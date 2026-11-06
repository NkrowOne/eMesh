"""Platform settings (👑 Panel › ⚙️ Plataforma) and the limits of each bot.

Stored in KV ``platform:settings``; the environment variables are the defaults until a super admin changes them.
Limits: ``Bot.limit_chats`` / ``Bot.limit_posts`` (None = the platform default, 0 = unlimited). Main bots and the
bots of super admins have no limits.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.db.models import Chat, ChatStatus, Post, PostStatus
from app.services import kv

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.config import Settings
    from app.db.models import Bot as BotRecord

PLATFORM_KEY = "platform:settings"
POLICIES = ("open", "approval", "closed")


@dataclass
class Platform:
    clone_policy: str  # open: anyone creates a clone | approval: a super admin approves it | closed: nobody
    max_clones: int  # clones per user (0 = unlimited)
    limit_chats: int  # default chats per clone (0 = unlimited)
    limit_posts: int  # default posts per clone (0 = unlimited)


async def platform(session: AsyncSession, settings: Settings) -> Platform:
    stored = await kv.get(session, PLATFORM_KEY, {}) or {}
    p = Platform(clone_policy=settings.CLONE_POLICY, max_clones=settings.MAX_CLONES_PER_USER,
                 limit_chats=settings.DEFAULT_LIMIT_CHATS, limit_posts=settings.DEFAULT_LIMIT_POSTS)
    if isinstance(stored, dict):
        if stored.get("clone_policy") in POLICIES:
            p.clone_policy = stored["clone_policy"]
        for name in ("max_clones", "limit_chats", "limit_posts"):
            value = stored.get(name)
            if isinstance(value, int) and value >= 0:
                setattr(p, name, value)
    return p


async def save_platform(session: AsyncSession, p: Platform) -> None:
    await kv.put(session, PLATFORM_KEY, asdict(p))


def unlimited(settings: Settings, ws_rec: BotRecord) -> bool:
    return ws_rec.is_main or ws_rec.owner_id in settings.super_admin_ids


async def max_chats(session: AsyncSession, settings: Settings, ws_rec: BotRecord) -> int:
    """Chats the bot may have (0 = unlimited)."""
    if unlimited(settings, ws_rec):
        return 0
    if ws_rec.limit_chats is not None:
        return ws_rec.limit_chats
    return (await platform(session, settings)).limit_chats


async def max_posts(session: AsyncSession, settings: Settings, ws_rec: BotRecord) -> int:
    """Posts the bot may have (0 = unlimited)."""
    if unlimited(settings, ws_rec):
        return 0
    if ws_rec.limit_posts is not None:
        return ws_rec.limit_posts
    return (await platform(session, settings)).limit_posts


async def count_chats(session: AsyncSession, bot_id: int) -> int:
    """Chats that count for the limit: approved or pending."""
    q = select(func.count()).select_from(Chat).where(
        Chat.bot_id == bot_id, Chat.status.in_([ChatStatus.APPROVED, ChatStatus.PENDING]))
    return int((await session.execute(q)).scalar() or 0)


async def count_posts(session: AsyncSession, bot_id: int) -> int:
    """Posts that count for the limit: every post that isn't finished."""
    q = select(func.count()).select_from(Post).where(Post.bot_id == bot_id, Post.status != PostStatus.DONE)
    return int((await session.execute(q)).scalar() or 0)


async def can_add_chat(session: AsyncSession, settings: Settings, ws_rec: BotRecord) -> bool:
    limit = await max_chats(session, settings, ws_rec)
    return not limit or await count_chats(session, ws_rec.id) < limit


async def can_add_post(session: AsyncSession, settings: Settings, ws_rec: BotRecord) -> bool:
    limit = await max_posts(session, settings, ws_rec)
    return not limit or await count_posts(session, ws_rec.id) < limit
