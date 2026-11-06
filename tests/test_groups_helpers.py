"""Shared helpers for the groups / frequencies tests (this module has no tests of its own)."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.db.models import (
    BotUser,
    Chat,
    ChatGroup,
    ChatOrigin,
    ChatStatus,
    ChatType,
    GroupChat,
    Post,
    PostStatus,
    SchedMode,
)
from app.services import audience
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, SUPER_ID, App

TZ = "Europe/Madrid"
NO_PERMISSION = "⛔ No tienes permiso para hacer esto."
NOT_FOUND = "⚠️ Ya no existe o fue eliminado."


def count_wakes(app: App, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts the calls to ``scheduler.wake()`` (one ``1`` per call)."""
    calls: list[int] = []
    monkeypatch.setattr(app.scheduler, "wake", lambda: calls.append(1))
    return calls


async def started(app: App, *user_ids: int) -> None:
    for user_id in user_ids:
        await app.send(user_id, "/start")


async def open_menu(app: App, user_id: int, screen: str, arg: int = 0, bot_id: int = MAIN_BOT_ID) -> None:
    await app.press(user_id, MenuCB(screen=screen, arg=arg).pack(), bot_id=bot_id)


async def manage(app: App, clone_id: int) -> None:
    """The super admin manages the network of ``clone_id`` from the main bot (👑 Panel › 🛠 Gestionar)."""
    await app.send(SUPER_ID, "/start")
    async with app.db() as s:
        bu = await s.get(BotUser, (MAIN_BOT_ID, SUPER_ID))
        assert bu is not None
        bu.ws_bot_id = clone_id


async def add_chat(app: App, chat_id: int, title: str, *, members: int = 1000, status: str = ChatStatus.APPROVED,
                   origin: str = ChatOrigin.OWN, rights_ok: bool = True, admin_paused: bool = False,
                   chat_type: str = ChatType.CHANNEL, username: str | None = None, bot_id: int = MAIN_BOT_ID,
                   groups: Sequence[int] = ()) -> int:
    async with app.db() as s:
        chat = Chat(bot_id=bot_id, chat_id=chat_id, title=title, members=members, status=status, origin=origin,
                    rights_ok=rights_ok, admin_paused=admin_paused, owner_paused=False, type=chat_type,
                    username=username)
        s.add(chat)
        await s.flush()
        for group_id in groups:
            s.add(GroupChat(group_id=group_id, chat_pk=chat.id))
        return chat.id


async def add_group(app: App, name: str, *, freq: dict[str, Any] | None = None, open: bool = False,
                    chats: Sequence[int] = (), bot_id: int = MAIN_BOT_ID, sort: int = 0) -> int:
    async with app.db() as s:
        group = ChatGroup(bot_id=bot_id, name=name, freq=freq, open=open, sort=sort)
        s.add(group)
        await s.flush()
        for chat_pk in chats:
            s.add(GroupChat(group_id=group.id, chat_pk=chat_pk))
        return group.id


async def add_post(app: App, name: str, *, targets: Sequence[str] = ("all",), mode: str = SchedMode.ROTATION,
                   status: str = PostStatus.ACTIVE, freq: dict[str, Any] | None = None,
                   bot_id: int = MAIN_BOT_ID) -> int:
    async with app.db() as s:
        post = Post(bot_id=bot_id, name=name, text="Hola", targets=list(targets), mode=mode, status=status,
                    freq=freq)
        s.add(post)
        await s.flush()
        return post.id


async def load(app: App, model: type, pk: Any) -> Any:
    async with app.db() as s:
        return await s.get(model, pk)


async def members_of(app: App, group_id: int) -> set[int]:
    async with app.db() as s:
        return await audience.group_chat_pks(s, group_id)


def answers(app: App) -> list[str]:
    """Texts of every callback answer (toasts and alerts), oldest first."""
    return [str(c.params.get("text") or "") for c in app.fake.calls_of("answerCallbackQuery")]


def button_texts(app: App, user_id: int = SUPER_ID) -> list[str]:
    return [b["text"] for b in app.buttons(app.last_panel(user_id))]


def button_data(app: App, contains: str, user_id: int = SUPER_ID) -> str:
    b, _ = app.find_button(user_id, contains)
    return str(b.get("callback_data"))
