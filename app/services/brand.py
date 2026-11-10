"""🖼 Platform images, chosen by a super admin and used by every bot of the platform, and the clones' avatar.

* ``bot`` (:data:`BOT`): the photo on top of the home message (main bots for everyone, clones for their admins). It
  changes no profile photo.
* ``tz`` (:data:`TZ`): the photo on top of the 🗺 timezone picker, in every bot.

Each image is stored in KV ``platform:photo:<name>`` as ``{"<bot id>": "<file id>"}``: Telegram file ids belong to one
bot, so a bot without one gets the file downloaded through a bot that has it (:func:`photo_for`) and, once it has sent
it, remembers its own id (:func:`remember`).

The profile photo of every clone is the eMesh logo bundled with the app (:data:`AVATAR_FILE`, :func:`avatar`): a clone
gets it when it starts running and every running clone at startup (:func:`give_to_clone`,
:func:`give_to_running_clones`). What a clone got is remembered in KV ``photo:bot:<bot id>`` (``uid``: the
``file_unique_id`` of its photo, ``src``: what it was): a clone without a photo, or still showing one we gave (an older
logo, or the platform image clones got before), gets the avatar; one that already shows it gets nothing again; a clone
whose owner put another photo keeps it.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
from collections import Counter
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, InputProfilePhotoStatic

from app.db.session import session_scope
from app.services import kv
from app.telegram.context import set_low_priority
from app.telegram.errors import short

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.session import SessionMaker
    from app.telegram.manager import BotManager

log = logging.getLogger(__name__)

BOT = "bot"  # photo on top of the home
TZ = "tz"  # photo of the 🗺 timezone picker
NAMES = (BOT, TZ)
FILE_NAME = "photo.jpg"
DOWNLOAD_LIMIT = 20 * 1024 * 1024  # getFile: Telegram lets bots download files up to 20 MB
AVATAR_FILE = Path(__file__).resolve().parent.parent / "assets" / "clone_avatar.jpg"  # profile photo of the clones

_tasks: set[asyncio.Task[Any]] = set()  # background work started here (kept so it isn't garbage collected)


def _key(name: str) -> str:
    return f"platform:photo:{name}"


def _given_key(bot_id: int) -> str:
    return f"photo:bot:{bot_id}"


def spawn(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    """Runs ``coro`` in the background (a reference is kept until it ends)."""
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


# ---------------------------------------------------------------------------------------------------
# The stored images
# ---------------------------------------------------------------------------------------------------
async def photo_ids(session: AsyncSession, name: str) -> dict[str, str]:
    """``{"<bot id>": "<file id>"}`` of the image ``name`` (empty: there is none)."""
    stored = await kv.get(session, _key(name), {})
    if not isinstance(stored, dict):
        return {}
    return {str(bot_id): str(file_id) for bot_id, file_id in stored.items() if file_id}


async def has_photo(session: AsyncSession, name: str) -> bool:
    return bool(await photo_ids(session, name))


async def set_photo(session: AsyncSession, name: str, bot_id: int, file_id: str) -> None:
    """A new image, sent to ``bot_id``: the file ids of the previous one are forgotten."""
    await kv.put(session, _key(name), {str(bot_id): file_id})


async def clear_photo(session: AsyncSession, name: str) -> None:
    await kv.delete(session, _key(name))


async def remember(session: AsyncSession, name: str, bot_id: int, file_id: str, *, source: str | None) -> None:
    """Stores the file id ``bot_id`` got for the image after uploading it. ``source``: the file id it was downloaded
    from (:func:`source_of`); nothing is stored when the image changed meanwhile."""
    ids = await photo_ids(session, name)
    if not ids or (source is not None and source not in ids.values()) or ids.get(str(bot_id)) == file_id:
        return
    await kv.put(session, _key(name), {**ids, str(bot_id): file_id})  # a new dict: JSON value


def source_of(photo: object) -> str | None:
    """The file id (of another bot) a photo returned by :func:`photo_for` was downloaded from."""
    return getattr(photo, "source_file_id", None)


# ---------------------------------------------------------------------------------------------------
# Getting the file
# ---------------------------------------------------------------------------------------------------
async def fetch_one(bot: Bot, file_id: str) -> bytes | None:
    """The bytes of a file of ``bot`` (None when it can't be downloaded)."""
    try:
        file = await bot.get_file(file_id)
        if not file.file_path or (file.file_size and file.file_size > DOWNLOAD_LIMIT):
            return None
        data = await bot.download_file(file.file_path)
    except Exception as exc:  # noqa: BLE001 - a missing image never breaks a panel
        log.warning("File %s can't be downloaded through bot %s: %s", file_id, bot.id, short(exc))
        return None
    raw = data.getvalue() if data is not None and hasattr(data, "getvalue") else None
    return raw or None


async def fetch(ids: dict[str, str], manager: BotManager | None) -> tuple[bytes, str] | None:
    """The bytes of an image (and the file id they come from), through any running bot that has a file id of it."""
    for bot_id, file_id in ids.items():
        bot = manager.get(int(bot_id)) if manager is not None and bot_id.isdigit() else None
        if bot is None:
            continue
        raw = await fetch_one(bot, file_id)
        if raw:
            return raw, file_id
    return None


async def photo_for(session: AsyncSession, bot: Bot, name: str,
                    manager: BotManager | None) -> str | BufferedInputFile | None:
    """What ``bot`` sends as the image ``name``: its own file id, or the file downloaded through another bot (after
    sending it, call :func:`remember` with ``source=source_of(photo)``). None when there is no image or it can't be
    obtained: the panels work without it."""
    ids = await photo_ids(session, name)
    own = ids.get(str(bot.id))
    if own or not ids:
        return own
    got = await fetch(ids, manager)
    if got is None:
        return None
    raw, source = got
    upload = BufferedInputFile(raw, filename=FILE_NAME)
    upload.source_file_id = source  # type: ignore[attr-defined] - see remember()
    return upload


# ---------------------------------------------------------------------------------------------------
# Profile photos
# ---------------------------------------------------------------------------------------------------
async def current_photo(bot: Bot) -> str | None:
    """``file_unique_id`` of the profile photo of ``bot`` (None: it has none)."""
    photos = await bot.get_user_profile_photos(bot.id, limit=1)
    if not photos.total_count or not photos.photos or not photos.photos[0]:
        return None
    return photos.photos[0][-1].file_unique_id


async def set_profile_photo(bot: Bot, raw: bytes) -> str | None:
    """Uploads ``raw`` (a JPEG photo) as the profile photo of ``bot`` and returns the ``file_unique_id`` it got (None
    when it can't be read back). Raises ``TelegramAPIError`` when Telegram refuses it."""
    await bot.set_my_profile_photo(photo=InputProfilePhotoStatic(photo=BufferedInputFile(raw, filename=FILE_NAME)))
    try:
        return await current_photo(bot)
    except TelegramAPIError as exc:
        log.info("The new profile photo of bot %s can't be read back: %s", bot.id, short(exc))
        return None


@functools.cache
def avatar() -> tuple[bytes, str]:
    """The clones' profile photo (:data:`AVATAR_FILE`, a square JPEG) and its marker ``asset:<sha1>`` (a new file is
    given again). Raises ``OSError`` when the file can't be read."""
    raw = AVATAR_FILE.read_bytes()
    return raw, f"asset:{hashlib.sha1(raw, usedforsecurity=False).hexdigest()}"


async def give_to_clone(manager: BotManager, sm: SessionMaker, bot_id: int) -> str:
    """Gives the clones' avatar (:func:`avatar`) to the clone ``bot_id`` unless its owner put a photo of their own (a
    photo we gave earlier, like an older platform image, is replaced). Returns ``set``, ``same`` (it already shows it:
    nothing is uploaded again), ``own`` (it keeps its photo), ``none`` (not running; a main bot) or ``failed``.
    Background work (low priority): run it with :func:`spawn`."""
    set_low_priority()
    bot = manager.get(bot_id)
    if bot is None or bot_id in manager.main_bot_ids:
        return "none"
    try:
        raw, src = avatar()
    except OSError as exc:
        log.error("The clones' avatar %s can't be read: %s", AVATAR_FILE, exc)
        return "failed"
    async with session_scope(sm) as s:
        given = await kv.get(s, _given_key(bot_id))
    given_uid, given_src = (given.get("uid"), given.get("src")) if isinstance(given, dict) else (None, None)
    try:
        current = await current_photo(bot)
        # Its owner's photo: one we never gave. A photo we gave but couldn't read back right after the upload
        # (``uid`` None) counts as ours.
        if current is not None and (given_src is None or (given_uid is not None and current != given_uid)):
            return "own"
        if current is not None and given_src == src:
            return "same"
        uid = await set_profile_photo(bot, raw)
    except TelegramAPIError as exc:
        log.warning("The avatar could not be given to bot %s: %s", bot_id, short(exc))
        return "failed"
    async with session_scope(sm) as s:
        await kv.put(s, _given_key(bot_id), {"uid": uid, "src": src})
    log.info("Bot %s got the clones' avatar", bot_id)
    return "set"


async def give_to_running_clones(manager: BotManager, sm: SessionMaker) -> Counter[str]:
    """Startup: the avatar on every running clone (:func:`give_to_clone`: one that already shows it or has a photo of
    its own is left as it is). Returns how many got each outcome. Background work (low priority): run it with
    :func:`spawn`."""
    set_low_priority()
    outcomes: Counter[str] = Counter()
    for bot_id in sorted(manager.bots):
        if bot_id in manager.main_bot_ids or not manager.is_running(bot_id):
            continue
        try:
            outcomes[await give_to_clone(manager, sm, bot_id)] += 1
        except Exception:  # one clone never stops the others
            log.exception("The avatar could not be given to bot %s", bot_id)
            outcomes["failed"] += 1
    if outcomes:
        log.info("Clones' avatar at startup: %s", ", ".join(f"{k} {n}" for k, n in sorted(outcomes.items())))
    return outcomes
