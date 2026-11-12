"""Safe direct messages to users and admins."""
from __future__ import annotations

import logging
from collections.abc import Callable

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, LinkPreviewOptions, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot as BotRecord
from app.db.models import BotUser
from app.services.users import admin_ids
from app.telegram.errors import is_user_blocked, short

log = logging.getLogger(__name__)


async def send_dm(
    bot: Bot,
    session: AsyncSession | None,
    user_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    preview: bool = False,
) -> Message | None:
    """Sends a private message. Marks the user as blocked when Telegram says so. Never raises."""
    try:
        return await bot.send_message(
            user_id, text, reply_markup=markup, link_preview_options=LinkPreviewOptions(is_disabled=not preview)
        )
    except TelegramBadRequest as exc:
        if "icon_custom_emoji" in str(exc).lower() and markup is not None:
            from app.ui.common import strip_button_icons
            clean = strip_button_icons(markup)
            try:
                return await bot.send_message(
                    user_id, text, reply_markup=clean, link_preview_options=LinkPreviewOptions(is_disabled=not preview)
                )
            except Exception as e:
                log.info("DM to %s failed on fallback: %s", user_id, short(e))
                return None
        if is_user_blocked(exc) and session is not None:
            bu = await session.get(BotUser, (bot.id, user_id))
            if bu is not None:
                bu.is_blocked = True
        log.info("DM to %s failed: %s", user_id, short(exc))
    except TelegramForbiddenError as exc:
        if is_user_blocked(exc) and session is not None:
            bu = await session.get(BotUser, (bot.id, user_id))
            if bu is not None:
                bu.is_blocked = True
        log.info("DM to %s failed: %s", user_id, short(exc))
    except Exception as exc:  # noqa: BLE001
        log.warning("DM to %s failed: %s", user_id, short(exc))
    return None


async def notify_admins(
    bot: Bot,
    session: AsyncSession,
    bot_rec: BotRecord,
    render: Callable[[str], tuple[str, InlineKeyboardMarkup | None]],
) -> list[tuple[int, int]]:
    """Sends ``render(lang)`` to the owner and every admin. Returns ``[(user_id, message_id)]``.

    Always: a request waits for their decision, so 🔔 Alertas de la red (what happens in the network) never silences
    it."""
    sent: list[tuple[int, int]] = []
    for uid in await admin_ids(session, bot_rec):
        bu = await session.get(BotUser, (bot_rec.id, uid))
        if bu is None:
            continue  # never started the bot: we can't write to them
        text, markup = render(bu.lang)
        msg = await send_dm(bot, session, uid, text, markup)
        if msg is not None:
            sent.append((uid, msg.message_id))
    return sent
