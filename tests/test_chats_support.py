"""Shared helpers of the chats module tests (no tests here)."""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.bot.routers import chat_events
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import BotUser, Chat, ChatGroup, ChatOrigin, ChatStatus, Event, Role
from tests.conftest import MAIN_BOT_ID, SUPER_ID, USER_ID, App
from tests.fake_tg import ADMIN_RIGHTS_FULL, Call

CHANNEL = -1001000000001
GROUP = -1001000000002
CLONE_ID = 7_000_000_011
CLONE_USERNAME = "clon_cine_bot"


@pytest.fixture(autouse=True)
def reset_chat_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordering of my_chat_member updates and the discovery are remembered in memory per (bot, chat): every
    test starts clean (the chat ids repeat between tests). Discovery runs at once."""
    chat_events._member_dates.clear()  # noqa: SLF001
    chat_events._discovered.clear()  # noqa: SLF001
    monkeypatch.setattr(chat_events, "DISCOVERY_DELAY", 0.0)


def full_rights(**override: bool) -> dict[str, Any]:
    return {**ADMIN_RIGHTS_FULL, **override}


async def start(app: App, *user_ids: int, bot_id: int = MAIN_BOT_ID) -> None:
    for uid in user_ids:
        await app.send(uid, "/start", bot_id=bot_id)


async def set_bot(app: App, bot_id: int = MAIN_BOT_ID, **values: Any) -> None:
    async with app.db() as s:
        rec = await s.get(BotRecord, bot_id)
        assert rec is not None
        for key, value in values.items():
            setattr(rec, key, value)


async def make_admin(app: App, user_id: int, bot_id: int = MAIN_BOT_ID) -> None:
    async with app.db() as s:
        bu = await s.get(BotUser, (bot_id, user_id))
        assert bu is not None, "the user must have started the bot"
        bu.role = Role.ADMIN


async def get_chat(app: App, chat_id: int = CHANNEL, bot_id: int = MAIN_BOT_ID) -> Chat | None:
    async with app.db() as s:
        q = select(Chat).where(Chat.bot_id == bot_id, Chat.chat_id == chat_id)
        return (await s.execute(q)).scalars().first()


async def add_chat(app: App, chat_id: int = CHANNEL, title: str = "Cine HD", *, user: int = USER_ID,
                   members: int = 1200, rights: dict[str, Any] | str = "full", new: str = "administrator",
                   old: str = "left", type: str = "channel", username: str | None = None,
                   bot_id: int = MAIN_BOT_ID) -> None:
    """Feeds the ``my_chat_member`` update of the bot being added (or changed) in a chat by ``user``."""
    if chat_id not in app.fake.chats:
        app.fake.add_chat(chat_id, title, type=type, members=members, username=username, creator=user)
    await app.feed(app.my_chat_member_update(chat_id, user, new=new, old=old, rights=rights, bot_id=bot_id), bot_id)


async def remove_bot(app: App, chat_id: int = CHANNEL, *, by: int = USER_ID, new: str = "left",
                     bot_id: int = MAIN_BOT_ID) -> None:
    await app.feed(app.my_chat_member_update(chat_id, by, new=new, old="administrator", bot_id=bot_id), bot_id)


async def partner_chat(app: App, chat_id: int = CHANNEL, title: str = "Cine HD", *, user: int = USER_ID,
                       bot_id: int = MAIN_BOT_ID, **kw: Any) -> Chat:
    """An external chat of ``user`` approved at once (the network admits partners without approval)."""
    async with app.db() as s:
        rec = await s.get(BotRecord, bot_id)
        assert rec is not None
        before = (rec.join_open, rec.join_approval)
        rec.join_open, rec.join_approval = True, False
    await add_chat(app, chat_id, title, user=user, bot_id=bot_id, **kw)
    await set_bot(app, bot_id, join_open=before[0], join_approval=before[1])
    chat = await get_chat(app, chat_id, bot_id)
    assert chat is not None and chat.status == ChatStatus.APPROVED and chat.origin == ChatOrigin.EXTERNAL
    return chat


async def db_chat(app: App, chat_id: int, title: str, *, bot_id: int = MAIN_BOT_ID, origin: str = ChatOrigin.OWN,
                  status: str = ChatStatus.APPROVED, owner: int | None = SUPER_ID, members: int = 1000,
                  **fields: Any) -> int:
    """A chat row written straight into the database (lists and screens)."""
    async with app.db() as s:
        chat = Chat(bot_id=bot_id, chat_id=chat_id, title=title, type=fields.pop("type", "channel"), origin=origin,
                    status=status, owner_user_id=owner, members=members, rights_ok=fields.pop("rights_ok", True),
                    **fields)
        if status == ChatStatus.APPROVED:
            chat.approved_at = utcnow() - timedelta(days=1)
        s.add(chat)
        await s.flush()
        return chat.id


async def make_group(app: App, name: str, *, open: bool = False, freq: dict[str, Any] | None = None,
                     bot_id: int = MAIN_BOT_ID) -> int:
    async with app.db() as s:
        group = ChatGroup(bot_id=bot_id, name=name, open=open, freq=freq)
        s.add(group)
        await s.flush()
        return group.id


async def events_of(app: App, kind: str | None = None, bot_id: int = MAIN_BOT_ID) -> list[Event]:
    async with app.db() as s:
        q = select(Event).where(Event.bot_id == bot_id)
        if kind:
            q = q.where(Event.kind == kind)
        return list((await s.execute(q.order_by(Event.id))).scalars())


def notices(app: App, user_id: int = SUPER_ID) -> list[Call]:
    return [c for c in app.fake.calls_of("sendMessage", chat_id=user_id)
            if "Solicitud para unirse a la red" in str(c.params.get("text"))]


def dms(app: App, user_id: int = USER_ID, token: str | None = None) -> list[str]:
    return [str(c.params.get("text")) for c in app.fake.calls_of("sendMessage", chat_id=user_id)
            if token is None or c.token == token]


def button(call: Call, contains: str) -> dict[str, Any]:
    for b in App.buttons(call):
        if contains in b["text"]:
            return b
    raise AssertionError(f"button {contains!r} not in {[b['text'] for b in App.buttons(call)]}")


def labels(call: Call) -> list[str]:
    return [b["text"] for b in App.buttons(call)]


def last_answer(app: App) -> dict[str, Any]:
    call = app.fake.last("answerCallbackQuery")
    assert call is not None
    return call.params


def is_alert(app: App, text: str) -> bool:
    answer = last_answer(app)
    return text in str(answer.get("text")) and str(answer.get("show_alert")).lower() == "true"


async def press_notice(app: App, contains: str, user_id: int = SUPER_ID) -> None:
    notice = notices(app, user_id)[-1]
    await app.press(user_id, button(notice, contains)["callback_data"], notice.result["message_id"])


def chat_message_update(app: App, chat: dict[str, Any], message_id: int, **fields: Any) -> dict[str, Any]:
    """A group message or a channel post with the given (service) fields."""
    msg: dict[str, Any] = {"message_id": message_id, "date": int(time.time()), "chat": chat, **fields}
    if chat["type"] == "channel":
        msg["sender_chat"] = chat
        return {"update_id": app.fake.new_update_id(), "channel_post": msg}
    msg.setdefault("from", app._user(USER_ID))  # noqa: SLF001
    return {"update_id": app.fake.new_update_id(), "message": msg}


class DropRecorder:
    """Stands in for ``Publisher.drop_chat``: records the chats and that the bot was still inside."""

    def __init__(self, app: App) -> None:
        self.app = app
        self.calls: list[int] = []
        self.left_before: list[bool] = []

    async def __call__(self, publisher: Any, chat_pk: int) -> int:
        self.calls.append(chat_pk)
        self.left_before.append(bool(self.app.fake.calls_of("leaveChat")))
        return 2


def record_drops(app: App, monkeypatch: pytest.MonkeyPatch) -> DropRecorder:
    rec = DropRecorder(app)

    async def drop_chat(publisher: Any, chat_pk: int) -> int:
        return await rec(publisher, chat_pk)

    monkeypatch.setattr("app.services.publisher.Publisher.drop_chat", drop_chat)
    return rec
