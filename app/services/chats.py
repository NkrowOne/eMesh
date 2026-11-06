"""Channels and groups of a network: admission of new chats (own, external with or without approval), the admins'
decisions, pauses, removal and the chats where the bot already is an administrator.

Shared by the chats routers (``chat_events``, ``requests``, ``chats``, ``partners``) and the other modules
(docs/ARCHITECTURE.md, section 7). Every function changes the rows in place and sends the related messages; the
caller commits.
"""
from __future__ import annotations

import asyncio
import logging
import weakref
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramMigrateToChat
from aiogram.filters.callback_data import CallbackData
from aiogram.types import ChatFullInfo, InlineKeyboardMarkup
from sqlalchemy import delete, select

from app.db.base import utcnow
from app.db.models import Chat, ChatGroup, ChatOrigin, ChatStatus, EventKind, RequestNotice, User
from app.i18n import t
from app.services import audience, events, limits, moderation
from app.services.chatinfo import apply_rights, chat_type_of
from app.services.chatstate import kind_word, rights_text
from app.services.notify import notify_admins, send_dm
from app.services.users import admin_ids, get_lang
from app.telegram.errors import short
from app.ui.callbacks import MenuCB
from app.ui.common import btn, kb
from app.ui.fmt import dt, esc, link, num, truncate, user_link

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.config import Settings
    from app.db.models import Bot as BotRecord
    from app.services.publisher import Publisher

log = logging.getLogger(__name__)


class RqCB(CallbackData, prefix="rq"):
    """Requests and rights checks (handled by ``routers/requests.py``)."""

    a: str  # ok accept · no reject (asks the reason) · nr reject without reason · chk check the rights · pg page
    pk: int = 0  # chat pk
    s: int = 0  # where it was pressed: SRC_NOTICE / SRC_LIST / SRC_CHAT
    p: int = 0  # page of the requests list


SRC_NOTICE, SRC_LIST, SRC_CHAT = 0, 1, 2

ACTIVE = (ChatStatus.APPROVED, ChatStatus.PENDING)  # in the network (listed); the others are out of it
CHAT_TYPES = frozenset({"channel", "group", "supergroup"})

# register_existing() outcomes
ADDED, EXISTING, NOT_ADMIN, NOT_FOUND, PENDING, LIMIT, REJECTED = (
    "added", "existing", "not_admin", "not_found", "pending", "limit", "rejected")


# --------------------------------------------------------------------------- presentation
def chat_icon(chat: Chat) -> str:
    return "📣" if chat.is_channel else "👥"


def chat_name(chat: Chat, limit: int = 0) -> str:
    """The title as HTML, a link when the chat is public."""
    title = truncate(chat.display_title, limit) if limit else chat.display_title
    return link(chat.public_link, title)


def missing_list(chat: Chat) -> list[str]:
    return [r for r in (chat.missing_rights or "").split(",") if r]


def user_label(user: User | None) -> str:
    """Plain text (buttons): ``@username`` or the name."""
    if user is None:
        return ""
    return f"@{user.username}" if user.username else user.full_name


def owner_html(chat: Chat, owners: dict[int, User]) -> str:
    """``@pepe`` (or a link to the user) of the chat's owner, ``""`` when unknown."""
    uid = chat.owner_user_id
    if not uid:
        return ""
    user = owners.get(uid)
    return user_link(uid, user.full_name, user.username) if user else user_link(uid)


async def users_by_id(session: AsyncSession, ids: set[int | None]) -> dict[int, User]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return {u.id: u for u in (await session.execute(select(User).where(User.id.in_(wanted)))).scalars()}


def status_icon(chat: Chat, now: datetime | None = None) -> str:
    """✅ receives posts · ⏸ paused · ⏳ pending · ⚠️ missing rights (❌ / 🚫 / 🚪 when out of the network)."""
    if chat.status == ChatStatus.PENDING:
        return "⏳" if chat.rights_ok else "⏳⚠️"
    if chat.status != ChatStatus.APPROVED:
        return {ChatStatus.REJECTED: "❌", ChatStatus.BANNED: "🚫", ChatStatus.LEFT: "🚪"}.get(chat.status, "❔")
    icon = ("" if chat.rights_ok else "⚠️") + ("⏸" if chat.is_paused(now) else "")
    return icon or "✅"


