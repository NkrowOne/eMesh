"""UI building blocks: buttons, keyboards, pagination and the ``show`` panel renderer."""
from __future__ import annotations

import html
import logging
import re
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from typing import TYPE_CHECKING, TypeVar

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    DisabledButton,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    LinkPreviewOptions,
    Message,
)

from app.i18n import t
from app.telegram.errors import is_not_modified
from app.ui.callbacks import InputCancelCB, MenuCB, NoopCB

if TYPE_CHECKING:
    from app.bot.context import Ctx

log = logging.getLogger(__name__)

T = TypeVar("T")
STYLES = ("primary", "success", "danger")
CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096

# "🛠 Gestionando @clone": set by the context middleware while a super admin manages another bot's network, and
# shown on top of every panel so it is always clear which network is being changed.
ws_banner: ContextVar[str] = ContextVar("ws_banner", default="")


def strip_button_icons(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    """Removes icon_custom_emoji_id from all buttons if Telegram rejects custom emoji icons."""
    if markup is None:
        return None
    new_rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        new_row: list[InlineKeyboardButton] = []
        for button in row:
            if getattr(button, "icon_custom_emoji_id", None):
                data = button.model_dump(exclude_unset=True)
                data.pop("icon_custom_emoji_id", None)
                new_row.append(InlineKeyboardButton(**data))
            else:
                new_row.append(button)
        new_rows.append(new_row)
    return InlineKeyboardMarkup(inline_keyboard=new_rows)


def btn(
    text: str,
    cb: CallbackData | str | None = None,
    *,
    url: str | None = None,
    style: str | None = None,
    disabled: bool = False,
    icon_custom_emoji_id: str | None = None,
) -> InlineKeyboardButton:
    """Inline button. ``style`` is one of primary/success/danger (Bot API 9.4 colors)."""
    kwargs: dict[str, object] = {"text": text}
    if style in STYLES:
        kwargs["style"] = style
    if disabled:
        kwargs["disabled"] = DisabledButton()
    elif url:
        kwargs["url"] = url
    else:
        kwargs["callback_data"] = cb.pack() if isinstance(cb, CallbackData) else (cb or NoopCB().pack())
    if icon_custom_emoji_id:
        kwargs["icon_custom_emoji_id"] = icon_custom_emoji_id
    return InlineKeyboardButton(**kwargs)  # type: ignore[arg-type]


def kb(*rows: Sequence[InlineKeyboardButton | None] | None) -> InlineKeyboardMarkup:
    clean = [[b for b in row if b is not None] for row in rows if row]
    return InlineKeyboardMarkup(inline_keyboard=[r for r in clean if r])


def grid(buttons: Sequence[InlineKeyboardButton], cols: int) -> list[list[InlineKeyboardButton]]:
    cols = max(1, cols)
    return [list(buttons[i : i + cols]) for i in range(0, len(buttons), cols)]


def back_row(lang: str, screen: str = "home", arg: int = 0) -> list[InlineKeyboardButton]:
    return [btn(t("common.back", lang), MenuCB(screen=screen, arg=arg))]


def cancel_row(lang: str, screen: str = "home", arg: int = 0) -> list[InlineKeyboardButton]:
    """Cancel button for text inputs: clears the FSM state and reopens ``screen``."""
    return [btn(t("common.cancel", lang), InputCancelCB(screen=screen, arg=arg))]


def paginate(items: Sequence[T], page: int, per_page: int) -> tuple[list[T], int, int]:
    pages = max(1, (len(items) + per_page - 1) // per_page)
    page = min(max(0, page), pages - 1)
    start = page * per_page
    return list(items[start : start + per_page]), page, pages


def nav_row(
    page: int, pages: int, make_cb: Callable[[int], CallbackData], lang: str
) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(btn(t("common.prev", lang), make_cb(page - 1)))
    if page < pages - 1:
        row.append(btn(t("common.next", lang), make_cb(page + 1)))
    return row


def bare_label(label: str) -> str:
    """The label without its leading emoji (``"📌 Fijar"`` -> ``"Fijar"``)."""
    icon, _, rest = label.partition(" ")
    return rest if rest and not icon[:1].isalnum() else label


def toggle_label(label: str, value: bool | None) -> str:
    """``✅ Fijar`` / ``✖️ Fijar`` (``⚠️`` when ``value`` is None: mixed values).

    The mark goes first, in place of the label's own emoji: Telegram cuts long button texts at the end.
    """
    mark = "⚠️" if value is None else ("✅" if value else "✖️")
    return f"{mark} {bare_label(label)}"


def choice_label(label: str, selected: bool) -> str:
    """An option of a choice row: ``✅ Label`` when it is the current value, ``⚪ Label`` otherwise (the mark goes in
    place of the label's emoji, so the selected option is always obvious)."""
    return f"{'✅' if selected else '⚪'} {bare_label(label)}"


def visible_len(html_text: str) -> int:
    """Visible length as Telegram counts it (UTF-16 code units, tags removed)."""
    plain = html.unescape(re.sub(r"<[^>]+>", "", html_text or ""))
    return len(plain.encode("utf-16-le")) // 2


def _has_media(msg: Message) -> bool:
    return bool(msg.photo or msg.video or msg.animation or msg.document or msg.audio)


async def _send(
    bot_msg_target: Message | CallbackQuery,
    chat_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None,
    media_id: str | InputFile | None,
    media_type: str | None,
    preview: bool,
) -> Message:
    bot = bot_msg_target.bot
    assert bot is not None
    lp = LinkPreviewOptions(is_disabled=not preview)
    try:
        if media_id:
            caption = text if visible_len(text) <= CAPTION_LIMIT else None
            reply_markup = markup if caption is not None else None
            if media_type == "video":
                sent = await bot.send_video(chat_id, media_id, caption=caption, reply_markup=reply_markup)
            elif media_type == "animation":
                sent = await bot.send_animation(chat_id, media_id, caption=caption, reply_markup=reply_markup)
            else:
                sent = await bot.send_photo(chat_id, media_id, caption=caption, reply_markup=reply_markup)
            if caption is not None:
                return sent
        return await bot.send_message(chat_id, text, reply_markup=markup, link_preview_options=lp)
    except TelegramBadRequest as exc:
        if "icon_custom_emoji" in str(exc).lower() and markup is not None:
            clean = strip_button_icons(markup)
            return await _send(bot_msg_target, chat_id, text, clean, media_id, media_type, preview)
        raise


async def show(
    event: Message | CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    media_id: str | InputFile | None = None,
    media_type: str | None = None,
    preview: bool = False,
    new: bool = False,
) -> Message | None:
    """Renders a panel.

    * Callback: edits the message in place when possible (text -> text); otherwise deletes it and
      sends a new one (media changes, too old to edit...).
    * Message: always sends a new panel.
    """
    banner = ws_banner.get()
    if banner and not text.startswith(banner):
        text = f"{banner}\n\n{text}"
    try:
        if isinstance(event, CallbackQuery):
            msg = event.message
            chat_id = event.from_user.id if msg is None or isinstance(msg, InaccessibleMessage) else msg.chat.id
            if msg is not None and not isinstance(msg, InaccessibleMessage) and not new:
                if media_id is None and not _has_media(msg):
                    try:
                        edited = await msg.edit_text(
                            text, reply_markup=markup, link_preview_options=LinkPreviewOptions(is_disabled=not preview)
                        )
                        return edited if isinstance(edited, Message) else msg
                    except TelegramBadRequest as exc:
                        if is_not_modified(exc):
                            return msg
                        if "icon_custom_emoji" in str(exc).lower() and markup is not None:
                            try:
                                clean = strip_button_icons(markup)
                                edited = await msg.edit_text(
                                    text, reply_markup=clean, link_preview_options=LinkPreviewOptions(is_disabled=not preview)
                                )
                                return edited if isinstance(edited, Message) else msg
                            except TelegramBadRequest:
                                pass
                        log.debug("edit_text failed, sending new panel: %s", exc)
                try:
                    await msg.delete()
                except TelegramBadRequest:
                    pass
            return await _send(event, chat_id, text, markup, media_id, media_type, preview)
        return await _send(event, event.chat.id, text, markup, media_id, media_type, preview)
    except TelegramForbiddenError:
        return None


async def prompt(
    event: Message | CallbackQuery,
    ctx: Ctx,
    text: str,
    *,
    cancel_screen: str = "home",
    cancel_arg: int = 0,
    extra_rows: Sequence[Sequence[InlineKeyboardButton]] = (),
    back: CallbackData | None = None,
) -> Message | None:
    """Asks the user for a text/media input. Pair it with ``state.set_state(...)``.

    ``back`` adds "🔙 Regresar" (previous step of a multi-step flow) next to the Cancel button.
    """
    rows = [list(r) for r in extra_rows]
    last = cancel_row(ctx.lang, cancel_screen, cancel_arg)
    if back is not None:
        last.insert(0, btn(t("common.back", ctx.lang), back))
    rows.append(last)
    return await show(event, text, kb(*rows))


callback_answered: ContextVar[bool] = ContextVar("callback_answered", default=False)

POPUP_MAX = 200  # Telegram refuses a longer answerCallbackQuery text (and then nothing is shown)
TOAST_MAX = 100  # longer toasts vanish before they can be read: they are shown as an alert (with OK)


def popup_text(text: str) -> str:
    """Plain text that fits a popup: no HTML tags or entities, at most ``POPUP_MAX`` characters."""
    plain = html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()
    if _utf16_len(plain) <= POPUP_MAX:
        return plain
    while _utf16_len(plain) > POPUP_MAX - 1:
        plain = plain[:-1]
    return plain.rstrip() + "…"


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


async def toast(event: Message | CallbackQuery, text: str, *, alert: bool = False) -> None:
    """Short notification: toast/popup for callbacks, plain message otherwise.

    Always use this instead of ``callback.answer()``: the auto-answer middleware then knows the
    query was already answered.
    """
    if isinstance(event, CallbackQuery):
        if callback_answered.get():
            # Only one popup per button press: a second one would never be seen.
            log.warning("Popup dropped, the button press was already answered: %s", text[:80])
            return
        text = popup_text(text)
        try:
            await event.answer(text, show_alert=alert or _utf16_len(text) > TOAST_MAX)
        except TelegramBadRequest as exc:
            log.warning("Popup refused by Telegram (%s): %s", exc, text[:80])
        callback_answered.set(True)
    else:
        await event.answer(text)


async def alert(event: Message | CallbackQuery, text: str) -> None:
    await toast(event, text, alert=True)
