"""State changes of a chat that both the engine and the screens make: the bot is gone, it lost or got back its
rights, and the periodic refresh (title, @username, members, rights).

Each function changes the row (the caller commits), logs the event (alerting the admins) and tells the chat's
owner when it is a partner (an external chat: admins already get the alert).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aiogram import Bot

from app.db.base import utcnow
from app.db.models import ChatStatus, EventKind
from app.i18n import t
from app.services import events
from app.services.chatinfo import inspect_chat
from app.services.notify import send_dm
from app.services.users import admin_ids, get_lang
from app.ui.fmt import esc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models import Bot as BotRecord
    from app.db.models import Chat

log = logging.getLogger(__name__)


def rights_text(missing: list[str] | str, lang: str) -> str:
    """``publicar mensajes, eliminar mensajes`` (i18n ``rights.<name>``)."""
    items = missing.split(",") if isinstance(missing, str) else missing
    return ", ".join(t(f"rights.{r}", lang) for r in items if r)


def kind_word(chat: Chat, lang: str) -> str:
    """``canal`` / ``grupo`` for sentences ("tu canal <b>X</b>")."""
    return t("common.channel_word" if chat.is_channel else "common.group_word", lang)


async def _tell_partner(bot: Bot | None, session: AsyncSession, ws_rec: BotRecord, chat: Chat, key: str,
                        missing: list[str] | None = None) -> None:
    """DM the owner of an external chat (admins get the event alert instead)."""
    uid = chat.owner_user_id
    if bot is None or not uid or uid in await admin_ids(session, ws_rec):
        return
    lang = await get_lang(session, ws_rec.id, uid)
    await send_dm(bot, session, uid, t(key, lang, chat=esc(chat.display_title), kind=kind_word(chat, lang),
                                       missing=esc(rights_text(missing or [], lang))))


async def mark_left(bot: Bot | None, session: AsyncSession, ws_rec: BotRecord, chat: Chat) -> bool:
    """The bot is no longer in the chat (removed, chat deleted). It stops receiving posts; its groups are kept in
    case it comes back. Returns False when it already was."""
    if chat.status == ChatStatus.LEFT:
        return False
    was_live = chat.status == ChatStatus.APPROVED
    chat.status = ChatStatus.LEFT
    chat.updated_at = utcnow()
    if was_live:
        await events.emit(bot, session, ws_rec, EventKind.CHAT_LEFT, chat=chat)
        await _tell_partner(bot, session, ws_rec, chat, "cs.left")
    else:
        await events.emit(bot, session, ws_rec, EventKind.CHAT_LEFT, chat=chat, notify=False)
    return True


async def mark_rights(bot: Bot | None, session: AsyncSession, ws_rec: BotRecord, chat: Chat,
                      missing: list[str]) -> bool:
    """The bot lacks required rights: no posts until they are back. Returns True when it just lost them."""
    was_ok = chat.rights_ok
    chat.rights_ok = False
    chat.missing_rights = ",".join(missing)[:256]
    if not was_ok or chat.status != ChatStatus.APPROVED:
        return False
    await events.emit(bot, session, ws_rec, EventKind.CHAT_RIGHTS, chat=chat, data={"missing": chat.missing_rights})
    await _tell_partner(bot, session, ws_rec, chat, "cs.rights", missing)
    return True


async def rights_restored(bot: Bot | None, session: AsyncSession, ws_rec: BotRecord, chat: Chat) -> bool:
    """The rights are back. Returns True when they had been missing."""
    was_ok = chat.rights_ok
    chat.rights_ok = True
    chat.missing_rights = ""
    if was_ok or chat.status != ChatStatus.APPROVED:
        return False
    await events.emit(bot, session, ws_rec, EventKind.CHAT_RIGHTS_OK, chat=chat)
    await _tell_partner(bot, session, ws_rec, chat, "cs.rights_ok")
    return True


@dataclass
class RefreshResult:
    gone: bool = False
    members_before: int = 0
    members_after: int = 0
    missing: list[str] = field(default_factory=list)
    lost_rights: bool = False
    got_rights: bool = False
    error: str | None = None


async def refresh(bot: Bot, session: AsyncSession, ws_rec: BotRecord, chat: Chat) -> RefreshResult:
    """Reads the chat from Telegram (title, @username, members, the bot's rights) and applies what changed:
    gone -> :func:`mark_left`, rights lost / back. Never raises because of Telegram. The caller commits."""
    before_ok = chat.rights_ok
    res = await inspect_chat(bot, chat)
    out = RefreshResult(members_before=res.members_before, members_after=res.members_after, missing=res.missing,
                        error=res.error)
    if res.gone:
        out.gone = True
        await mark_left(bot, session, ws_rec, chat)
        return out
    if res.rights_read:
        chat.rights_ok = before_ok  # inspect_chat applied the new rights: let the helpers compare and alert
        if res.missing:
            out.lost_rights = await mark_rights(bot, session, ws_rec, chat, res.missing)
        else:
            out.got_rights = await rights_restored(bot, session, ws_rec, chat)
    return out
