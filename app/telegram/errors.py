"""Helpers to classify Bot API errors in a single place."""
from __future__ import annotations

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramServerError,
    TelegramUnauthorizedError,
)


def _msg(exc: BaseException) -> str:
    return str(getattr(exc, "message", "") or exc).lower()


def is_not_modified(exc: BaseException) -> bool:
    return isinstance(exc, TelegramBadRequest) and "message is not modified" in _msg(exc)


def is_message_gone(exc: BaseException) -> bool:
    """The target message no longer exists (deleted by someone else)."""
    m = _msg(exc)
    return isinstance(exc, (TelegramBadRequest, TelegramNotFound)) and (
        "message to delete not found" in m
        or "message to edit not found" in m
        or "message to pin not found" in m
        or "message to forward not found" in m
        or "message to copy not found" in m
        or "message_id_invalid" in m
        or "message not found" in m
    )


def is_cant_delete(exc: BaseException) -> bool:
    return isinstance(exc, TelegramBadRequest) and "message can't be deleted" in _msg(exc)


def is_chat_gone(exc: BaseException) -> bool:
    """The bot can no longer reach the chat at all (kicked, chat deleted, user blocked the bot)."""
    m = _msg(exc)
    if isinstance(exc, TelegramForbiddenError):
        return True
    return isinstance(exc, (TelegramBadRequest, TelegramNotFound)) and (
        "chat not found" in m or "peer_id_invalid" in m or "channel_private" in m or "user is deactivated" in m
    )


def is_user_blocked(exc: BaseException) -> bool:
    m = _msg(exc)
    return isinstance(exc, TelegramForbiddenError) and (
        "blocked by the user" in m or "user is deactivated" in m or "bot can't initiate" in m or "chat not found" in m
    ) or (isinstance(exc, TelegramBadRequest) and "chat not found" in m)


def is_rights_error(exc: BaseException) -> bool:
    """The bot is in the chat but lacks a permission."""
    m = _msg(exc)
    return isinstance(exc, (TelegramBadRequest, TelegramForbiddenError)) and (
        "not enough rights" in m
        or "need administrator rights" in m
        or "chat_write_forbidden" in m
        or "chat_admin_required" in m
        or "have no rights" in m
        or "not an administrator" in m
        or "bot is not a member" in m
    )


# Telegram refused the message for its size: too many buttons, a keyboard too heavy (long names and links add up
# well before the 100 buttons) or a text too long. The same post with fewer chats goes through.
_TOO_BIG_MARKERS = (
    "reply markup is too long", "reply_markup_too_long", "too much buttons", "too many buttons", "buttons_too_much",
    "message is too long", "message_too_long", "caption is too long", "caption_too_long", "entities_too_long",
)


def is_too_big(exc: BaseException) -> bool:
    m = _msg(exc)
    return isinstance(exc, TelegramBadRequest) and any(marker in m for marker in _TOO_BIG_MARKERS)


def is_parse_error(exc: BaseException) -> bool:
    return isinstance(exc, TelegramBadRequest) and "can't parse entities" in _msg(exc)


def is_outcome_unknown(exc: BaseException) -> bool:
    """No answer (timeout, connection lost) or a Telegram server error (5xx): the request may have been applied
    anyway, e.g. the message may be out. A 413 (request too large) was refused before that."""
    return isinstance(exc, (TelegramNetworkError, TelegramServerError)) and not isinstance(exc, TelegramEntityTooLarge)


def is_button_error(exc: BaseException) -> bool:
    """Telegram refused a button of the keyboard: ``BUTTON_USER_PRIVACY_RESTRICTED`` (a tg://user link),
    ``BUTTON_URL_INVALID``, ``BUTTON_TYPE_INVALID``... or the Bot API's "inline keyboard button URL '…' is invalid"."""
    m = _msg(exc)
    return isinstance(exc, TelegramBadRequest) and ("button_" in m or "inline keyboard button" in m)


def is_topic_error(exc: BaseException) -> bool:
    """A forum supergroup refused the message in its General topic (closed or deleted): only an administrator
    that can manage topics may post there."""
    m = _msg(exc)
    return isinstance(exc, TelegramBadRequest) and (
        "topic_closed" in m or "topic_deleted" in m or "message thread not found" in m
    )


def migrated_to(exc: BaseException) -> int | None:
    if isinstance(exc, TelegramMigrateToChat):
        return exc.migrate_to_chat_id
    return None


def is_unauthorized(exc: BaseException) -> bool:
    return isinstance(exc, TelegramUnauthorizedError)


def short(exc: BaseException, limit: int = 240) -> str:
    return f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"[:limit]
