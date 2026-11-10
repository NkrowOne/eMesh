"""Shared helpers for the posts tests (this module has no tests of its own). Import the fixtures you use
(``engine_fixture`` / ``freq_screen_fixture``, used as ``engine`` / ``freq_screen``)."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import (DEFAULT_FREQ, BotUser, Chat, ChatGroup, ChatOrigin, ChatStatus, GroupChat, Post,
                            PostStatus, SchedMode)
from app.services import freq
from app.ui import screens
from app.ui.callbacks import MenuCB
from app.ui.common import show
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, App

NO_PERMISSION = "⛔ No tienes permiso para hacer esto."
NOT_FOUND = "⚠️ Ya no existe o fue eliminado."
EXPIRED = "⌛ Este botón ya no está activo. Pulsa /start."
TZ = "Europe/Madrid"
CLONE_ID = 7_000_000_031
CLONE_USERNAME = "clon_cine_bot"


async def started(app: App, *user_ids: int, bot_id: int = MAIN_BOT_ID) -> None:
    """Users open the bot with /start first (their rows are created in that update)."""
    for user_id in user_ids:
        await app.send(user_id, "/start", bot_id=bot_id)


async def open_menu(app: App, user_id: int, screen: str, arg: int = 0, bot_id: int = MAIN_BOT_ID) -> None:
    await app.press(user_id, MenuCB(screen=screen, arg=arg).pack(), bot_id=bot_id)


async def add_chat(app: App, chat_id: int, title: str = "Canal de Cine", members: int = 1000, *,
                   origin: str = ChatOrigin.OWN, status: str = ChatStatus.APPROVED, rights_ok: bool = True,
                   bot_id: int = MAIN_BOT_ID, **values: Any) -> int:
    async with app.db() as s:
        chat = Chat(bot_id=bot_id, chat_id=chat_id, title=title, members=members, origin=origin, status=status,
                    rights_ok=rights_ok, **values)
        s.add(chat)
        await s.flush()
        return chat.id


async def add_group(app: App, name: str, chat_pks: tuple[int, ...] = (), *, bot_id: int = MAIN_BOT_ID) -> int:
    async with app.db() as s:
        group = ChatGroup(bot_id=bot_id, name=name)
        s.add(group)
        await s.flush()
        for pk in chat_pks:
            s.add(GroupChat(group_id=group.id, chat_pk=pk))
        return group.id


async def add_post(app: App, *, bot_id: int = MAIN_BOT_ID, **values: Any) -> int:
    """A text post «Promo Cine» to everyone, ⏰ at its own times (the default schedule), plus ``values``."""
    base: dict[str, Any] = {"name": "Promo Cine", "kind": "text", "text": "<b>Promo</b> de cine", "targets": ["all"],
                            "mode": SchedMode.OWN, "freq": dict(DEFAULT_FREQ), "status": PostStatus.ACTIVE,
                            "buttons": [], "media": {}, "delete_previous": True, "delete_after": 0}
    async with app.db() as s:
        post = Post(bot_id=bot_id, **{**base, **values})
        s.add(post)
        await s.flush()
        freq.refresh_post(post, TZ, utcnow())
        return post.id


async def load(app: App, model: type, pk: Any) -> Any:
    async with app.db() as s:
        return await s.get(model, pk)


async def all_posts(app: App) -> list[Post]:
    async with app.db() as s:
        return list((await s.execute(select(Post).order_by(Post.id))).scalars())


async def add_clone(app: App, *, limit_posts: int | None = None) -> None:
    """A clone owned by OWNER2 (not a super admin, so the platform limits apply to it)."""
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    async with app.db() as s:
        rec = await s.get(BotRecord, CLONE_ID)
        assert rec is not None
        rec.limit_posts = limit_posts


async def manage_clone(app: App) -> None:
    """The super admin manages the clone's network from the main bot (🛠 Gestionar)."""
    await started(app, SUPER_ID)
    async with app.db() as s:
        bu = await s.get(BotUser, (MAIN_BOT_ID, SUPER_ID))
        assert bu is not None
        bu.ws_bot_id = CLONE_ID


def answers(app: App) -> list[str]:
    """Texts of every callback answer (toasts and alerts), oldest first."""
    return [str(c.params.get("text") or "") for c in app.fake.calls_of("answerCallbackQuery")]


def last_buttons(app: App, user_id: int) -> list[dict[str, Any]]:
    return app.buttons(app.last_panel(user_id))


def button_texts(app: App, user_id: int = SUPER_ID) -> list[str]:
    return [b["text"] for b in last_buttons(app, user_id)]


def keyboard(app: App, user_id: int = SUPER_ID) -> list[list[dict[str, Any]]]:
    return (app.last_panel(user_id).params.get("reply_markup") or {}).get("inline_keyboard", [])


@pytest.fixture(name="engine")
def engine_fixture(app: App, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Fake publisher / scheduler (the engine module is a stub here) that records how they are called."""
    rec = SimpleNamespace(busy=False, live=0, run_id=1, woke=0, sent=[], retired=[], updated=[])

    def wake() -> None:
        rec.woke += 1

    async def send_now(post_id: int, *, user_id: int | None = None) -> int | None:
        rec.sent.append((post_id, user_id))
        return rec.run_id

    async def retire(post_id: int) -> int:
        rec.retired.append(post_id)
        return rec.live

    async def update_live(post_id: int) -> tuple[int, int]:
        rec.updated.append(post_id)
        return rec.live, 0

    async def live_count(session: Any, post_id: int) -> int:
        return rec.live

    monkeypatch.setattr(app.publisher, "is_busy", lambda post_id: rec.busy)
    monkeypatch.setattr(app.publisher, "send_now", send_now)
    monkeypatch.setattr(app.publisher, "retire", retire)
    monkeypatch.setattr(app.publisher, "update_live", update_live)
    monkeypatch.setattr(app.scheduler, "wake", wake)
    monkeypatch.setattr("app.services.publisher.live_count", live_count)
    return rec


@pytest.fixture(name="freq_screen")
def freq_screen_fixture(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """A stand-in for the groups module's ``freq_edit`` screen: records the args it was opened with."""
    opened: list[int] = []

    async def fake_freq_edit(event: Any, ctx: Any, session: Any, arg: int = 0, **_: Any) -> None:
        opened.append(arg)
        await show(event, f"FREQ_EDIT {arg}")

    monkeypatch.setitem(screens._SCREENS, "freq_edit", fake_freq_edit)  # noqa: SLF001
    return opened
