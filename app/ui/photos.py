"""Panels with one of the platform images (``services.brand``) on top: 🖼 the bot image on the home and in 👑 › 🖼 Imagen
del bot, the photo of the 🗺 timezone picker.

While the pressed panel already is that photo only its caption and buttons change (nothing is sent again); a bot
without its own file id of the image uploads it once and remembers it; a photo Telegram refuses is left out (the
panel works without it).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message

from app.services import brand
from app.telegram.errors import is_not_modified, short
from app.ui.common import release_prompt, show, ws_banner

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.bot.context import Ctx

log = logging.getLogger(__name__)


def _same_photo(msg: Message, photo: str | BufferedInputFile) -> bool:
    """The pressed panel shows this very image (an image this bot hasn't sent yet never is)."""
    return isinstance(photo, str) and bool(msg.photo) and msg.photo[-1].file_id == photo


async def _edit_caption(call: CallbackQuery, msg: Message, text: str, markup: InlineKeyboardMarkup | None) -> bool:
    """Only the caption and the buttons of the pressed photo change. False when it can't be edited."""
    banner = ws_banner.get()  # on top of every panel while managing a clone, as show() does
    if banner and not text.startswith(banner):
        text = f"{banner}\n\n{text}"
    try:
        await msg.edit_caption(caption=text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if not is_not_modified(exc):
            log.debug("edit_caption failed, sending the panel again: %s", exc)
            return False
    await release_prompt(call)  # as show() does: a prompt pressed here is the panel now
    return True


async def show_with_photo(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, name: str, text: str,
                          markup: InlineKeyboardMarkup | None) -> Message | None:
    """``show`` with the platform image ``name`` on top (just ``show`` while there is none)."""
    bot = event.bot
    photo = await brand.photo_for(session, bot, name, ctx.manager) if bot is not None else None
    if photo is None:
        return await show(event, text, markup)
    pressed = event.message if isinstance(event, CallbackQuery) and isinstance(event.message, Message) else None
    if isinstance(event, CallbackQuery) and pressed is not None and _same_photo(pressed, photo):
        if await _edit_caption(event, pressed, text, markup):
            return pressed
    try:
        sent = await show(event, text, markup, media_id=photo, media_type="photo")
    except TelegramBadRequest as exc:  # a file id Telegram no longer takes: the panel without the photo
        log.warning("The %s image was refused through bot %s: %s", name, ctx.bot_id, short(exc))
        return await show(event, text, markup, new=isinstance(event, CallbackQuery))
    if isinstance(photo, BufferedInputFile) and sent is not None and sent.photo and bot is not None:
        await brand.remember(session, name, bot.id, sent.photo[-1].file_id, source=brand.source_of(photo))
    return sent
