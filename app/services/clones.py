"""Clones (bots of other owners run by the platform): limits, connection, Managed Bots helpers.

Owner: clone/panel module (it may extend this file; keep the functions other modules use).
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import TYPE_CHECKING
from urllib.parse import quote

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import func, or_, select

from app.db.models import Bot as BotRecord
from app.db.models import BotStatus
from app.i18n import t
from app.services import limits
from app.services.notify import send_dm
from app.services.users import get_lang
from app.telegram.manager import BotTokenError
from app.ui.fmt import esc, user_link

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.config import Settings
    from app.telegram.manager import BotManager

log = logging.getLogger(__name__)

# ``bots.status_reason`` values of DISABLED bots set by this module.
REASON_OWNER = "owner"  # paused by its owner in "Mis bots"
REASON_ADMIN = "admin"  # disabled by a super admin (the owner can't re-enable it)
REASON_REMOVED = "removed"  # disconnected by its owner: hidden and not counted, data kept

USERNAME_SUFFIX = "_mesh_bot"
USERNAME_MAX = 32
CAN_MANAGE_TTL = 600.0
_can_manage: dict[int, tuple[float, bool]] = {}


def _not_removed() -> ColumnElement[bool]:
    return or_(
        BotRecord.status != BotStatus.DISABLED,
        BotRecord.status_reason.is_(None),
        BotRecord.status_reason != REASON_REMOVED,
    )


def is_removed(rec: BotRecord) -> bool:
    return rec.status == BotStatus.DISABLED and rec.status_reason == REASON_REMOVED


def is_admin_locked(rec: BotRecord) -> bool:
    """Disabled by a super admin: only a super admin can bring it back."""
    return rec.status == BotStatus.DISABLED and rec.status_reason == REASON_ADMIN


def status_key(rec: BotRecord) -> str:
    """``active`` / ``pending`` / ``paused`` / ``admin`` / ``removed`` / ``invalid`` (i18n ``cl.status.<key>``)."""
    if rec.status == BotStatus.ACTIVE:
        return "active"
    if rec.status == BotStatus.PENDING:
        return "pending"
    if rec.status == BotStatus.INVALID:
        return "invalid"
    if rec.status_reason == REASON_ADMIN:
        return "admin"
    if rec.status_reason == REASON_REMOVED:
        return "removed"
    return "paused"


async def user_bots(session: AsyncSession, owner_id: int) -> list[BotRecord]:
    """Clones of ``owner_id`` (not the disconnected ones), oldest first, freshly loaded."""
    q = (
        select(BotRecord)
        .where(BotRecord.owner_id == owner_id, BotRecord.is_main.is_(False), _not_removed())
        .order_by(BotRecord.created_at, BotRecord.id)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(q)).scalars())


async def main_username(session: AsyncSession, settings: Settings) -> str | None:
    """Username of the main bot of BOT_TOKEN (not of its copies): where clones and payments point to."""
    rec = await session.get(BotRecord, settings.main_bot_id)
    return rec.username if rec is not None and rec.username else None


async def count_user_bots(session: AsyncSession, owner_id: int) -> int:
    q = select(func.count()).select_from(BotRecord).where(
        BotRecord.owner_id == owner_id, BotRecord.is_main.is_(False), _not_removed()
    )
    return int((await session.execute(q)).scalar() or 0)


async def clone_limit(session: AsyncSession, settings: Settings, user_id: int) -> int | None:
    """Maximum clones of a user; None = unlimited (super admins, or the platform limit is 0)."""
    if user_id in settings.super_admin_ids:
        return None
    limit = (await limits.platform(session, settings)).max_clones
    return limit or None


def token_bot_id(token: str) -> int | None:
    head = token.strip().split(":", 1)[0]
    return int(head) if ":" in token and head.isdigit() else None


async def connect_bot(manager: BotManager, session: AsyncSession, settings: Settings, token: str, owner_id: int,
                      *, managed: bool = False, pending: bool = False) -> tuple[BotRecord, bool]:
    """Validates and starts a clone owned by ``owner_id`` (``pending``: stored, waiting for a super admin's
    approval, not started).

    Returns ``(record, is_new)``; ``is_new`` is False when the owner re-connects one of their bots.
    Raises :class:`BotTokenError` with the manager codes plus ``limit`` and ``admin_locked``.
    """
    bot_id = token_bot_id(token)
    if bot_id is None:
        raise BotTokenError("format")
    existing = await session.get(BotRecord, bot_id, populate_existing=True)
    if (existing is not None and existing.owner_id == owner_id and is_admin_locked(existing)
            and owner_id not in settings.super_admin_ids):
        # manager.add_bot would re-activate it, undoing the super admin's decision.
        raise BotTokenError("admin_locked")
    counted = (existing is not None and existing.owner_id == owner_id and not existing.is_main
               and not is_removed(existing))
    limit = await clone_limit(session, settings, owner_id)
    used = await count_user_bots(session, owner_id)
    if not counted and limit is not None and used >= limit:
        raise BotTokenError("limit")
    rec = await manager.add_bot(token, owner_id, managed=managed, pending=pending)
    is_new = existing is None or existing.owner_id != owner_id
    log.info("Clone @%s (%s) connected by %s (managed=%s, new=%s)", rec.username, rec.id, owner_id, managed, is_new)
    return rec, is_new


async def notify_new_clone(bot: Bot, session: AsyncSession, settings: Settings, rec: BotRecord, *,
                           owner_name: str, owner_username: str | None, managed: bool) -> None:
    """Tells every super admin (except the owner) about a new clone. ``bot`` is the main bot."""
    owner = user_link(rec.owner_id, owner_name, owner_username)
    for admin_id in sorted(settings.super_admin_ids):
        if admin_id == rec.owner_id:
            continue
        lang = await get_lang(session, bot.id, admin_id, settings.DEFAULT_LANG)
        method = t("cl.method.managed" if managed else "cl.method.token", lang)
        text = t("cl.new_admin", lang, bot=esc(rec.username), bot_id=rec.id, owner=owner, owner_id=rec.owner_id,
                 method=method)
        await send_dm(bot, session, admin_id, text)


# ------------------------------------------------------------------ Managed Bots
async def can_manage_bots(bot: Bot) -> bool:
    """``getMe().can_manage_bots`` ("Bot Management Mode" in BotFather), cached for a few minutes."""
    now = time.monotonic()
    cached = _can_manage.get(bot.id)
    if cached is not None and now - cached[0] < CAN_MANAGE_TTL:
        return cached[1]
    try:
        me = await bot.get_me()
    except TelegramAPIError as exc:
        log.warning("getMe failed while checking can_manage_bots: %s", exc)
        return cached[1] if cached is not None else False
    value = bool(me.can_manage_bots)
    _can_manage[bot.id] = (now, value)
    return value


def _slug(value: str | None) -> str:
    ascii_text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_]+", "_", ascii_text)).strip("_")


def suggest_username(username: str | None, first_name: str | None, user_id: int,
                     suffix: str = USERNAME_SUFFIX) -> str:
    """A valid bot username for the user: letters/digits/underscores, starts with a letter,
    ends in "bot", at most 32 characters. Telegram lets the user edit it before creating the bot."""
    base = _slug(username) or _slug(first_name)
    base = re.sub(r"(?i)_?bot$", "", base)
    base = base.lstrip("_0123456789") or f"u{user_id}"
    base = base[: USERNAME_MAX - len(suffix)].rstrip("_")
    return base + suffix


def newbot_url(manager_username: str, suggested_username: str, name: str) -> str:
    """Deep link that opens Telegram's "create a managed bot" dialog."""
    return f"https://t.me/newbot/{manager_username}/{suggested_username}?name={quote(name[:64])}"
