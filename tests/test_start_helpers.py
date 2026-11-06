"""Shared helpers of the start module tests (test_start_*, test_settings*, test_stats*). No tests live here."""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

import pytest
from aiogram.fsm.storage.base import StorageKey

from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import (
    BotUser,
    Chat,
    ChatGroup,
    ChatOrigin,
    ChatStatus,
    ChatType,
    Event,
    Post,
    PostStatus,
    Role,
    Run,
    RunStatus,
    SchedMode,
)
from app.ui import screens
from app.ui.common import show
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, App

CLONE_ID = 7_000_000_001
CLONE_USERNAME = "clone_test_bot"
NO_PERMISSION = "⛔ No tienes permiso para hacer esto."

# Screens owned by other modules: the tests register stand-ins so deep links and menu buttons can be followed.
FOREIGN_SCREENS = (
    "posts", "post", "chats", "chat", "requests", "paused", "my_chats", "my_chat", "join", "groups", "freqs",
    "clone", "mybots", "panel",
)


@pytest.fixture
def stub_screens(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Replaces the screens of the other modules with stand-ins that record ``(name, arg)``."""
    calls: list[tuple[str, int]] = []

    def make(name: str) -> Callable[..., Any]:
        async def fn(event: Any, ctx: Any, session: Any, arg: int = 0, **_: Any) -> None:
            calls.append((name, arg))
            await show(event, f"stub:{name}:{arg}")

        return fn

    for name in FOREIGN_SCREENS:
        monkeypatch.setitem(screens._SCREENS, name, make(name))  # noqa: SLF001
    return calls


async def add_clone(app: App, *, owner_id: int = OWNER2_ID, timezone_set: bool = True,
                    setup_done: bool = True) -> int:
    """Registers and starts a clone owned by ``owner_id``. Returns its id. ``timezone_set`` / ``setup_done``: its
    owner already chose the timezone / went through the setup wizard (a brand new clone has both False)."""
    await app.add_clone(CLONE_ID, CLONE_USERNAME, owner_id, setup_done=setup_done)
    async with app.db() as s:
        rec = await s.get(BotRecord, CLONE_ID)
        assert rec is not None
        rec.timezone_set = timezone_set
    return CLONE_ID


async def get_bot(app: App, bot_id: int = MAIN_BOT_ID) -> BotRecord:
    async with app.db() as s:
        rec = await s.get(BotRecord, bot_id)
    assert rec is not None
    return rec


@asynccontextmanager
async def edit_bot(app: App, bot_id: int = MAIN_BOT_ID) -> AsyncIterator[BotRecord]:
    """Loads the bot row, lets the test change it and commits."""
    async with app.db() as s:
        rec = await s.get(BotRecord, bot_id)
        assert rec is not None
        yield rec


async def get_bu(app: App, user_id: int, bot_id: int = MAIN_BOT_ID) -> BotUser:
    async with app.db() as s:
        bu = await s.get(BotUser, (bot_id, user_id))
    assert bu is not None, f"user {user_id} never started bot {bot_id}"
    return bu


async def make_admin(app: App, user_id: int, bot_id: int = MAIN_BOT_ID) -> None:
    """The user starts the bot and becomes one of its admins."""
    await app.send(user_id, "/start", bot_id=bot_id)
    async with app.db() as s:
        bu = await s.get(BotUser, (bot_id, user_id))
        assert bu is not None
        bu.role = Role.ADMIN


async def manage(app: App, user_id: int, bot_id: int) -> None:
    """A super admin manages ``bot_id`` from the main bot (👑 Panel › 🛠 Gestionar)."""
    await app.send(user_id, "/start")
    async with app.db() as s:
        bu = await s.get(BotUser, (MAIN_BOT_ID, user_id))
        assert bu is not None
        bu.ws_bot_id = bot_id


# ------------------------------------------------------------------------------------------- seeding
_next_chat_id = iter(range(-1_001_000_000_001, -1_002_000_000_000, -1))


async def add_chat_row(app: App, *, bot_id: int = MAIN_BOT_ID, title: str = "Canal de Cine", members: int = 1000,
                       origin: str = ChatOrigin.OWN, status: str = ChatStatus.APPROVED, rights_ok: bool = True,
                       owner_user_id: int | None = None, owner_paused: bool = False,
                       owner_paused_until: datetime | None = None, admin_paused: bool = False,
                       type: str = ChatType.CHANNEL) -> int:
    async with app.db() as s:
        chat = Chat(bot_id=bot_id, chat_id=next(_next_chat_id), type=type, title=title, members=members,
                    origin=origin, status=status, rights_ok=rights_ok, owner_user_id=owner_user_id,
                    owner_paused=owner_paused, owner_paused_until=owner_paused_until, admin_paused=admin_paused)
        s.add(chat)
        await s.flush()
        return chat.id


async def add_post(app: App, *, bot_id: int = MAIN_BOT_ID, name: str = "Promo Cine", status: str = PostStatus.ACTIVE,
                   mode: str = SchedMode.ROTATION, freq: dict[str, Any] | None = None,
                   send_at: datetime | None = None) -> int:
    async with app.db() as s:
        post = Post(bot_id=bot_id, name=name, text=name, status=status, mode=mode, freq=freq, send_at=send_at)
        s.add(post)
        await s.flush()
        return post.id


async def add_group(app: App, *, bot_id: int = MAIN_BOT_ID, name: str = "Cine", freq: dict[str, Any] | None = None,
                    open: bool = False) -> int:
    async with app.db() as s:
        group = ChatGroup(bot_id=bot_id, name=name, freq=freq, open=open)
        s.add(group)
        await s.flush()
        return group.id


async def add_run(app: App, *, ago: timedelta, bot_id: int = MAIN_BOT_ID, post_name: str = "Promo Cine",
                  sent: int = 0, failed: int = 0, skipped: int = 0, reach: int = 0) -> None:
    async with app.db() as s:
        s.add(Run(bot_id=bot_id, post_name=post_name, status=RunStatus.DONE, total=sent + failed + skipped,
                  sent=sent, failed=failed, skipped=skipped, reach=reach, started_at=utcnow() - ago))


async def add_event(app: App, kind: str, *, bot_id: int = MAIN_BOT_ID, chat_title: str = "Canal de Cine",
                    actor_id: int | None = None, data: dict[str, Any] | None = None,
                    created_at: datetime | None = None) -> None:
    async with app.db() as s:
        s.add(Event(bot_id=bot_id, kind=kind, chat_title=chat_title, actor_id=actor_id, data=data or {},
                    created_at=created_at or utcnow()))


# --------------------------------------------------------------------------------------------- panels
def last_buttons(app: App, chat_id: int) -> list[dict[str, Any]]:
    return app.buttons(app.last_panel(chat_id))


def button_texts(app: App, chat_id: int) -> list[str]:
    return [b["text"] for b in last_buttons(app, chat_id)]


def button_rows(app: App, chat_id: int) -> list[list[str]]:
    markup = app.last_panel(chat_id).params.get("reply_markup") or {}
    return [[b["text"] for b in row] for row in markup.get("inline_keyboard", [])]


def has_button(app: App, chat_id: int, contains: str) -> bool:
    return any(contains.lower() in text.lower() for text in button_texts(app, chat_id))


def button_of(app: App, chat_id: int, contains: str) -> dict[str, Any]:
    """The button of the LAST panel whose text contains ``contains``."""
    for b in last_buttons(app, chat_id):
        if contains.lower() in b["text"].lower():
            return b
    raise AssertionError(f"button {contains!r} not in {button_texts(app, chat_id)}")


def callback_of(app: App, chat_id: int, contains: str) -> str:
    b = button_of(app, chat_id, contains)
    assert "callback_data" in b, f"{b} is not a callback button"
    return str(b["callback_data"])


def url_of(app: App, chat_id: int, contains: str) -> str:
    b = button_of(app, chat_id, contains)
    assert "url" in b, f"{b} is not a URL button"
    return str(b["url"])


def last_answer(app: App) -> dict[str, Any]:
    """The last ``answerCallbackQuery`` (toast or alert)."""
    call = app.fake.last("answerCallbackQuery")
    assert call is not None, "no callback was answered"
    return call.params


def denied(app: App) -> bool:
    """The last button press was answered with the "no permission" alert."""
    answer = last_answer(app)
    return answer.get("text") == NO_PERMISSION and str(answer.get("show_alert")).lower() == "true"


def dms_to(app: App, user_id: int, bot_id: int = MAIN_BOT_ID) -> list[str]:
    """Texts of the messages the given bot sent to the user, oldest first."""
    token = f"{bot_id}:TEST{bot_id}"
    return [str(c.params.get("text")) for c in app.fake.messages_to(user_id) if c.token == token]


async def fsm_state(app: App, user_id: int, bot_id: int = MAIN_BOT_ID) -> str | None:
    return await app.storage.get_state(StorageKey(bot_id=bot_id, chat_id=user_id, user_id=user_id))


async def force_state(app: App, user_id: int, state: str, bot_id: int = MAIN_BOT_ID) -> None:
    await app.storage.set_state(StorageKey(bot_id=bot_id, chat_id=user_id, user_id=user_id), state)
