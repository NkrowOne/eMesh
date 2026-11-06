"""Chats and clones after the third review: what the probes don't pin down (tests/test_*_review3.py)."""
from __future__ import annotations

import pytest

from app.bot.routers.chats import ChCB
from app.bot.routers.partners import PaCB
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import BotStatus, Chat, ChatStatus, EventKind
from app.services import chatstate
from app.services.chats import RqCB
from tests.conftest import MAIN_BOT_ID, SUPER_ID, USER_ID, App
from tests.test_chats_support import (  # noqa: F401  (reset_chat_caches is an autouse fixture)
    CHANNEL,
    add_chat,
    button,
    events_of,
    get_chat,
    is_alert,
    make_group,
    notices,
    partner_chat,
    record_drops,
    reset_chat_caches,
    set_bot,
    start,
)
from tests.test_clone import get_bot, managed_update, set_policy


async def test_pending_managed_bot_stays_pending_when_the_platform_opens(app: App) -> None:
    await set_policy(app, "approval")
    new_id = 6_100_000_779
    app.fake.managed_tokens[new_id] = app.fake.add_bot(new_id, "pepe_mesh_bot")
    await app.feed(managed_update(app, USER_ID, new_id))
    assert (await get_bot(app, new_id)).status == BotStatus.PENDING

    await set_policy(app, "open")
    await app.feed(managed_update(app, USER_ID, new_id))  # a new token of the bot still waiting
    rec = await get_bot(app, new_id)
    assert rec.status == BotStatus.PENDING and not app.manager.is_running(new_id)


async def test_partner_leaving_clears_only_their_own_pause(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    record_drops(app, monkeypatch)
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await app.press(SUPER_ID, ChCB(a="pz", id=chat.id).pack())
    await app.press(USER_ID, PaCB(a="pz", id=chat.id, v=1).pack())
    await app.press(USER_ID, PaCB(a="lvy", id=chat.id).pack())
    chat = await get_chat(app)
    assert chat.status == ChatStatus.LEFT
    assert not chat.owner_paused and chat.owner_paused_until is None
    assert chat.admin_paused and chat.paused_at is not None


async def test_mark_left_keeps_a_decision_taken_meanwhile(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await partner_chat(app)
    async with app.db() as s:
        chat = await s.get(Chat, (await get_chat(app)).id)  # read before the decision
        async with app.db() as other:
            (await other.get(Chat, chat.id)).status = ChatStatus.REJECTED
        ws = await s.get(BotRecord, MAIN_BOT_ID)
        assert not await chatstate.mark_left(app.main_bot, s, ws, chat)
        assert chat.status == ChatStatus.REJECTED
    assert (await get_chat(app)).status == ChatStatus.REJECTED
    assert not await events_of(app, EventKind.CHAT_LEFT)


async def test_old_notice_of_a_chat_found_gone_is_settled(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True)
    await add_chat(app)
    [notice] = notices(app)
    app.fake.chats[CHANNEL].bot_admin.pop(MAIN_BOT_ID)
    await app.scheduler._refresh_chats(MAIN_BOT_ID, utcnow())  # noqa: SLF001
    [closed] = [c for c in app.fake.calls_of("editMessageReplyMarkup", chat_id=SUPER_ID)
                if c.params["message_id"] == notice.result["message_id"]]
    assert closed.params["reply_markup"]["inline_keyboard"][0][0]["text"] == "🚪 El bot ya no está en el chat"

    await app.press(SUPER_ID, button(notice, "Aceptar")["callback_data"], notice.result["message_id"])
    assert is_alert(app, "Esta solicitud ya está resuelta")
    assert (await get_chat(app)).status == ChatStatus.LEFT
    await app.press(SUPER_ID, RqCB(a="nr", pk=(await get_chat(app)).id).pack())
    assert is_alert(app, "Esta solicitud ya está resuelta")
    assert (await get_chat(app)).status == ChatStatus.LEFT


async def test_long_lists_of_groups_are_cut(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    names = [f"Categoría {i:02d}" for i in range(12)]
    for name in names:
        await make_group(app, name, open=True)
    chat = await partner_chat(app)  # an external chat joins every open group

    await app.press(SUPER_ID, ChCB(a="ls").pack())
    assert "🗂 Categoría 00, Categoría 01 +10" in app.last_text(SUPER_ID)
    await app.press(SUPER_ID, ChCB(a="op", id=chat.id).pack())
    assert f"🗂 Grupos de canales: {', '.join(names[:10])} +2\n" in app.last_text(SUPER_ID)
    await app.press(USER_ID, PaCB(a="op", id=chat.id).pack())
    assert f"🗂 Categorías: {', '.join(names[:10])} +2" in app.last_text(USER_ID)
