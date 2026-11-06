"""📝 Content of posts: reading it from a user's message, the buttons (rows, colors, copy buttons) and sending it.

Buttons are stored as rows: ``[[{"text": "Web", "url": "https://…", "style": "success"}, {...}], [...]]``. A button
has either ``url`` or ``copy`` (a "copy to clipboard" button, Bot API ``copy_text``) and an optional ``style``:
``primary`` (🔵 blue), ``success`` (🟢 green) or ``danger`` (🔴 red) (Bot API 9.4 button colors).

Text syntax of the buttons (one row per line, several buttons in a row separated by ``&&`` or ``|``)::

    Visita la web - https://example.com 🟢
    Canal - @micanal && Grupo - t.me/migrupo
    Código - copiar: PROMO10 🔵

Telegram file ids are per bot: ``Post.media`` keeps ``{"<bot id>": "<file id>"}``. A bot without its own id
downloads the file through a bot that has one and uploads it (``media_for``); the new id is then remembered
(``remember_media``). Telegram lets bots download files up to 20 MB.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    LinkPreviewOptions,
    Message,
)

from app.db.models import Post
from app.db.session import SessionMaker, session_scope
from app.i18n import t
from app.telegram.errors import is_parse_error, short
from app.ui.common import visible_len

if TYPE_CHECKING:
    from app.telegram.manager import BotManager

log = logging.getLogger(__name__)

KINDS = ("text", "photo", "video", "animation", "document", "audio", "voice")
MEDIA_KINDS = KINDS[1:]
VISUAL_KINDS = ("photo", "video", "animation")  # caption above the media and spoiler apply to these
CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096
DOWNLOAD_LIMIT = 20 * 1024 * 1024  # getFile: Telegram lets bots download files up to 20 MB

MAX_BUTTONS = 30
MAX_PER_ROW = 8
MAX_BUTTON_TEXT = 64
MAX_COPY_TEXT = 256
STYLES = ("primary", "success", "danger")
COLORS = ("default", *STYLES)
COLOR_EMOJI = {"default": "⬜", "primary": "🔵", "success": "🟢", "danger": "🔴"}
_EMOJI_COLOR = {"🔵": "primary", "🟦": "primary", "🟢": "success", "🟩": "success", "🔴": "danger", "🟥": "danger",
                "⬜": "default", "⚪": "default"}
_WORD_COLOR = {"azul": "primary", "blue": "primary", "verde": "success", "green": "success", "rojo": "danger",
               "red": "danger", "normal": "default", "default": "default", "gris": "default", "grey": "default",
               "gray": "default"}
_DEFAULT_FILE_NAMES = {"photo": "photo.jpg", "video": "video.mp4", "animation": "animation.mp4",
                       "document": "file", "audio": "audio.mp3", "voice": "voice.ogg"}

_URL_START = r"(?:https?://|tg://|(?:www\.)?(?:t|telegram)\.me/|@)"
_BUTTON_RE = re.compile(rf"^(?P<text>.*?\S)\s*[-–—]\s*(?P<target>(?:{_URL_START}|(?:copiar|copy)\s*:).*)$",
                        re.IGNORECASE)
_COPY_RE = re.compile(r"^(?:copiar|copy)\s*:\s*(?P<value>.+)$", re.IGNORECASE | re.DOTALL)
_USERNAME_RE = re.compile(r"^@([A-Za-z][A-Za-z0-9_]{3,31})$")
_COLOR_TAIL_RE = re.compile(r"\s+(?:(?P<emoji>🔵|🟦|🟢|🟩|🔴|🟥|⬜|⚪)|#(?P<word>[a-záéíóú]+))\s*$", re.IGNORECASE)
_ROW_SPLIT_RE = re.compile(r"\s*(?:&&|\s\|\s)\s*")
_TG_EMOJI_RE = re.compile(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


class ButtonsError(ValueError):
    """Bad buttons text. ``key`` is an i18n key (``content.err.*``), ``line`` the 1-based line number."""

    def __init__(self, key: str, line: int = 0) -> None:
        super().__init__(key)
        self.key = key
        self.line = line


class MediaError(Exception):
    """The media of a post can't be used by a bot (``too_big`` or ``unavailable``)."""


# --------------------------------------------------------------------------- content of a message
@dataclass
class Content:
    kind: str
    text: str | None  # HTML
    file_id: str | None = None
    file_name: str | None = None


