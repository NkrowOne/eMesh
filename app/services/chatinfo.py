"""Reads live information of a channel/group from Telegram (title, members, bot rights)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramMigrateToChat
from aiogram.types import ChatMember, ChatMemberAdministrator

from app.db.base import utcnow
from app.db.models import Chat, ChatType
from app.telegram.errors import is_chat_gone, short

log = logging.getLogger(__name__)

# Rights the bot needs (ChatMemberAdministrator attributes; i18n keys ``rights.<name>``): publish, edit (also pins
# in channels), delete (auto delete, "delete previous" and the "pinned" notices) and, in groups, pin. In groups an
# administrator can always send and edit its own messages, and slow mode doesn't apply to it.
REQUIRED_CHANNEL = ("can_post_messages", "can_edit_messages", "can_delete_messages")
REQUIRED_GROUP = ("can_delete_messages", "can_pin_messages")

# Deep links that open Telegram's "add bot as admin" dialog with these rights pre-selected.
CHANNEL_RIGHTS_PARAM = "post_messages+edit_messages+delete_messages"
GROUP_RIGHTS_PARAM = "delete_messages+pin_messages"


def add_to_channel_url(bot_username: str) -> str:
    return f"https://t.me/{bot_username}?startchannel&admin={CHANNEL_RIGHTS_PARAM}"


def add_to_group_url(bot_username: str) -> str:
    return f"https://t.me/{bot_username}?startgroup&admin={GROUP_RIGHTS_PARAM}"


def chat_type_of(tg_type: str) -> str:
    return ChatType.CHANNEL if tg_type == "channel" else ChatType.GROUP


def missing_rights(member: ChatMember | None, chat_type: str) -> list[str]:
    """Required rights the bot lacks. ``["admin"]`` when it is not an administrator at all."""
    if member is None or member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
        return ["admin"]
    if not isinstance(member, ChatMemberAdministrator):
        return []
    required = REQUIRED_CHANNEL if chat_type == ChatType.CHANNEL else REQUIRED_GROUP
    return [r for r in required if not getattr(member, r, False)]


def apply_rights(chat: Chat, member: ChatMember | None) -> list[str]:
    missing = missing_rights(member, chat.type)
    chat.rights_ok = not missing
    chat.missing_rights = ",".join(missing)
    return missing


@dataclass
class InspectResult:
    gone: bool = False  # the bot can't access the chat anymore
    migrated_from: int | None = None
    members_before: int = 0
    members_after: int = 0
    missing: list[str] = field(default_factory=list)
    error: str | None = None
    description: str | None = None  # the chat's bio (getChat), for the blocked words check
    fetched: bool = False  # getChat worked: title, @username and description are up to date
    rights_read: bool = False  # getChatMember worked: ``missing`` (and the chat's rights) are up to date

    @property
    def members_changed(self) -> bool:
        return self.members_before != self.members_after


def _surely_gone(exc: BaseException) -> bool:
    """A 403 (the bot was kicked / is not a member) is definitive; a 400 like "chat not found" needs another call
    to confirm it (it can be a hiccup of the Bot API server)."""
    return isinstance(exc, TelegramForbiddenError)


async def _confirm_gone(bot: Bot, chat: Chat, *, by_member: bool) -> bool:
    """Asks Telegram a second, different way whether the bot still reaches ``chat``. True only when that answer says
    it doesn't too (an error that also means "gone", or the bot is left / kicked)."""
    try:
        if by_member:
            member = await bot.get_chat_member(chat.chat_id, bot.id)
            return member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)
        await bot.get_chat(chat.chat_id)
        return False
    except TelegramAPIError as exc:
        return is_chat_gone(exc)
    except Exception:  # noqa: BLE001 - unknown: never expel on it
        return False


async def inspect_chat(bot: Bot, chat: Chat, *, with_rights: bool = True) -> InspectResult:
    """Refreshes ``chat`` in place (title, username, type, members, rights). Never raises.

    The caller commits the session.
    """
    res = InspectResult(members_before=chat.members or 0, members_after=chat.members or 0)
    for _ in range(2):
        try:
            full = await bot.get_chat(chat.chat_id)
            break
        except TelegramMigrateToChat as exc:
            res.migrated_from = chat.chat_id
            chat.chat_id = exc.migrate_to_chat_id
        except TelegramAPIError as exc:
            if is_chat_gone(exc) and (_surely_gone(exc) or await _confirm_gone(bot, chat, by_member=True)):
                res.gone = True
            res.error = short(exc)
            return res
        except Exception as exc:  # noqa: BLE001 - e.g. unexpected response shape
            log.warning("get_chat(%s) failed: %s", chat.chat_id, exc)
            res.error = short(exc)
            return res
    else:
        res.error = "migration loop"
        return res

    chat.title = (full.title or chat.title or "")[:256]
    chat.username = full.username
    chat.type = chat_type_of(full.type)
    res.description = full.description
    res.fetched = True
    try:
        chat.members = await bot.get_chat_member_count(chat.chat_id)
        chat.members_at = utcnow()
        res.members_after = chat.members
    except Exception as exc:  # noqa: BLE001
        res.error = short(exc)
    if with_rights:
        try:
            member = await bot.get_chat_member(chat.chat_id, bot.id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                res.gone = True  # the chat answers (it may be public) but the bot isn't in it
            res.missing = apply_rights(chat, member)
            res.rights_read = True
        except TelegramAPIError as exc:
            if is_chat_gone(exc) and (_surely_gone(exc) or await _confirm_gone(bot, chat, by_member=False)):
                res.gone = True
            res.error = short(exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("get_chat_member(%s) failed: %s", chat.chat_id, exc)
            res.error = short(exc)
    chat.checked_at = utcnow()
    return res


async def check_access(bot: Bot, chat: Chat) -> InspectResult:
    """Fast 1-call check (`getChatMember`) of whether the bot is still in ``chat`` and holds all required rights."""
    res = InspectResult(members_before=chat.members or 0, members_after=chat.members or 0)
    for _ in range(2):
        try:
            member = await bot.get_chat_member(chat.chat_id, bot.id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                res.gone = True
            res.missing = apply_rights(chat, member)
            res.rights_read = True
            break
        except TelegramMigrateToChat as exc:
            res.migrated_from = chat.chat_id
            chat.chat_id = exc.migrate_to_chat_id
        except TelegramAPIError as exc:
            if is_chat_gone(exc) and (_surely_gone(exc) or await _confirm_gone(bot, chat, by_member=False)):
                res.gone = True
            res.error = short(exc)
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("get_chat_member(%s) failed: %s", chat.chat_id, exc)
            res.error = short(exc)
            break
    chat.checked_at = utcnow()
    return res