def status_parts(chat: Chat, lang: str, tz: str, *, partner: bool = False, now: datetime | None = None) -> list[str]:
    """What a chat's status line says, for the admins (``ch.st.*``) or for its owner (``pa.st.*``)."""
    p = "pa.st." if partner else "ch.st."
    if chat.status in (ChatStatus.REJECTED, ChatStatus.BANNED, ChatStatus.LEFT):
        return [t(p + chat.status, lang)]
    rights = rights_text(missing_list(chat) or ["admin"], lang)
    if chat.status == ChatStatus.PENDING:
        return [t(p + "pending", lang) if chat.rights_ok else t(p + "pending_rights", lang, rights=rights)]
    parts: list[str] = []
    if not chat.rights_ok:
        parts.append(t(p + "rights", lang, rights=rights))
    if chat.owner_pause_active(now):
        parts.append(t(p + "owner_paused", lang, date=dt(chat.owner_paused_until, tz)) if chat.owner_paused_until
                     else t(p + "owner_paused_open", lang))
    if chat.admin_paused:
        parts.append(t(p + "admin_paused", lang))
    return parts or [t(p + "ok", lang)]


def status_text(chat: Chat, lang: str, tz: str, *, partner: bool = False) -> str:
    return " · ".join(status_parts(chat, lang, tz, partner=partner))


async def open_groups_of(session: AsyncSession, ws_id: int, chat_pk: int) -> list[ChatGroup]:
    """The 🤝 open groups the chat is in (its "categories")."""
    member = await audience.chat_group_ids(session, chat_pk)
    return [g for g in await audience.bot_groups(session, ws_id) if g.open and g.id in member]


def names_text(names: list[str], limit: int, width: int = 0) -> str:
    """``Cine, Series +3`` (HTML): the first ``limit`` names (cut to ``width`` characters, 0 = whole) and how many
    more there are. A chat can be in many groups: the message must stay within Telegram's 4096 characters."""
    shown = [esc(truncate(n, width) if width else n) for n in names[:limit]]
    more = len(names) - len(shown)
    return ", ".join(shown) + (f" +{more}" if more else "")


def group_names(groups: list[ChatGroup], limit: int = 10) -> str:
    return names_text([g.name for g in groups], limit)


# --------------------------------------------------------------------------- queries
async def chat_row(session: AsyncSession, bot_id: int, chat_id: int) -> Chat | None:
    q = select(Chat).where(Chat.bot_id == bot_id, Chat.chat_id == chat_id)
    return (await session.execute(q)).scalars().first()


async def listed_chats(session: AsyncSession, ws_id: int) -> list[Chat]:
    """The chats of the network (approved and pending), by title."""
    chats = await audience.bot_chats(session, ws_id, statuses=list(ACTIVE))
    return sorted(chats, key=lambda c: (c.display_title.casefold(), c.id))


async def partner_ids(session: AsyncSession, ws_id: int) -> list[int]:
    """Owners of the network's external chats (partners), for 📢 Avisar a los dueños."""
    q = (select(Chat.owner_user_id)
         .where(Chat.bot_id == ws_id, Chat.origin == ChatOrigin.EXTERNAL, Chat.status.in_(list(ACTIVE)),
                Chat.owner_user_id.is_not(None))
         .distinct())
    return sorted(uid for (uid,) in await session.execute(q))


# --------------------------------------------------------------------------- one change at a time per chat
# The updates of one chat (the bot added, promoted, removed), the admins' decisions on it and the rights checks of
# its owner are applied one at a time, commit included: aiogram only keeps apart the updates of one user.
_locks: weakref.WeakValueDictionary[tuple[int, int], asyncio.Lock] = weakref.WeakValueDictionary()


def chat_lock(bot_id: int, chat_id: int) -> asyncio.Lock:
    key = (bot_id, chat_id)
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