def from_message(message: Message) -> Content | None:
    """The content of a message the user sent or forwarded (None when its type isn't supported)."""
    text = message.html_text if (message.text or message.caption) else None
    if message.photo:
        return Content("photo", text, message.photo[-1].file_id)
    if message.video:
        return Content("video", text, message.video.file_id, message.video.file_name)
    if message.animation:  # before document: a GIF also carries a document
        return Content("animation", text, message.animation.file_id, message.animation.file_name)
    if message.document:
        return Content("document", text, message.document.file_id, message.document.file_name)
    if message.audio:
        return Content("audio", text, message.audio.file_id, message.audio.file_name)
    if message.voice:
        return Content("voice", text, message.voice.file_id)
    if message.text:
        return Content("text", text)
    return None


def content_error(content: Content) -> str | None:
    """i18n key of what is wrong with the content (too long), or None."""
    length = visible_len(content.text or "")
    if content.kind == "text":
        if not length:
            return "content.err.empty"
        return "content.err.text_long" if length > TEXT_LIMIT else None
    return "content.err.caption_long" if length > CAPTION_LIMIT else None


def apply(post: Post, content: Content, bot_id: int) -> None:
    """Stores the content in the post (the media's file id belongs to ``bot_id``, the bot that received it)."""
    post.kind = content.kind
    post.text = content.text
    post.media = {str(bot_id): content.file_id} if content.file_id else {}
    post.media_name = (content.file_name or "")[:128] or None


def set_text(post: Post, text_html: str | None) -> None:
    """Changes only the text (or caption) of a post."""
    post.text = text_html


def plain(html_text: str | None) -> str:
    return html.unescape(_TAG_RE.sub("", html_text or ""))


def kind_label(kind: str, lang: str) -> str:
    """``📝 Texto``, ``🖼 Foto``, ``🎬 Vídeo``…"""
    return t(f"content.kind.{kind if kind in KINDS else 'text'}", lang)


def default_name(post: Post, lang: str) -> str:
    """A name for a new post: its first words, or the kind of media."""
    first = next((line.strip() for line in plain(post.text).splitlines() if line.strip()), "")
    if first:
        return first if len(first) <= 40 else first[:39].rstrip() + "…"
    return kind_label(post.kind, lang)


# --------------------------------------------------------------------------- buttons
def normalize_url(raw: str) -> str | None:
    url = raw.strip()
    m = _USERNAME_RE.match(url)
    if m:
        return f"https://t.me/{m.group(1)}"
    low = url.lower()
    if low.startswith(("t.me/", "telegram.me/", "www.t.me/", "www.telegram.me/")):
        url = "https://" + url
        low = url.lower()
    if low.startswith("tg://"):
        return url if len(url) > len("tg://") and " " not in url else None
    if low.startswith(("http://", "https://")):
        if any(c.isspace() for c in url):
            return None
        try:
            host = urlsplit(url).hostname or ""
        except ValueError:
            return None
        return url if "." in host.strip(".") else None
    return None


def _parse_button(raw: str, line: int) -> dict[str, str]:
    part = raw.strip()
    style = None
    m = _COLOR_TAIL_RE.search(part)
    if m:
        color = _EMOJI_COLOR.get(m.group("emoji") or "") or _WORD_COLOR.get((m.group("word") or "").lower())
        if color is not None:
            style = color
            part = part[: m.start()].rstrip()
    if len(part) > 1 and part[0] == "[" and part[-1] == "]":
        part = part[1:-1].strip()
    m = _BUTTON_RE.match(part)
    if not m:
        raise ButtonsError("content.err.format", line)
    text = m.group("text").strip()
    if not text or len(text) > MAX_BUTTON_TEXT:
        raise ButtonsError("content.err.button_text", line)
    target = m.group("target").strip()
    button: dict[str, str] = {"text": text}
    copy = _COPY_RE.match(target)
    if copy:
        value = copy.group("value").strip()
        if not value or len(value) > MAX_COPY_TEXT:
            raise ButtonsError("content.err.copy", line)
        button["copy"] = value
    else:
        url = normalize_url(target)
        if url is None:
            raise ButtonsError("content.err.url", line)
        button["url"] = url
    if style and style != "default":
        button["style"] = style
    return button


def parse_buttons(text: str) -> list[list[dict[str, str]]]:
    """Rows of buttons from their text syntax (see the module docstring). Raises :class:`ButtonsError`."""
    rows: list[list[dict[str, str]]] = []
    count = 0
    for lineno, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        row = [_parse_button(part, lineno) for part in _ROW_SPLIT_RE.split(line) if part.strip()]
        if not row:
            continue
        if len(row) > MAX_PER_ROW:
            raise ButtonsError("content.err.row", lineno)
        count += len(row)
        if count > MAX_BUTTONS:
            raise ButtonsError("content.err.too_many", lineno)
        rows.append(row)
    if not rows:
        raise ButtonsError("content.err.empty_buttons")
    return rows


