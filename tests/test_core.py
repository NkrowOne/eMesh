"""Core layer: rate limiter, FSM storage, manager, i18n, workspace context."""
from __future__ import annotations

import asyncio
import time

import pytest
from aiogram.fsm.storage.base import StorageKey

from app import i18n
from app.db.models import Bot as BotRecord
from app.db.models import BotStatus, BotUser
from app.telegram.context import Priority, request_priority
from app.telegram.ratelimit import RateLimitMiddleware, SlidingWindow, TokenBucket
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, App


def test_i18n_languages_have_same_keys() -> None:
    cat = i18n.catalog()
    missing = set(cat["es"]) - set(cat["en"])
    assert not missing, f"missing EN translations: {sorted(missing)[:20]}"
    extra = set(cat["en"]) - set(cat["es"])
    assert not extra, f"EN keys without ES: {sorted(extra)[:20]}"


def test_i18n_placeholders_match() -> None:
    import string

    cat = i18n.catalog()
    fmt = string.Formatter()
    for key, es in cat["es"].items():
        en = cat["en"].get(key)
        if en is None:
            continue
        es_f = {f for _, f, _, _ in fmt.parse(es) if f}
        en_f = {f for _, f, _, _ in fmt.parse(en) if f}
        assert es_f == en_f, f"placeholders differ for {key}: {es_f} vs {en_f}"


async def test_token_bucket_rate() -> None:
    bucket = TokenBucket(rate=50, capacity=5)
    start = time.monotonic()
    for _ in range(30):
        await bucket.acquire()
    assert time.monotonic() - start >= (30 - 5) / 50 * 0.9


async def test_sliding_window() -> None:
    win = SlidingWindow(limit=5, window=0.5)
    start = time.monotonic()
    for _ in range(10):
        await win.acquire()
    assert time.monotonic() - start >= 0.5


async def test_rate_limiter_retries_429(app: App) -> None:
    app.fake.fail("sendMessage", code=429, description="Too Many Requests: retry after 1", retry_after=1)
    start = time.monotonic()
    msg = await app.main_bot.send_message(SUPER_ID, "hola")
    assert msg.text == "hola"
    assert time.monotonic() - start >= 1.0
    assert len(app.fake.calls_of("sendMessage")) == 2


async def test_rate_limiter_global_30_per_second(app: App) -> None:
    """60 bulk messages to different users: never more than 30 per second (Telegram limit)."""
    from app.config import Settings

    app.fake.strict_limits = True
    app.fake.global_per_sec = 30
    app.fake.group_per_min = 10_000
    prod = Settings(_env_file=None, BOT_TOKEN="1:x")  # type: ignore[call-arg]
    mws = app.main_bot.session.middleware._middlewares  # noqa: SLF001
    for i, m in enumerate(mws):
        if isinstance(m, RateLimitMiddleware):
            mws[i] = RateLimitMiddleware(prod)
    for i in range(60):
        app.fake.add_user(10_000 + i)
    token = request_priority.set(Priority.LOW)
    try:
        start = time.monotonic()
        await asyncio.gather(*(app.main_bot.send_message(10_000 + i, "x") for i in range(60)))
    finally:
        request_priority.reset(token)
    assert app.fake.limit_violations == 0
    assert time.monotonic() - start >= 2.0  # bulk lane: ~20 msg/s


async def test_fsm_storage_persists(app: App) -> None:
    key = StorageKey(bot_id=MAIN_BOT_ID, chat_id=1, user_id=1)
    await app.storage.set_state(key, "Wizard:title")
    await app.storage.set_data(key, {"a": 1})
    await app.storage.flush()
    from app.telegram.fsm_storage import SQLStorage

    fresh = SQLStorage(app.sm)
    assert await fresh.get_state(key) == "Wizard:title"
    assert await fresh.get_data(key) == {"a": 1}


async def test_main_bot_registered(app: App) -> None:
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        assert rec is not None and rec.is_main and rec.owner_id == SUPER_ID
        assert app.manager.cipher.decrypt(rec.token_enc) == app.settings.BOT_TOKEN


async def test_start_answers(app: App) -> None:
    await app.send(SUPER_ID, "/start")
    assert app.panels(SUPER_ID), "the bot must answer /start"


async def test_send_is_not_retried_after_server_error(app: App) -> None:
    from aiogram.exceptions import TelegramServerError

    app.fake.fail("sendMessage", code=500, description="Internal Server Error")
    with pytest.raises(TelegramServerError):
        await app.main_bot.send_message(SUPER_ID, "hola")
    assert len(app.fake.calls_of("sendMessage")) == 1


async def test_pending_clone_is_stored_but_not_started(app: App) -> None:
    token = app.fake.add_bot(7_000_000_010, "pendiente_bot")
    rec = await app.manager.add_bot(token, owner_id=OWNER2_ID, pending=True)
    assert rec.status == BotStatus.PENDING and not app.manager.is_running(rec.id)
    assert await app.manager.enable_bot(rec.id)
    assert app.manager.is_running(rec.id)


async def test_workspace_banner_for_super_admin_managing_a_clone(app: App) -> None:
    await app.add_clone(7_000_000_011, "clon_cine_bot", OWNER2_ID)
    await app.send(SUPER_ID, "/start")
    async with app.db() as s:
        bu = await s.get(BotUser, (MAIN_BOT_ID, SUPER_ID))
        assert bu is not None
        bu.ws_bot_id = 7_000_000_011
    await app.send(SUPER_ID, "/start")
    assert "clon_cine_bot" in app.last_text(SUPER_ID)
    # a user that isn't a super admin never gets a workspace, even with the column set
    await app.send(OWNER2_ID, "/start")
    async with app.db() as s:
        bu2 = await s.get(BotUser, (MAIN_BOT_ID, OWNER2_ID))
        assert bu2 is not None
        bu2.ws_bot_id = 7_000_000_011
    await app.send(OWNER2_ID, "/start")
    assert "clon_cine_bot" not in app.last_text(OWNER2_ID)


def test_visible_len_counts_utf16_units() -> None:
    from app.ui.common import visible_len

    assert visible_len("<b>hola</b> &amp;") == 6
    assert visible_len("🦁") == 2