# --------------------------------------------------------------------------- messages
async def owner_lang(session: AsyncSession, chat: Chat, default: str = "es") -> str:
    if not chat.owner_user_id:
        return default
    return await get_lang(session, chat.bot_id, chat.owner_user_id, default)


async def dm_owner(bot: Bot, session: AsyncSession, chat: Chat, text: str,
                   markup: InlineKeyboardMarkup | None = None) -> None:
    if chat.owner_user_id:
        await send_dm(bot, session, chat.owner_user_id, text, markup)


async def _tell_partner(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat, key: str) -> None:
    """DM the owner of an external chat (the admins learn it from the event alert)."""
    uid = chat.owner_user_id
    if not chat.is_external or not uid or uid in await admin_ids(session, ws_rec):
        return
    lang = await owner_lang(session, chat)
    await send_dm(bot, session, uid, t(key, lang, kind=kind_word(chat, lang), chat=esc(chat.display_title)))


async def leave_chat(bot: Bot, chat: Chat) -> None:
    try:
        await bot.leave_chat(chat.chat_id)
    except TelegramAPIError as exc:
        log.info("leaveChat %s failed: %s", chat.chat_id, short(exc))
    chat.rights_ok = False


async def count_members(bot: Bot, chat: Chat) -> bool:
    """Updates the member count; False when it could not be read."""
    try:
        chat.members = await bot.get_chat_member_count(chat.chat_id)
    except TelegramAPIError as exc:
        log.info("getChatMemberCount %s failed: %s", chat.chat_id, short(exc))
        return False
    chat.members_at = utcnow()
    return True