def button_line(button: dict[str, str]) -> str:
    """One button in the text syntax."""
    target = f"copiar: {button['copy']}" if button.get("copy") else button.get("url", "")
    color = COLOR_EMOJI.get(button.get("style", ""), "")
    return f"{button.get('text', '')} - {target}" + (f" {color}" if color else "")


def format_buttons(rows: list[list[dict[str, str]]] | None) -> str:
    """Inverse of :func:`parse_buttons` (one row per line, `` && `` between buttons)."""
    return "\n".join(" && ".join(button_line(b) for b in row if isinstance(b, dict))
                     for row in rows or [] if row)


def clean_rows(rows: Any) -> list[list[dict[str, str]]]:
    """Valid rows only (stored JSON may be edited by hand or come from an older version)."""
    out: list[list[dict[str, str]]] = []
    for row in rows if isinstance(rows, list) else []:
        clean = [dict(b) for b in row if isinstance(b, dict) and b.get("text") and (b.get("url") or b.get("copy"))] \
            if isinstance(row, list) else []
        if clean:
            out.append(clean)
    return out


def count_buttons(rows: Any) -> int:
    return sum(len(r) for r in clean_rows(rows))


def make_button(b: dict[str, str]) -> InlineKeyboardButton:
    kwargs: dict[str, Any] = {"text": b["text"]}
    if b.get("style") in STYLES:
        kwargs["style"] = b["style"]
    if b.get("copy"):
        kwargs["copy_text"] = CopyTextButton(text=b["copy"])
    else:
        kwargs["url"] = b["url"]
    return InlineKeyboardButton(**kwargs)


def build_markup(rows: Any) -> InlineKeyboardMarkup | None:
    clean = clean_rows(rows)
    if not clean:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[make_button(b) for b in row] for row in clean])


# --------------------------------------------------------------------------- media across bots
def file_id_of(message: Message, kind: str) -> str | None:
    """The file id of the media a bot just sent (to remember it for that bot)."""
    if kind == "photo" and message.photo:
        return message.photo[-1].file_id
    obj = getattr(message, kind, None)
    return getattr(obj, "file_id", None)


async def media_for(bot: Bot, post: Post, manager: BotManager | None) -> str | BufferedInputFile | None:
    """What ``bot`` sends as the media of ``post``: its own file id, or the file downloaded through another bot
    that has one (upload it, then :func:`remember_media`). None for text posts. Raises :class:`MediaError`."""
    if post.kind not in MEDIA_KINDS:
        return None
    media = dict(post.media or {})
    own = media.get(str(bot.id))
    if own:
        return own
    for bot_id, file_id in media.items():
        source = manager.get(int(bot_id)) if manager is not None and bot_id.isdigit() else None
        if source is None:
            continue
        try:
            file = await source.get_file(file_id)
            if file.file_size and file.file_size > DOWNLOAD_LIMIT:
                raise MediaError("too_big")
            if not file.file_path:
                continue
            data = await source.download_file(file.file_path)
        except MediaError:
            raise
        except TelegramBadRequest as exc:
            if "too big" in str(exc).lower():
                raise MediaError("too_big") from exc
            log.warning("Media of post %s can't be downloaded through bot %s: %s", post.id, bot_id, short(exc))
            continue
        except Exception as exc:  # noqa: BLE001 - try the next bot that has it
            log.warning("Media of post %s can't be downloaded through bot %s: %s", post.id, bot_id, short(exc))
            continue
        if data is None:
            continue
        raw = data.getvalue() if hasattr(data, "getvalue") else bytes(data)  # type: ignore[arg-type]
        if not raw:
            continue
        return BufferedInputFile(raw, filename=post.media_name or _DEFAULT_FILE_NAMES.get(post.kind, "file"))
    raise MediaError("unavailable")


async def remember_media(sm: SessionMaker, post_id: int, bot_id: int, file_id: str) -> None:
    """Stores the file id ``bot_id`` got for the media of a post (its own short transaction)."""
    async with session_scope(sm) as s:
        post = await s.get(Post, post_id)
        if post is not None and (post.media or {}).get(str(bot_id)) != file_id:
            post.media = {**(post.media or {}), str(bot_id): file_id}


