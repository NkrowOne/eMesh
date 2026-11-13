"""📜 Activity of a network: every change of a chat is stored (``Event``) and, when asked, sent as an alert to the
owner and the admins of the bot that have 🔔 alerts on.

Usage (any module)::

    await events.emit(bot, session, ctx.ws_rec, EventKind.CHAT_PAUSED, chat=chat, actor_id=ctx.user_id,
                      data={"by": "owner", "until": until.isoformat() if until else None})

``bot`` is the aiogram Bot of the network (``ctx.ws_bot()``, or the engine's bot): alerts go out through it, so the
admins get them in the bot they manage. Without a bot (not running) the event is only stored.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import BotUser, Event, EventKind, User
from app.i18n import t
from app.services.notify import send_dm
from app.services.users import admin_ids
from app.ui.callbacks import MenuCB
from app.ui.common import btn, kb
from app.ui.fmt import dt, esc, user_link

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models import Bot as BotRecord
    from app.db.models import Chat

log = logging.getLogger(__name__)

# Kinds an admin is alerted about by default (others are only logged unless ``notify=True`` is passed).
ALERT_KINDS = frozenset({
    EventKind.CHAT_PAUSED, EventKind.CHAT_RESUMED, EventKind.CHAT_LEFT, EventKind.CHAT_REMOVED,
    EventKind.CHAT_RIGHTS, EventKind.CHAT_RIGHTS_OK, EventKind.CHAT_JOINED,
})
ICONS = {
    EventKind.CHAT_ADDED: "➕", EventKind.CHAT_REQUEST: "📨", EventKind.CHAT_JOINED: "🤝",
    EventKind.CHAT_REJECTED: "❌", EventKind.CHAT_BANNED: "🚫", EventKind.CHAT_PAUSED: "⏸",
    EventKind.CHAT_RESUMED: "▶️", EventKind.CHAT_LEFT: "🚪", EventKind.CHAT_REMOVED: "🗑",
    EventKind.CHAT_RIGHTS: "⚠️", EventKind.CHAT_RIGHTS_OK: "✅", EventKind.BOT_PAUSED: "⏸",
    EventKind.BOT_RESUMED: "▶️", EventKind.POST_MISSED: "⚠️",
}


async def _actor_label(session: AsyncSession, actor_id: int | None) -> str:
    if not actor_id:
        return ""
    user = await session.get(User, actor_id)
    if user is None:
        return user_link(actor_id)
    return user_link(user.id, user.full_name, user.username)


def _until_text(data: dict[str, Any], lang: str, tz: str) -> str:
    until = data.get("until")
    if not until:
        return t("ev.until.none", lang)
    try:
        when = datetime.fromisoformat(str(until))
    except ValueError:
        return t("ev.until.none", lang)
    return t("ev.until.date", lang, date=dt(when, tz))


def _due_text(data: dict[str, Any], tz: str) -> str:
    try:
        return dt(datetime.fromisoformat(str(data.get("due"))), tz)
    except ValueError:
        return "—"


def render(kind: str, lang: str, tz: str, *, chat_title: str, actor: str, data: dict[str, Any] | None) -> str:
    """The sentence of an event (HTML): used both for alerts and for the activity list."""
    data = data or {}
    by = str(data.get("by") or "")
    title = esc(chat_title or "?")
    key = f"ev.{kind}"
    if kind in (EventKind.CHAT_PAUSED, EventKind.CHAT_RESUMED, EventKind.CHAT_REMOVED, EventKind.CHAT_JOINED) and by:
        key = f"ev.{kind}.{by}"
    if kind == EventKind.POST_MISSED:
        key = f"ev.{kind}.{'late' if data.get('reason') == 'late' else 'no_chats'}"
    missing = ", ".join(t(f"rights.{r}", lang) for r in str(data.get("missing") or "").split(",") if r)
    return t(key, lang, chat=title, actor=actor or t("ev.someone", lang), until=_until_text(data, lang, tz),
             missing=esc(missing), reason=esc(data.get("reason") or ""), post=esc(data.get("post") or "?"),
             due=_due_text(data, tz))


async def describe(session: AsyncSession, ev: Event, lang: str, tz: str) -> str:
    """``⏸ 07/11/2026 10:00 AM · Canal X pausado por su dueño…`` for the activity list."""
    actor = await _actor_label(session, ev.actor_id)
    text = render(ev.kind, lang, tz, chat_title=ev.chat_title, actor=actor, data=ev.data)
    return f"{ICONS.get(ev.kind, '•')} <i>{dt(ev.created_at, tz)}</i>\n{text}"


async def emit(
    bot: Bot | None,
    session: AsyncSession,
    ws_rec: BotRecord,
    kind: str,
    *,
    chat: Chat | None = None,
    actor_id: int | None = None,
    data: dict[str, Any] | None = None,
    notify: bool | None = None,
    skip_user: int | None = None,
    markup: InlineKeyboardMarkup | None = None,
) -> Event:
    """Stores the event and alerts the owner and admins with 🔔 alerts on (``notify`` None = the default of the
    kind). ``skip_user``: who caused it (no alert to themselves). Never raises because of Telegram."""
    ev = Event(bot_id=ws_rec.id, chat_pk=chat.id if chat is not None else None,
               chat_title=(chat.display_title if chat is not None else "")[:256], kind=kind, actor_id=actor_id,
               data=dict(data or {}), created_at=utcnow())
    session.add(ev)
    await session.flush()
    if notify is None:
        notify = kind in ALERT_KINDS
    if not notify or bot is None:
        return ev
    actor = await _actor_label(session, actor_id)
    for uid in await admin_ids(session, ws_rec):
        if uid == skip_user:
            continue
        bu = await session.get(BotUser, (ws_rec.id, uid))
        if bu is None or not bu.notify or bu.is_blocked:
            continue
        tz = bu.timezone or ws_rec.timezone
        text = f"{ICONS.get(kind, '🔔')} " + render(kind, bu.lang, tz, chat_title=ev.chat_title, actor=actor,
                                                    data=ev.data)
        reply = markup or _default_markup(ev, bu.lang)
        await send_dm(bot, session, uid, text, reply)
    return ev


def _default_markup(ev: Event, lang: str) -> InlineKeyboardMarkup | None:
    if ev.kind == EventKind.POST_MISSED:
        post_id = int((ev.data or {}).get("post_id") or 0)
        return kb([btn(t("ev.btn.post", lang), MenuCB(screen="post", arg=post_id)),
                   btn(t("ev.btn.activity", lang), MenuCB(screen="activity"))])
    if ev.chat_pk is None or ev.kind in (EventKind.CHAT_LEFT, EventKind.CHAT_REMOVED):
        return kb([btn(t("ev.btn.activity", lang), MenuCB(screen="activity"))])
    return kb([btn(t("ev.btn.chat", lang), MenuCB(screen="chat", arg=ev.chat_pk)),
               btn(t("ev.btn.activity", lang), MenuCB(screen="activity"))])


async def recent(session: AsyncSession, bot_id: int, *, limit: int = 20, offset: int = 0,
                 chat_pk: int | None = None, kinds: list[str] | None = None) -> list[Event]:
    """Newest first."""
    q = select(Event).where(Event.bot_id == bot_id)
    if chat_pk is not None:
        q = q.where(Event.chat_pk == chat_pk)
    if kinds:
        q = q.where(Event.kind.in_(kinds))
    q = q.order_by(Event.created_at.desc(), Event.id.desc()).offset(offset).limit(limit)
    return list((await session.execute(q)).scalars())
