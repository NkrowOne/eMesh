"""Per update context (``ctx``) injected into every handler, plus the core middlewares."""
from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, TelegramObject, Update
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import BotStatus, BotUser, Role, User
from app.db.session import SessionMaker
from app.i18n import normalize_lang, t
from app.ui.common import callback_answered, ws_banner
from app.ui.fmt import esc

if TYPE_CHECKING:
    from app.telegram.manager import BotManager

log = logging.getLogger(__name__)

ROLE_RANK = {Role.USER: 0, Role.ADMIN: 1, Role.OWNER: 2, Role.SUPER: 3}


@dataclass
class Ctx:
    """Who is talking to which bot, and which bot's data they manage.

    * ``bot_rec`` / ``bot_id``: the bot that receives the update and answers the user.
    * ``ws`` / ``ws_id`` (workspace): the bot whose network (chats, groups, posts, settings) the screens show and
      change. It is ``bot_rec`` except for a super admin who manages a clone from a main bot (👑 Panel ›
      🛠 Gestionar): then ``ws`` is that clone and ``in_ws`` is True. Chat API calls on the network (sending,
      leaving a chat, checking rights) go through ``ws_bot()``; answers to the user through the update's bot.
    """

    bot_rec: BotRecord
    user: User | None
    bu: BotUser | None
    role: str
    lang: str
    settings: Settings
    extra: dict[str, Any] = field(default_factory=dict)
    manager: BotManager | None = None
    ws: BotRecord | None = None

    def __post_init__(self) -> None:
        if self.ws is None:
            self.ws = self.bot_rec

    # --- roles -------------------------------------------------------------
    @property
    def is_super(self) -> bool:
        return self.role == Role.SUPER

    @property
    def is_owner(self) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[Role.OWNER]

    @property
    def is_admin(self) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[Role.ADMIN]

    def at_least(self, role: str) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]

    # --- bot ---------------------------------------------------------------
    @property
    def is_main(self) -> bool:
        return self.bot_rec.is_main

    @property
    def is_hub(self) -> bool:
        """The main bot in hub mode (and not managing a clone): it creates clones and runs no network."""
        return self.bot_rec.is_main and self.settings.MAIN_BOT_MODE == "hub" and not self.in_ws

    @property
    def bot_id(self) -> int:
        return self.bot_rec.id

    # --- workspace ---------------------------------------------------------
    @property
    def ws_rec(self) -> BotRecord:
        assert self.ws is not None
        return self.ws

    @property
    def ws_id(self) -> int:
        return self.ws_rec.id

    @property
    def in_ws(self) -> bool:
        """A super admin managing another bot's network from this one."""
        return self.ws_rec.id != self.bot_rec.id

    def ws_bot(self) -> Bot | None:
        """The running aiogram Bot of the workspace (None when it isn't running)."""
        if self.manager is None:
            return None
        return self.manager.get(self.ws_id)

    # --- user --------------------------------------------------------------
    @property
    def user_id(self) -> int:
        return self.user.id if self.user else 0

    @property
    def bot_tz(self) -> str:
        """Timezone of the workspace: its frequencies and dates are in it."""
        return self.ws_rec.timezone or self.settings.DEFAULT_TIMEZONE

    @property
    def tz(self) -> str:
        """Timezone used to DISPLAY dates to the current user."""
        if self.is_admin:
            return self.bot_tz
        return (self.bu.timezone if self.bu and self.bu.timezone else None) or self.bot_tz

    def t(self, key: str, **kwargs: object) -> str:
        return t(key, self.lang, **kwargs)


def resolve_role(settings: Settings, bot_rec: BotRecord, user_id: int, bu: BotUser | None) -> str:
    if user_id in settings.super_admin_ids:
        return Role.SUPER
    if user_id == bot_rec.owner_id:
        return Role.OWNER
    if bu is not None and bu.role == Role.ADMIN:
        return Role.ADMIN
    return Role.USER


async def insert_ignore(session: AsyncSession, model: type, values: dict[str, Any]) -> None:
    """INSERT ... ON CONFLICT DO NOTHING (safe when two updates create the same row at once)."""
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    await session.execute(insert(model).values(**values).on_conflict_do_nothing())


async def upsert_user(session: AsyncSession, tg: TgUser) -> User:
    user = await session.get(User, tg.id)
    if user is None:
        now = utcnow()
        await insert_ignore(session, User, {
            "id": tg.id, "first_name": tg.first_name or "", "last_name": tg.last_name, "username": tg.username,
            "language_code": tg.language_code, "created_at": now, "updated_at": now,
        })
        user = await session.get(User, tg.id)
        assert user is not None
        return user
    if (user.first_name, user.last_name, user.username, user.language_code) != (
        tg.first_name or "", tg.last_name, tg.username, tg.language_code
    ):
        user.first_name = tg.first_name or ""
        user.last_name = tg.last_name
        user.username = tg.username
        user.language_code = tg.language_code
    return user