# --------------------------------------------------------------------------- sending
def _strip_custom_emoji(html_text: str | None) -> str | None:
    return _TG_EMOJI_RE.sub(r"\1", html_text) if html_text else html_text


_KEEP = object()


async def deliver(
    bot: Bot,
    chat_id: int,
    post: Post,
    *,
    media: str | InputFile | None = None,
    reply_markup: InlineKeyboardMarkup | None | object = _KEEP,
    silent: bool | None = None,
    protect: bool | None = None,
) -> Message:
    """Sends the post to ``chat_id`` with its options. ``media`` comes from :func:`media_for` (required for media
    posts). Custom emoji the bot may not use are sent as normal emoji. Raises the Telegram errors."""
    markup = build_markup(post.buttons) if reply_markup is _KEEP else reply_markup
    text = post.text
    for attempt in range(2):
        try:
            return await _send(bot, chat_id, post, text, media, markup,  # type: ignore[arg-type]
                               post.silent if silent is None else silent, post.protect if protect is None else protect)
        except TelegramBadRequest as exc:
            stripped = _strip_custom_emoji(text)
            if attempt == 0 and stripped != text and (is_parse_error(exc) or "emoji" in str(exc).lower()):
                text = stripped
                continue
            raise
    raise RuntimeError("unreachable")


async def _send(bot: Bot, chat_id: int, post: Post, text: str | None, media: str | InputFile | None,
                markup: InlineKeyboardMarkup | None, silent: bool, protect: bool) -> Message:
    common: dict[str, Any] = {"reply_markup": markup, "disable_notification": silent or None,
                              "protect_content": protect or None}
    kind = post.kind
    if kind not in MEDIA_KINDS:
        return await bot.send_message(chat_id, text or "…", link_preview_options=LinkPreviewOptions(
            is_disabled=not post.link_preview), **common)
    if media is None:
        raise MediaError("unavailable")
    if kind in VISUAL_KINDS:
        visual = {"caption": text, "show_caption_above_media": post.caption_above or None,
                  "has_spoiler": post.spoiler or None, **common}
        if kind == "photo":
            return await bot.send_photo(chat_id, media, **visual)
        if kind == "video":
            return await bot.send_video(chat_id, media, **visual)
        return await bot.send_animation(chat_id, media, **visual)
    if kind == "document":
        return await bot.send_document(chat_id, media, caption=text, **common)
    if kind == "audio":
        return await bot.send_audio(chat_id, media, caption=text, **common)
    return await bot.send_voice(chat_id, media, caption=text, **common)


async def send_post(bot: Bot, chat_id: int, post: Post, manager: BotManager | None, sm: SessionMaker | None = None,
                    **kwargs: Any) -> Message:
    """One-off send (previews, tests): resolves the media for ``bot``, sends, and remembers a newly uploaded
    file id when ``sm`` is given. Raises :class:`MediaError` and the Telegram errors."""
    media = await media_for(bot, post, manager)
    msg = await deliver(bot, chat_id, post, media=media, **kwargs)
    if isinstance(media, InputFile) and sm is not None and post.id:
        file_id = file_id_of(msg, post.kind)
        if file_id:
            await remember_media(sm, post.id, bot.id, file_id)
    return msg


async def edit_delivery(bot: Bot, chat_id: int, message_id: int, post: Post) -> None:
    """Applies the current text/caption and buttons of a post to a message already sent (the media stays).
    Raises the Telegram errors ("message is not modified" included)."""
    markup = build_markup(post.buttons)
    if post.kind not in MEDIA_KINDS:
        await bot.edit_message_text(post.text or "…", chat_id=chat_id, message_id=message_id, reply_markup=markup,
                                    link_preview_options=LinkPreviewOptions(is_disabled=not post.link_preview))
    else:
        await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=post.text, reply_markup=markup,
                                       show_caption_above_media=(post.caption_above or None)
                                       if post.kind in VISUAL_KINDS else None)


def is_media_error(exc: BaseException) -> bool:
    return isinstance(exc, MediaError)


__all__ = [
    "COLORS", "COLOR_EMOJI", "KINDS", "MEDIA_KINDS", "VISUAL_KINDS", "ButtonsError", "Content", "MediaError",
    "TelegramAPIError", "apply", "build_markup", "button_line", "clean_rows", "content_error", "count_buttons",
    "default_name", "deliver", "edit_delivery", "file_id_of", "format_buttons", "from_message", "kind_label",
    "make_button", "media_for", "normalize_url", "parse_buttons", "plain", "remember_media", "send_post", "set_text",
]
