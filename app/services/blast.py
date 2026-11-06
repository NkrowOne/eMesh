"""📢 A message copied to many users of one bot (partners, owners of clones), in the background."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import update

from app.db.models import BotUser
from app.db.session import SessionMaker, session_scope
from app.telegram.context import set_low_priority
from app.telegram.errors import is_user_blocked, short

log = logging.getLogger(__name__)


@dataclass
class BlastResult:
    sent: int = 0
    failed: int = 0
    blocked: int = 0


async def copy_to_users(bot: Bot, sm: SessionMaker, from_chat_id: int, message_id: int, user_ids: list[int], *,
                        on_progress: Callable[[BlastResult, int], Awaitable[None]] | None = None) -> BlastResult:
    """Copies the message ``message_id`` of ``from_chat_id`` (a chat of the same bot, e.g. the admin's) to every
    user. Users that blocked the bot are marked. Never raises because of Telegram."""
    set_low_priority()
    res = BlastResult()
    blocked: list[int] = []
    for i, uid in enumerate(dict.fromkeys(user_ids), 1):
        try:
            await bot.copy_message(uid, from_chat_id, message_id)
            res.sent += 1
        except TelegramAPIError as exc:
            if is_user_blocked(exc):
                res.blocked += 1
                blocked.append(uid)
            else:
                res.failed += 1
                log.info("Copy to %s failed: %s", uid, short(exc))
        if on_progress is not None and i % 25 == 0:
            await on_progress(res, i)
    if blocked:
        async with session_scope(sm) as s:
            await s.execute(update(BotUser).where(BotUser.bot_id == bot.id, BotUser.user_id.in_(blocked))
                            .values(is_blocked=True))
    return res
