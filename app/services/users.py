"""User / role queries shared by all modules."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Bot as BotRecord
from app.db.models import BotUser, Role, User


async def admin_ids(session: AsyncSession, bot_rec: BotRecord) -> list[int]:
    """Owner first, then promoted admins of the bot (users that started it)."""
    rows = await session.execute(
        select(BotUser.user_id).where(BotUser.bot_id == bot_rec.id, BotUser.role == Role.ADMIN)
    )
    ids = [bot_rec.owner_id]
    ids.extend(uid for (uid,) in rows if uid != bot_rec.owner_id)
    return ids


async def admins(session: AsyncSession, bot_rec: BotRecord) -> list[BotUser]:
    rows = await session.execute(
        select(BotUser).where(BotUser.bot_id == bot_rec.id, BotUser.role == Role.ADMIN).order_by(BotUser.started_at)
    )
    return list(rows.scalars())


async def find_bot_user(session: AsyncSession, bot_id: int, query: str) -> BotUser | None:
    """Finds a user of this bot by ``@username`` or numeric id."""
    query = query.strip()
    if query.startswith("@"):
        query = query[1:]
    if query.lstrip("-").isdigit():
        return await session.get(BotUser, (bot_id, int(query)))
    if not query:
        return None
    row = await session.execute(
        select(BotUser)
        .join(User, User.id == BotUser.user_id)
        .where(BotUser.bot_id == bot_id, func.lower(User.username) == query.lower())
        # Telegram reuses usernames: the owner seen most recently wins over stale rows.
        .order_by(User.updated_at.desc(), User.id.desc())
    )
    return row.scalars().first()


async def get_lang(session: AsyncSession, bot_id: int, user_id: int, default: str = "es") -> str:
    bu = await session.get(BotUser, (bot_id, user_id))
    return bu.lang if bu else default


def role_of(settings: Settings, bot_rec: BotRecord, user_id: int, bu: BotUser | None) -> str:
    if user_id in settings.super_admin_ids:
        return Role.SUPER
    if user_id == bot_rec.owner_id:
        return Role.OWNER
    if bu is not None and bu.role == Role.ADMIN:
        return Role.ADMIN
    return Role.USER