# --------------------------------------------------------------------------- admin notices of a request
def notice_view(chat: Chat, owner: User | None, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    lines = [t("rq.notice.title", lang)]
    if chat.owner_user_id:
        who = user_link(owner.id, owner.full_name, owner.username) if owner else user_link(chat.owner_user_id)
        lines.append(t("rq.notice.who", lang, user=who))
    lines.append(t("rq.notice.chat", lang, icon=chat_icon(chat), chat=esc(chat.display_title),
                   members=num(chat.members)))
    lines.append(t("rq.notice.id_link", lang, id=chat.chat_id, link=esc(chat.public_link)) if chat.public_link
                 else t("rq.notice.id", lang, id=chat.chat_id))
    markup = kb([btn(t("rq.btn.accept", lang), RqCB(a="ok", pk=chat.id), style="success"),
                 btn(t("rq.btn.reject", lang), RqCB(a="no", pk=chat.id), style="danger")])
    return "\n".join(lines), markup


async def send_notices(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat) -> int:
    await session.execute(delete(RequestNotice).where(RequestNotice.chat_pk == chat.id))
    owner = await session.get(User, chat.owner_user_id) if chat.owner_user_id else None
    sent = await notify_admins(bot, session, ws_rec, lambda lang: notice_view(chat, owner, lang))
    session.add_all(RequestNotice(chat_pk=chat.id, user_id=uid, message_id=mid) for uid, mid in sent)
    await session.flush()
    return len(sent)


async def close_notices(bot: Bot, session: AsyncSession, chat: Chat, label_key: str,
                        by_user: int | None = None) -> None:
    """Every admin notice of ``chat`` gets a disabled button saying what happened (``✅ Aceptada · @admin``)."""
    notices = (await session.execute(select(RequestNotice).where(RequestNotice.chat_pk == chat.id))).scalars().all()
    if not notices:
        return
    who = user_label(await session.get(User, by_user)) if by_user else ""
    for notice in notices:
        label = t(label_key, await get_lang(session, chat.bot_id, notice.user_id))
        if who:
            label = f"{label} · {who}"
        try:
            await bot.edit_message_reply_markup(chat_id=notice.user_id, message_id=notice.message_id,
                                                reply_markup=kb([btn(truncate(label, 64), disabled=True)]))
        except TelegramAPIError as exc:
            log.info("Request notice %s/%s not closed: %s", notice.user_id, notice.message_id, short(exc))
    await session.execute(delete(RequestNotice).where(RequestNotice.chat_pk == chat.id))


# --------------------------------------------------------------------------- missing rights
def recheck_markup(chat: Chat, lang: str) -> InlineKeyboardMarkup:
    return kb([btn(t("rq.btn.recheck", lang), RqCB(a="chk", pk=chat.id))])


def missing_text(chat: Chat, missing: list[str], lang: str) -> str:
    items = "\n".join(f"• {t(f'rights.{r}', lang)}" for r in missing)
    return t("rq.dm.missing", lang, kind=kind_word(chat, lang), chat=esc(chat.display_title), rights=items)


async def dm_missing_rights(bot: Bot, session: AsyncSession, chat: Chat, missing: list[str]) -> None:
    """Whoever added the bot learns what to grant, with [🔄 Comprobar de nuevo]."""
    lang = await owner_lang(session, chat)
    await dm_owner(bot, session, chat, missing_text(chat, missing, lang), recheck_markup(chat, lang))


# --------------------------------------------------------------------------- admission and decisions
def _decide(chat: Chat, status: str, by_user: int | None) -> None:
    chat.status = status
    chat.decided_by = by_user
    chat.decided_at = utcnow()


async def _welcome(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat, *, accepted: bool) -> None:
    lang = await owner_lang(session, chat)
    kw = {"kind": kind_word(chat, lang), "chat": esc(chat.display_title), "bot": esc(ws_rec.username)}
    if not chat.is_external:
        markup = kb([btn(t("ce.btn.add_groups", lang), MenuCB(screen="chat_groups", arg=chat.id))])
        await dm_owner(bot, session, chat, t("ce.dm.own_added", lang, **kw), markup)
        return
    lines = [t("rq.dm.accepted" if accepted else "ce.dm.joined", lang, **kw)]
    names = group_names(await open_groups_of(session, ws_rec.id, chat.id))
    if names:
        lines.append(t("ce.dm.categories", lang, names=names))
    if ws_rec.partners_can_pause:
        lines.append(t("ce.dm.pause_hint", lang))
    markup = kb([btn(t("ce.btn.my_chats", lang), MenuCB(screen="my_chats"))])
    await dm_owner(bot, session, chat, "\n\n".join(lines), markup)


async def approve(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat, by_user: int | None, *,
                  notify: bool = True) -> None:
    """Accepts ``chat`` in the network (``by_user``: the admin who accepted it; None = automatic). External chats
    join every 🤝 open group, the admin notices are closed, the event is logged (alerting the other admins) and the
    owner is told (``notify``)."""
    _decide(chat, ChatStatus.APPROVED, by_user)
    chat.reject_reason = None
    chat.approved_at = chat.decided_at
    if chat.is_external:
        await audience.join_open_groups(session, ws_rec.id, chat.id)
    await close_notices(bot, session, chat, "rq.closed.accepted", by_user)
    actor = by_user or chat.owner_user_id
    if chat.is_external:
        await events.emit(bot, session, ws_rec, EventKind.CHAT_JOINED, chat=chat, actor_id=actor, skip_user=by_user,
                          data={"by": "admin"} if by_user else None)
    else:
        await events.emit(bot, session, ws_rec, EventKind.CHAT_ADDED, chat=chat, actor_id=actor, notify=True,
                          skip_user=actor)
    if notify:
        await _welcome(bot, session, ws_rec, chat, accepted=by_user is not None)


async def request(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat) -> None:
    """An external chat waits for an admin: its owner is told, the event is logged and the admins get a notice
    with ✅ Aceptar / ❌ Rechazar (only once: a chat that lost and got back its rights while waiting keeps them; the
    notices of a chat that left are closed, so one that comes back is asked again)."""
    chat.status = ChatStatus.PENDING
    sent = await session.execute(select(RequestNotice.id).where(RequestNotice.chat_pk == chat.id).limit(1))
    if sent.first() is not None:
        return
    lang = await owner_lang(session, chat)
    await dm_owner(bot, session, chat, t("rq.dm.sent", lang, kind=kind_word(chat, lang),
                                         chat=esc(chat.display_title)))
    await events.emit(bot, session, ws_rec, EventKind.CHAT_REQUEST, chat=chat, actor_id=chat.owner_user_id)
    await send_notices(bot, session, ws_rec, chat)


async def admit(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat, *, added_by_admin: bool = False,
                force_request: bool = False, notify: bool = True) -> str:
    """A chat whose rights are fine enters the network: own chats, chats added by an admin, chats accepted before
    (back after the bot was removed) and external chats of a network without approval enter at once; the other
    external chats (and every one with ``force_request``) wait for an admin. Returns the new status."""
    direct = (added_by_admin or chat.origin == ChatOrigin.OWN or chat.approved_at is not None
              or not ws_rec.join_approval)
    if direct and not force_request:
        await approve(bot, session, ws_rec, chat, None, notify=notify)
        return ChatStatus.APPROVED
    await request(bot, session, ws_rec, chat)
    return ChatStatus.PENDING


async def refuse(bot: Bot, session: AsyncSession, chat: Chat, reason: str, text: str) -> None:
    """Automatic rejection (too few members, platform words): the owner is told and the bot leaves."""
    _decide(chat, ChatStatus.REJECTED, None)
    chat.reject_reason = reason
    chat.approved_at = None
    await dm_owner(bot, session, chat, text)
    await session.flush()  # the decision is written before the bot's own "left" update can arrive
    await leave_chat(bot, chat)


async def check_external(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat, *,
                         description: str | None, counted: bool) -> bool:
    """An external chat needs the network's minimum of members and no platform blocked word (the word is never
    shown). False: it was refused and the bot left."""
    lang = await owner_lang(session, chat)
    kw = {"kind": kind_word(chat, lang), "chat": esc(chat.display_title)}
    if ws_rec.min_members and counted and (chat.members or 0) < ws_rec.min_members:
        nums = {"min": num(ws_rec.min_members), "members": num(chat.members)}
        await refuse(bot, session, chat, t("ce.reason.min_members", lang, **nums),
                     t("ce.dm.min_members", lang, **kw, **nums))
        return False
    if await moderation.check_chat(session, chat.title, chat.username, description):
        await refuse(bot, session, chat, t("ce.reason.words", lang), t("ce.dm.words", lang, **kw))
        return False
    return True


async def reject(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat, by_user: int | None,
                 reason: str | None, *, leave: bool = True) -> None:
    """Rejects a request: the admin notices are closed, the owner is told (with the reason) and the bot leaves the
    chat (``leave``). Adding the bot again later is a new request."""
    _decide(chat, ChatStatus.REJECTED, by_user)
    chat.reject_reason = reason
    chat.approved_at = None
    await close_notices(bot, session, chat, "rq.closed.rejected", by_user)
    await events.emit(bot, session, ws_rec, EventKind.CHAT_REJECTED, chat=chat, actor_id=by_user,
                      data={"reason": reason} if reason else None)
    if chat.owner_user_id != by_user:
        lang = await owner_lang(session, chat)
        text = t("rq.dm.rejected", lang, kind=kind_word(chat, lang), chat=esc(chat.display_title))
        if reason:
            text += "\n" + t("rq.dm.reason", lang, reason=esc(reason))
        await dm_owner(bot, session, chat, text)
    if leave:
        await session.flush()
        await leave_chat(bot, chat)


async def remove(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat, by_user: int | None, *,
                 publisher: Publisher, ban: bool = False, by_owner: bool = False) -> None:
    """Takes ``chat`` out of the network: its posts still up there are deleted first (the bot can't once it is out),
    then the bot leaves. Status ``left`` (adding the bot again is a new admission) or ``banned`` (``ban``: adding it
    again is refused). ``by_owner``: the partner left the network from their panel (an admin's pause stays: it is
    not theirs to lift)."""
    await publisher.drop_chat(chat.id)
    _decide(chat, ChatStatus.BANNED if ban else ChatStatus.LEFT, by_user)
    chat.approved_at = None
    chat.owner_paused = False
    chat.owner_paused_until = None
    if not by_owner:
        chat.admin_paused = False
    if not chat.admin_paused:
        chat.paused_at = None
    await close_notices(bot, session, chat, "rq.closed.banned" if ban else "rq.closed.removed", by_user)
    await session.flush()
    await leave_chat(bot, chat)
    if ban:
        await events.emit(bot, session, ws_rec, EventKind.CHAT_BANNED, chat=chat, actor_id=by_user, notify=True,
                          skip_user=by_user)
    else:
        await events.emit(bot, session, ws_rec, EventKind.CHAT_REMOVED, chat=chat, actor_id=by_user,
                          data={"by": "owner" if by_owner else "admin"}, skip_user=by_user)
    if not by_owner:
        await _tell_partner(bot, session, ws_rec, chat, "ch.dm.banned" if ban else "ch.dm.removed")


# --------------------------------------------------------------------------- pauses
def pause_allowed(ws_rec: BotRecord, length: timedelta | None) -> bool:
    """The admins' rules let a partner pause their chat for ``length`` (None: until they resume it): partners may
    pause (``Bot.partners_can_pause``) for at most ``Bot.pause_max_hours`` (0: no limit, the only case that allows a
    pause without an end)."""
    if not ws_rec.partners_can_pause:
        return False
    if not ws_rec.pause_max_hours:
        return True
    return length is not None and length <= timedelta(hours=ws_rec.pause_max_hours)


async def pause_by_owner(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat, user_id: int,
                         until: datetime | None) -> bool:
    """⏸ The partner pauses the distribution in their chat until ``until`` (None: until they resume it). Refused
    (False, nothing changes) when the admins' rules don't allow it (:func:`pause_allowed`). The admins are alerted;
    the partner resumes it whenever they want, an admin at any time, or it ends by itself."""
    now = utcnow()
    if not pause_allowed(ws_rec, until - now if until is not None else None):
        return False
    if not chat.is_paused(now):
        chat.paused_at = now
    chat.owner_paused = True
    chat.owner_paused_until = until
    await events.emit(bot, session, ws_rec, EventKind.CHAT_PAUSED, chat=chat, actor_id=user_id,
                      data={"by": "owner", "until": until.isoformat() if until else None}, skip_user=user_id)
    return True


async def resume_by_owner(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat, user_id: int) -> None:
    chat.owner_paused = False
    chat.owner_paused_until = None
    if not chat.admin_paused:
        chat.paused_at = None
    await events.emit(bot, session, ws_rec, EventKind.CHAT_RESUMED, chat=chat, actor_id=user_id,
                      data={"by": "owner"}, skip_user=user_id)


async def pause_by_admin(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat, user_id: int) -> None:
    """⏸ An admin pauses the distribution in a chat: only an admin resumes it. Its partner is told."""
    if not chat.is_paused():
        chat.paused_at = utcnow()
    chat.admin_paused = True
    await events.emit(bot, session, ws_rec, EventKind.CHAT_PAUSED, chat=chat, actor_id=user_id,
                      data={"by": "admin", "until": None}, skip_user=user_id)
    await _tell_partner(bot, session, ws_rec, chat, "ch.dm.paused")


async def resume_by_admin(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat, user_id: int) -> None:
    """▶️ An admin resumes the distribution in a chat. The admins rule over the partners: it lifts an admin's pause
    and its partner's pause too. One event (alerting the other admins); the partner is told."""
    chat.admin_paused = False
    chat.owner_paused = False
    chat.owner_paused_until = None
    chat.paused_at = None
    await events.emit(bot, session, ws_rec, EventKind.CHAT_RESUMED, chat=chat, actor_id=user_id,
                      data={"by": "admin"}, skip_user=user_id)
    await _tell_partner(bot, session, ws_rec, chat, "ch.dm.resumed")


# --------------------------------------------------------------------------- chats where the bot already is admin
_registering: set[tuple[int, int]] = set()


async def _resolve(bot: Bot, ref: int | str) -> ChatFullInfo | None:
    target = ref
    for _ in range(2):
        try:
            full = await bot.get_chat(target)
        except TelegramMigrateToChat as exc:
            target = exc.migrate_to_chat_id
            continue
        except TelegramAPIError as exc:
            log.info("getChat %s failed: %s", target, short(exc))
            return None
        return full if full.type in CHAT_TYPES else None
    return None


async def _origin_of(bot: Bot, chat_id: int, net_admins: set[int]) -> tuple[str, int | None]:
    """Own when one of the chat's administrators administers the network (that one is its owner), external
    otherwise (owned by the chat's creator)."""
    try:
        members = await bot.get_chat_administrators(chat_id)
    except TelegramAPIError as exc:
        log.info("getChatAdministrators %s failed: %s", chat_id, short(exc))
        return ChatOrigin.EXTERNAL, None
    humans = [m for m in members if not m.user.is_bot]
    creator = next((m.user.id for m in humans if m.status == ChatMemberStatus.CREATOR), None)
    ours = [m.user.id for m in humans if m.user.id in net_admins]
    if ours:
        return ChatOrigin.OWN, creator if creator in ours else ours[0]
    return ChatOrigin.EXTERNAL, creator or (humans[0].user.id if humans else None)


async def register_existing(bot: Bot, session: AsyncSession, ws_rec: BotRecord, ref: int | str, *,
                            added_by: int | None = None, settings: Settings | None = None) -> str:
    """Registers a channel or group (id or ``@username``) where the bot already is an administrator, as if it had
    just been added: by ``added_by`` (an admin importing it: an own chat), or else by the chat's administrators (own
    when one of them administers the network). External chats always wait for an admin: their owners didn't ask now.

    Returns ``added``, ``pending`` (missing rights or waiting for an admin), ``existing``, ``not_admin``,
    ``not_found``, ``limit`` or ``rejected`` (an external chat with a platform blocked word: the bot left).
    ``settings`` (the limits): the app's settings when not given.
    """
    full = await _resolve(bot, ref)
    if full is None:
        return NOT_FOUND
    key = (ws_rec.id, full.id)
    if key in _registering:
        return EXISTING
    _registering.add(key)
    try:
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        return await _register(bot, session, ws_rec, full, added_by, settings)
    finally:
        _registering.discard(key)


async def _register(bot: Bot, session: AsyncSession, ws_rec: BotRecord, full: ChatFullInfo, added_by: int | None,
                    settings: Settings) -> str:
    chat = await chat_row(session, ws_rec.id, full.id)
    if chat is not None and chat.status not in (ChatStatus.LEFT, ChatStatus.REJECTED):
        return EXISTING
    try:
        member = await bot.get_chat_member(full.id, bot.id)
    except TelegramAPIError as exc:
        log.info("getChatMember %s failed: %s", full.id, short(exc))
        return NOT_ADMIN
    if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
        return NOT_ADMIN
    if not await limits.can_add_chat(session, settings, ws_rec):
        return LIMIT
    net_admins = set(await admin_ids(session, ws_rec)) | settings.super_admin_ids
    if added_by is not None and added_by in net_admins:
        origin, owner = ChatOrigin.OWN, added_by
    else:
        origin, owner = await _origin_of(bot, full.id, net_admins)
    if chat is None:
        chat = Chat(bot_id=ws_rec.id, chat_id=full.id, origin=origin)
        session.add(chat)
    chat.owner_user_id = owner or chat.owner_user_id  # a chat that comes back keeps its origin and its groups
    chat.status = ChatStatus.PENDING
    chat.reject_reason = None
    chat.title = (full.title or chat.title or "")[:256]
    chat.username = full.username
    chat.type = chat_type_of(full.type)
    missing = apply_rights(chat, member)
    await count_members(bot, chat)
    await session.flush()
    if chat.is_external and await moderation.check_chat(session, chat.title, chat.username, full.description):
        lang = await owner_lang(session, chat)
        await refuse(bot, session, chat, t("ce.reason.words", lang),
                     t("ce.dm.words", lang, kind=kind_word(chat, lang), chat=esc(chat.display_title)))
        return REJECTED
    if missing:
        await dm_missing_rights(bot, session, chat, missing)
        return PENDING
    status = await admit(bot, session, ws_rec, chat, force_request=chat.is_external, notify=added_by is None)
    return ADDED if status == ChatStatus.APPROVED else PENDING
