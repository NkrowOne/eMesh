"""Review probes (chats): each test proves a defect and FAILS on the current code."""
from __future__ import annotations

import asyncio

import pytest

from app.bot.routers.chats import ChCB
from app.bot.routers.partners import PaCB
from app.db.base import utcnow
from app.db.models import ChatStatus
from app.services import chatstate
from app.ui.common import visible_len
from tests.conftest import MAIN_BOT_ID, SUPER_ID, USER_ID, App
from tests.test_chats_support import (  # noqa: F401  (reset_chat_caches is an autouse fixture)
    CHANNEL,
    GROUP,
    add_chat,
    get_chat,
    make_group,
    notices,
    partner_chat,
    record_drops,
    reset_chat_caches,
    set_bot,
    start,
)


async def test_probe_same_second_member_updates_are_applied_in_telegram_order(app: App) -> None:
    """Updates are handled concurrently (UPDATE_CONCURRENCY_PER_BOT): two my_chat_member updates of one chat in the
    same second (added as member, then promoted) can reach the lock in reverse order. Only ``date`` (1 s) orders
    them, so the older one is applied last and the approved chat is marked as missing its rights."""
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True, join_approval=False)
    app.fake.add_chat(GROUP, "Grupo de Pepe", type="supergroup", members=1200, creator=USER_ID)
    as_member = app.my_chat_member_update(GROUP, USER_ID, new="member")  # older (lower update_id)
    promoted = app.my_chat_member_update(GROUP, USER_ID, new="administrator", old="member")  # newer
    promoted["my_chat_member"]["date"] = as_member["my_chat_member"]["date"]
    assert as_member["update_id"] < promoted["update_id"]
    await app.feed(promoted)
    await app.feed(as_member)  # the older one reaches the handler last
    chat = await get_chat(app, GROUP)
    assert chat.status == ChatStatus.APPROVED
    assert chat.rights_ok, "an older update overwrote the newer state (missing: %s)" % chat.missing_rights


async def test_probe_chats_list_fits_in_a_telegram_message(app: App) -> None:
    """External chats join every open group and each list row names all its groups: 15 categories of ~30 chars
    and one page of partner chats exceed 4096 characters, so the 📣 list can't be shown at all."""
    await start(app, SUPER_ID, USER_ID)
    for i in range(15):
        await make_group(app, f"Categoría de películas número {i:02d}", open=True)
    await set_bot(app, join_open=True, join_approval=False)
    for i in range(10):
        await add_chat(app, CHANNEL - i, f"Canal de cine y series número {i:02d} de Pepe",
                       username=f"cine_series_{i:02d}")
    await app.press(SUPER_ID, ChCB(a="ls").pack())
    text = app.last_text(SUPER_ID)
    assert "Canal de cine y series número 00" in text
    assert visible_len(text) <= 4096, f"{visible_len(text)} characters: Telegram refuses the message"


async def test_probe_ban_survives_a_maintenance_refresh_in_flight(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    """The scheduler's chat refresh (engine) holds a stale row across its Telegram calls without the chats module's
    chat_lock, and chatstate.mark_left doesn't check the status: a ban committed meanwhile becomes ``left``, so the
    partner can add the bot again and the chat comes back."""
    record_drops(app, monkeypatch)
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await set_bot(app, join_open=True, join_approval=False)
    gate, entered = asyncio.Event(), asyncio.Event()
    real = chatstate.inspect_chat

    async def slow_inspect(bot, row, **kw):  # noqa: ANN001, ANN003, ANN202
        entered.set()
        await gate.wait()  # Telegram answering slowly
        return await real(bot, row, **kw)

    monkeypatch.setattr(chatstate, "inspect_chat", slow_inspect)
    refresh = asyncio.create_task(app.scheduler._refresh_chats(MAIN_BOT_ID, utcnow()))  # noqa: SLF001
    await asyncio.wait_for(entered.wait(), 5)
    await app.press(SUPER_ID, ChCB(a="bny", id=chat.id).pack())  # 🚫 ban while the refresh waits
    assert (await get_chat(app)).status == ChatStatus.BANNED
    gate.set()
    await refresh
    await add_chat(app)  # the partner adds the bot again
    status = (await get_chat(app)).status
    assert status == ChatStatus.BANNED, f"the banned chat came back ({status})"


async def test_probe_request_notices_closed_when_maintenance_finds_the_chat_gone(app: App) -> None:
    """The scheduler refreshes pending chats too (engine): one found gone becomes ``left`` but its admin notices keep
    their live ✅/❌ buttons, and when the partner adds the bot again ``request()`` sees those stale notices and
    sends nothing (no new notice, no DM, no event)."""
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True)
    await add_chat(app)
    assert len(notices(app)) == 1
    app.fake.chats[CHANNEL].bot_admin.pop(MAIN_BOT_ID)  # removed while its update was lost (bot down > 24 h)
    await app.scheduler._refresh_chats(MAIN_BOT_ID, utcnow())  # noqa: SLF001
    assert (await get_chat(app)).status == ChatStatus.LEFT
    stale = not app.fake.calls_of("editMessageReplyMarkup", chat_id=SUPER_ID)
    await add_chat(app, old="left")  # the partner adds the bot again: a new request
    assert (await get_chat(app)).status == ChatStatus.PENDING
    assert len(notices(app)) == 2 and not stale, f"no new notice (old one left live: {stale})"


async def test_probe_partner_cant_lift_an_admin_pause_by_leaving_and_coming_back(
        app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    """Partners can't resume an admin's pause (spec 4): leaving from their panel and adding the bot again does."""
    record_drops(app, monkeypatch)
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await set_bot(app, join_open=True, join_approval=False)
    await app.press(SUPER_ID, ChCB(a="pz", id=chat.id).pack())  # ⏸ admin pause
    assert (await get_chat(app)).admin_paused

    await app.press(USER_ID, PaCB(a="lvy", id=chat.id).pack())  # 🚪 Salir de la red
    assert (await get_chat(app)).status == ChatStatus.LEFT
    await add_chat(app)  # ... and the partner adds the bot again
    chat = await get_chat(app)
    assert chat.status == ChatStatus.APPROVED
    assert chat.admin_paused, "the admin's pause was lifted by the partner"
