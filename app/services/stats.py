"""Numbers of a network for the home screen, 📊 Estadísticas and the 👑 panel."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.db.base import utcnow
from app.db.models import (
    Chat,
    ChatGroup,
    ChatOrigin,
    ChatStatus,
    Delivery,
    DeliveryStatus,
    Post,
    PostStatus,
    Run,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class Summary:
    chats: int = 0  # approved chats
    own: int = 0
    external: int = 0
    members: int = 0  # members of the approved chats
    sendable: int = 0  # approved, with rights and not paused
    pending: int = 0  # waiting for approval (external) or for rights
    owner_paused: int = 0  # ⏸ paused by their owner (partners)
    admin_paused: int = 0
    no_rights: int = 0  # approved but missing rights
    groups: int = 0
    posts_active: int = 0
    posts_total: int = 0
    runs: int = 0  # in the period
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    reach: int = 0  # members of the chats the runs were sent to
    top_posts: list[tuple[str, int]] = field(default_factory=list)  # (name, deliveries sent) in the period


async def summary(session: AsyncSession, bot_id: int, *, hours: int = 24, now: datetime | None = None) -> Summary:
    """Chats, posts and the activity of the last ``hours``."""
    now = now or utcnow()
    out = Summary()
    chats = (await session.execute(select(Chat).where(Chat.bot_id == bot_id))).scalars().all()
    for c in chats:
        if c.status == ChatStatus.PENDING:
            out.pending += 1
            continue
        if c.status != ChatStatus.APPROVED:
            continue
        out.chats += 1
        out.members += c.members or 0
        if c.origin == ChatOrigin.EXTERNAL:
            out.external += 1
        else:
            out.own += 1
        if c.owner_pause_active(now):
            out.owner_paused += 1
        if c.admin_paused:
            out.admin_paused += 1
        if not c.rights_ok:
            out.no_rights += 1
        if c.rights_ok and not c.vault and not c.is_paused(now):
            out.sendable += 1
    out.groups = int((await session.execute(
        select(func.count()).select_from(ChatGroup).where(ChatGroup.bot_id == bot_id))).scalar() or 0)
    rows = (await session.execute(
        select(Post.status, func.count()).where(Post.bot_id == bot_id).group_by(Post.status))).all()
    for status, n in rows:
        out.posts_total += int(n)
        if status == PostStatus.ACTIVE:
            out.posts_active += int(n)
    since = now - timedelta(hours=hours)
    row = (await session.execute(
        select(func.count(), func.coalesce(func.sum(Run.sent), 0), func.coalesce(func.sum(Run.failed), 0),
               func.coalesce(func.sum(Run.skipped), 0), func.coalesce(func.sum(Run.reach), 0))
        .where(Run.bot_id == bot_id, Run.started_at >= since))).one()
    out.runs, out.sent, out.failed, out.skipped, out.reach = (int(x or 0) for x in row)
    top = (await session.execute(
        select(Run.post_name, func.sum(Run.sent)).where(Run.bot_id == bot_id, Run.started_at >= since)
        .group_by(Run.post_name).order_by(func.sum(Run.sent).desc()).limit(5))).all()
    out.top_posts = [(name or "—", int(n or 0)) for name, n in top if n]
    return out


async def chat_received(session: AsyncSession, chat_pk: int, *, days: int = 7, now: datetime | None = None) -> int:
    """Posts delivered in a chat in the last ``days``."""
    since = (now or utcnow()) - timedelta(days=days)
    q = select(func.count()).select_from(Delivery).where(
        Delivery.chat_pk == chat_pk, Delivery.sent_at >= since,
        Delivery.status.in_([DeliveryStatus.SENT, DeliveryStatus.DELETED, DeliveryStatus.MISSING,
                             DeliveryStatus.EXPIRED]))
    return int((await session.execute(q)).scalar() or 0)