class DbContextMiddleware(BaseMiddleware):
    """Opens one DB session per update and builds ``ctx``."""

    def __init__(self, sessionmaker: SessionMaker, settings: Settings) -> None:
        self.sm = sessionmaker
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bot = data["bot"]
        async with self.sm() as session:
            bot_rec = await session.get(BotRecord, bot.id)
            if bot_rec is None or bot_rec.status != BotStatus.ACTIVE:
                return None
            tg_user: TgUser | None = data.get("event_from_user")
            tg_chat = data.get("event_chat")
            user: User | None = None
            bu: BotUser | None = None
            private = tg_chat is not None and tg_chat.type == "private"
            if tg_user is not None and not tg_user.is_bot:
                user = await upsert_user(session, tg_user)
                bu = await session.get(BotUser, (bot_rec.id, user.id))
                if bu is None and private:
                    now = utcnow()
                    await insert_ignore(session, BotUser, {
                        "bot_id": bot_rec.id, "user_id": user.id, "lang": normalize_lang(tg_user.language_code),
                        "role": Role.USER, "notify": True, "summary": True, "run_reports": False,
                        "is_blocked": False, "is_banned": False, "started_at": now, "last_seen_at": now,
                    })
                    bu = await session.get(BotUser, (bot_rec.id, user.id))
                if bu is not None and private:
                    now = utcnow()
                    if bu.is_blocked:
                        bu.is_blocked = False
                    if now - (bu.last_seen_at or now) > timedelta(minutes=30):
                        bu.last_seen_at = now
            role = resolve_role(self.settings, bot_rec, user.id if user else 0, bu)
            if bu is not None and bu.is_banned and role == Role.USER:
                return None
            lang = bu.lang if bu else normalize_lang(tg_user.language_code if tg_user else None)
            ws = await self._workspace(session, bot_rec, bu, role)
            ctx = Ctx(bot_rec=bot_rec, user=user, bu=bu, role=role, lang=lang, settings=self.settings,
                      manager=data.get("manager"), ws=ws)
            # Release the write lock of the user upsert now: handlers may write through other sessions
            # (FSM storage, BotManager) and SQLite only has one writer.
            await session.commit()
            data["session"] = session
            data["ctx"] = ctx
            token = ws_banner.set(t("ws.banner", lang, username=esc(ws.username or ws.id)) if ctx.in_ws else "")
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
            finally:
                ws_banner.reset(token)

    @staticmethod
    async def _workspace(session: AsyncSession, bot_rec: BotRecord, bu: BotUser | None, role: str) -> BotRecord:
        """The bot whose network the user manages: a super admin in a main bot may manage a clone."""
        if bu is None or not bu.ws_bot_id or role != Role.SUPER or not bot_rec.is_main or bu.ws_bot_id == bot_rec.id:
            return bot_rec
        target = await session.get(BotRecord, bu.ws_bot_id)
        if target is None:
            bu.ws_bot_id = None
            return bot_rec
        return target


class ThrottleMiddleware(BaseMiddleware):
    """Drops floods: more than ``limit`` updates in ``window`` seconds from one user."""

    def __init__(self, limit: int = 30, window: float = 10.0) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[tuple[int, int], deque[float]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: TgUser | None = data.get("event_from_user")
        if user is None or not isinstance(event, Update) or not (event.message or event.callback_query):
            return await handler(event, data)
        key = (data["bot"].id, user.id)
        now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window:
            hits.popleft()
        hits.append(now)
        if len(hits) > self.limit:
            if event.callback_query is not None:
                try:
                    await event.callback_query.answer("⏳")
                except TelegramBadRequest:
                    pass
            return None
        if len(self._hits) > 50_000:
            self._hits.clear()
        return await handler(event, data)


class CallbackAutoAnswerMiddleware(BaseMiddleware):
    """Answers every callback query after its handler (unless the handler already did via ``toast``)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        token = callback_answered.set(False)
        try:
            result = await handler(event, data)
        except Exception:
            # Let the error handler answer with an alert.
            callback_answered.reset(token)
            raise
        if isinstance(event, CallbackQuery) and not callback_answered.get():
            try:
                await event.answer()
            except Exception:  # noqa: BLE001
                pass
        callback_answered.reset(token)
        return result
