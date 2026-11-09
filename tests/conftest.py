"""Test fixtures: a fake Telegram server + the whole application wired against it."""
from __future__ import annotations

import asyncio
import itertools
import os
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("BOT_TOKEN", "1:placeholder")

from aiogram.types import Update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app import i18n  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import create_engine, create_sessionmaker  # noqa: E402
from app.main import build_dispatcher  # noqa: E402
from app.services import clones  # noqa: E402
from app.services.publisher import Publisher  # noqa: E402
from app.services.scheduler import Scheduler  # noqa: E402
from app.telegram.manager import BotManager  # noqa: E402
from tests.fake_tg import ADMIN_RIGHTS_FULL, Call, FakeTelegram  # noqa: E402

MAIN_BOT_ID = 5_000_000_001
MAIN_BOT_USERNAME = "emesh_test_bot"
SUPER_ID = 111
OWNER2_ID = 222  # a regular user that will own a clone in some tests
USER_ID = 333  # a regular channel owner

_msg_ids = itertools.count(10_000)
_cb_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _skip_user_timezone_question(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Users are asked their timezone before the menu; most tests are about other screens, so they skip it
    (tests marked ``ask_timezone`` keep it)."""
    if request.node.get_closest_marker("ask_timezone"):
        return
    from app.bot.routers import start

    async def never(session: object, ctx: object, **_: object) -> bool:
        return False

    monkeypatch.setattr(start, "must_choose_timezone", never, raising=False)


@pytest.fixture(autouse=True)
def _no_waiting_prompts() -> None:
    """The input prompts waiting in each chat are kept in memory: every test starts without any."""
    from app.ui import common

    common._prompts.clear()


@pytest.fixture
async def fake() -> AsyncIterator[FakeTelegram]:
    f = FakeTelegram()
    await f.start()
    yield f
    await f.stop()


@pytest.fixture
def settings(tmp_path, fake: FakeTelegram) -> Settings:
    token = fake.add_bot(MAIN_BOT_ID, MAIN_BOT_USERNAME, first_name="eMesh", can_manage_bots=True)
    fake.add_user(SUPER_ID, "Super", "superadmin")
    fake.add_user(OWNER2_ID, "Owner2", "owner2")
    fake.add_user(USER_ID, "Pepe", "pepe")
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        BOT_TOKEN=token,
        SUPER_ADMIN_IDS=str(SUPER_ID),
        DATABASE_URL=os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        TELEGRAM_API_BASE=fake.base_url,
        RUN_MIGRATIONS=False,
        ENCRYPTION_KEY=Fernet.generate_key().decode(),
        MODE="webhook",
        WEBHOOK_BASE_URL="https://example.test",
        RL_GLOBAL_PER_SEC=500,
        RL_BULK_PER_SEC=400,
        RL_PRIVATE_PER_SEC=100,
        RL_PRIVATE_BURST=100,
        RL_GROUP_PER_MIN=1000,
        SCHEDULER_TICK_SECONDS=1,
        THROTTLE_LIMIT=100_000,
        MAIN_BOT_MODE="full",  # most tests run a network on the main bot; hub tests switch it
    )


class App:
    """Everything a test needs: fake world, DB, manager and update helpers."""

    def __init__(self, fake: FakeTelegram, settings: Settings, engine, sm, dp, storage, manager: BotManager,
                 publisher: Publisher, scheduler: Scheduler) -> None:
        self.fake = fake
        self.settings = settings
        self.engine = engine
        self.sm = sm
        self.dp = dp
        self.storage = storage
        self.manager = manager
        self.publisher = publisher
        self.scheduler = scheduler

    # --------------------------------------------------------------- basics
    @property
    def main_bot(self):  # noqa: ANN201
        bot = self.manager.main_bot
        assert bot is not None
        return bot

    def bot_user_json(self, bot_id: int = MAIN_BOT_ID) -> dict[str, Any]:
        return next(b for b in self.fake.bots.values() if b["id"] == bot_id)

    @asynccontextmanager
    async def db(self) -> AsyncIterator[AsyncSession]:
        async with self.sm() as s:
            yield s
            await s.commit()

    async def feed(self, update: dict[str, Any], bot_id: int = MAIN_BOT_ID) -> None:
        bot = self.manager.get(bot_id)
        assert bot is not None, f"bot {bot_id} is not running"
        upd = Update.model_validate(update, context={"bot": bot})
        await self.manager.feed(bot, upd)

    # -------------------------------------------------------------- builders
    def _user(self, user_id: int) -> dict[str, Any]:
        return self.fake.users.get(user_id) or self.fake.add_user(user_id, f"U{user_id}")

    def message_update(self, user_id: int, text: str | None = None, *, photo: str | None = None,
                       video: str | None = None, animation: str | None = None, caption: str | None = None,
                       entities: list[dict[str, Any]] | None = None,
                       caption_entities: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        user = self._user(user_id)
        msg: dict[str, Any] = {
            "message_id": next(_msg_ids),
            "date": int(time.time()),
            "chat": {"id": user_id, "type": "private", "first_name": user["first_name"]},
            "from": user,
        }
        if text is not None:
            msg["text"] = text
            if text.startswith("/") and entities is None:
                entities = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
            if entities:
                msg["entities"] = entities
        if photo:
            msg["photo"] = [{"file_id": photo, "file_unique_id": f"u{photo}", "width": 100, "height": 100}]
        for kind, fid in (("video", video), ("animation", animation)):
            if fid:
                msg[kind] = {"file_id": fid, "file_unique_id": f"u{fid}", "width": 10, "height": 10, "duration": 1}
        if caption is not None:
            msg["caption"] = caption
            if caption_entities:
                msg["caption_entities"] = caption_entities
        return {"update_id": self.fake.new_update_id(), "message": msg}

    def callback_update(self, user_id: int, data: str, message_id: int = 1, *, text: str = "panel",
                        bot_id: int = MAIN_BOT_ID) -> dict[str, Any]:
        user = self._user(user_id)
        return {
            "update_id": self.fake.new_update_id(),
            "callback_query": {
                "id": str(next(_cb_ids)),
                "from": user,
                "chat_instance": "ci",
                "data": data,
                "message": {
                    "message_id": message_id,
                    "date": int(time.time()),
                    "chat": {"id": user_id, "type": "private", "first_name": user["first_name"]},
                    "from": self.bot_user_json(bot_id),
                    "text": text,
                },
            },
        }

    def my_chat_member_update(self, chat_id: int, user_id: int, *, new: str = "administrator",
                              old: str = "left", rights: dict[str, Any] | str | None = "full",
                              bot_id: int = MAIN_BOT_ID) -> dict[str, Any]:
        """The bot was added/promoted/removed in a chat. Also updates the fake world accordingly."""
        chat = self.fake.chats[chat_id]
        bot_user = self.bot_user_json(bot_id)
        if new == "administrator":
            r = dict(ADMIN_RIGHTS_FULL) if rights == "full" else dict(rights or {})
            chat.bot_admin[bot_id] = r
            new_member: dict[str, Any] = {"status": "administrator", "user": bot_user, **r}
        elif new == "member":
            chat.bot_admin[bot_id] = None
            new_member = {"status": "member", "user": bot_user}
        elif new == "kicked":
            chat.bot_admin.pop(bot_id, None)
            new_member = {"status": "kicked", "user": bot_user, "until_date": 0}
        else:
            chat.bot_admin.pop(bot_id, None)
            new_member = {"status": "left", "user": bot_user}
        old_member: dict[str, Any] = {"status": old, "user": bot_user}
        if old == "administrator":
            old_member.update(ADMIN_RIGHTS_FULL)
        elif old == "kicked":
            old_member["until_date"] = 0
        return {
            "update_id": self.fake.new_update_id(),
            "my_chat_member": {
                "chat": self.fake.chat_json(chat_id),
                "from": self._user(user_id),
                "date": int(time.time()),
                "old_chat_member": old_member,
                "new_chat_member": new_member,
            },
        }

    def channel_post_update(self, chat_id: int, text: str = "post", **extra: Any) -> dict[str, Any]:
        """A post published in a channel (or, for a group, a message from a member)."""
        chat = self.fake.chat_json(chat_id)
        msg: dict[str, Any] = {"message_id": next(_msg_ids), "date": int(time.time()), "chat": chat, "text": text,
                               **extra}
        if chat["type"] == "channel":
            msg["sender_chat"] = chat
            return {"update_id": self.fake.new_update_id(), "channel_post": msg}
        msg["from"] = self._user(USER_ID)
        return {"update_id": self.fake.new_update_id(), "message": msg}

    async def add_chat(self, chat_id: int, user_id: int, title: str = "Canal", *, type: str = "channel",
                       members: int = 1000, bot_id: int = MAIN_BOT_ID, rights: dict[str, Any] | str | None = "full",
                       username: str | None = None) -> None:
        """Creates the chat in the fake world (if needed) and adds the bot to it as admin, added by ``user_id``."""
        if chat_id not in self.fake.chats:
            self.fake.add_chat(chat_id, title, type=type, members=members, username=username, creator=user_id)
        await self.feed(self.my_chat_member_update(chat_id, user_id, rights=rights, bot_id=bot_id), bot_id)

    async def add_clone(self, bot_id: int, username: str, owner_id: int, *, setup_done: bool = True) -> None:
        """Registers and starts a clone owned by ``owner_id`` (as if connected with a token). ``setup_done``: its
        owner already went through the setup wizard (tests of the wizard pass False)."""
        from app.db.models import Bot as BotRecord

        token = self.fake.add_bot(bot_id, username, first_name=username)
        await self.manager.add_bot(token, owner_id)
        async with self.db() as s:
            rec = await s.get(BotRecord, bot_id)
            assert rec is not None
            rec.setup_done = setup_done

    # ------------------------------------------------------------- shortcuts
    async def send(self, user_id: int, text: str, bot_id: int = MAIN_BOT_ID, **kw: Any) -> None:
        await self.feed(self.message_update(user_id, text, **kw), bot_id)

    async def press(self, user_id: int, data: str, message_id: int = 1, bot_id: int = MAIN_BOT_ID) -> None:
        await self.feed(self.callback_update(user_id, data, message_id, bot_id=bot_id), bot_id)

    def panels(self, chat_id: int, token: str | None = None) -> list[Call]:
        """Messages sent or edited in a private chat, oldest first."""
        methods = {"sendMessage", "sendPhoto", "sendVideo", "sendAnimation", "editMessageText",
                   "editMessageCaption", "editMessageReplyMarkup"}
        return [c for c in self.fake.calls
                if c.method in methods and str(c.params.get("chat_id")) == str(chat_id)
                and (token is None or c.token == token)]

    def last_panel(self, chat_id: int) -> Call:
        panels = self.panels(chat_id)
        assert panels, f"nothing was sent to {chat_id}"
        return panels[-1]

    def last_text(self, chat_id: int) -> str:
        p = self.last_panel(chat_id).params
        return str(p.get("text") or p.get("caption") or "")

    @staticmethod
    def buttons(call: Call) -> list[dict[str, Any]]:
        markup = call.params.get("reply_markup") or {}
        return [b for row in markup.get("inline_keyboard", []) for b in row]

    @staticmethod
    def message_id_of(call: Call) -> int | None:
        mid = call.params.get("message_id") or (call.result or {}).get("message_id")
        return int(mid) if mid is not None else None

    def find_button(self, chat_id: int, contains: str) -> tuple[dict[str, Any], Call]:
        """Finds a button by (part of) its text in the latest panels of ``chat_id``.

        Only the current version of each message counts (a later edit supersedes earlier keyboards).
        """
        seen: set[int] = set()
        for call in reversed(self.panels(chat_id)):
            mid = self.message_id_of(call)
            if mid is not None:
                if mid in seen:
                    continue
                seen.add(mid)
            for b in self.buttons(call):
                if contains.lower() in b["text"].lower():
                    return b, call
        raise AssertionError(f"button {contains!r} not found for {chat_id}; last: {self.last_text(chat_id)[:300]}")

    async def click(self, user_id: int, contains: str, bot_id: int = MAIN_BOT_ID) -> None:
        b, call = self.find_button(user_id, contains)
        assert "callback_data" in b, f"button {b} is not a callback button"
        mid = call.params.get("message_id") or (call.result or {}).get("message_id", 1)
        await self.press(user_id, b["callback_data"], int(mid), bot_id)

    async def wait_for(self, cond: Callable[[], Any], timeout: float = 5.0, every: float = 0.05) -> Any:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            res = cond()
            if asyncio.iscoroutine(res):
                res = await res
            if res:
                return res
            await asyncio.sleep(every)
        raise AssertionError("condition not met in time")


@pytest.fixture
async def app(settings: Settings, fake: FakeTelegram) -> AsyncIterator[App]:
    i18n.load()
    engine = create_engine(settings)
    sm = create_sessionmaker(engine)
    async with engine.begin() as conn:
        if not settings.is_sqlite:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    dp, storage = build_dispatcher(settings, sm)
    manager = BotManager(dp, settings, sm)
    publisher = Publisher(manager, sm, settings)
    scheduler = Scheduler(manager, sm, settings, publisher)
    dp.workflow_data.update(settings=settings, sm=sm, manager=manager, publisher=publisher, scheduler=scheduler)
    clones.install(manager, sm, settings)
    await manager.start()
    a = App(fake, settings, engine, sm, dp, storage, manager, publisher, scheduler)
    try:
        yield a
    finally:
        try:
            await scheduler.stop()
        except Exception:  # noqa: BLE001
            pass
        await manager.shutdown()
        await storage.close()
        await engine.dispose()
