"""Review probes for the engine (publisher, scheduler, freq, manager): each test shows a defect found in review and
fails until it is fixed."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import BotStatus, Delivery, DeliveryStatus, Post, RunKind
from app.services import content, freq
from app.services.publisher import delete_time
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, App
from tests.test_engine import CLONE_ID, chat_id_of, deliveries, get, make_chats, make_post, run_post, set_bot, \
    texts_in


def hold_deliver(monkeypatch: pytest.MonkeyPatch) -> tuple[asyncio.Event, asyncio.Event]:
    """``content.deliver`` waits for ``gate``; ``started`` is set when the first send is out."""
    gate, started = asyncio.Event(), asyncio.Event()
    deliver = content.deliver

    async def held(*args: Any, **kwargs: Any) -> Any:
        started.set()
        await gate.wait()
        return await deliver(*args, **kwargs)

    monkeypatch.setattr("app.services.publisher.content.deliver", held)
    return gate, started


async def test_review_auto_delete_of_48_h_is_really_done(app: App) -> None:
    """🗑 48 h (the longest auto delete offered) is scheduled 5 minutes before Telegram's limit (MAX_DELETE_AGE), but
    ``_delete_message`` treats anything older than that same mark as expired: the message is never deleted."""
    [pk] = await make_chats(app)
    post_id = await make_post(app, delete_after=2880)
    run_id = await run_post(app, post_id, [pk])
    [d] = await deliveries(app, run_id)
    async with app.db() as s:  # time goes by: the scheduler's tick comes a few seconds after delete_at
        row = (await s.execute(select(Delivery).where(Delivery.id == d.id))).scalar_one()
        row.sent_at = utcnow() - timedelta(hours=47, minutes=55, seconds=10)
        row.delete_at = delete_time(row.sent_at, 2880)
        assert row.delete_at <= utcnow() and utcnow() - row.sent_at < timedelta(hours=48)
    await app.publisher.delete_due()
    [d] = await deliveries(app, run_id)
    assert app.fake.calls_of("deleteMessage", chat_id=d.chat_id), f"deleteMessage never called ({d.status})"
    assert d.status == DeliveryStatus.DELETED
    assert not app.fake.chats[d.chat_id].messages


async def test_review_media_changed_during_an_upload_is_not_mixed_up(app: App,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """A clone uploads the media of a post the main bot received; if the post's media is changed while that first
    upload is in flight, ``remember_media`` merges the OLD file's id for the clone into the NEW media dict: from
    then on the clone keeps sending the old picture (the main bot's preview shows the new one)."""
    await app.add_clone(CLONE_ID, "clon_cine_bot", OWNER2_ID)
    pks = await make_chats(app, 2, bot_id=CLONE_ID)
    app.fake.files["PHOTO_OLD"] = b"old picture"
    app.fake.files["PHOTO_NEW"] = b"new picture"
    post_id = await make_post(app, bot_id=CLONE_ID, kind="photo", text="Cartel",
                              media={str(MAIN_BOT_ID): "PHOTO_OLD"})
    deliver = content.deliver
    gate, started = hold_deliver(monkeypatch)
    assert await app.publisher.send_now(post_id) is not None
    await asyncio.wait_for(started.wait(), 5)
    async with app.db() as s:  # ✏️ Cambiar el mensaje (content.apply with the main bot, managing the clone)
        post = await s.get(Post, post_id)
        content.apply(post, content.Content("photo", "Cartel nuevo", "PHOTO_NEW"), MAIN_BOT_ID)
    gate.set()
    await app.publisher.wait_idle(10)
    monkeypatch.setattr("app.services.publisher.content.deliver", deliver)

    media = (await get(app, Post, post_id)).media  # buggy: {main: PHOTO_NEW, clone: upl1 (= the old picture)}
    app.fake.reset_calls()
    await run_post(app, post_id, pks)  # the next run of the clone must carry the new picture
    sent = app.fake.calls_of("sendPhoto")[-1].params["photo"]
    assert app.fake.files.get(sent) == b"new picture", (media, sent, app.fake.files.get(sent))


async def test_review_pausing_the_network_stops_a_run_in_progress(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    """⏸ Pausar todo: «no se enviará nada hasta que la reanudes». A run in progress (e.g. a post to thousands of
    chats) re-checks the chats' own pauses before every batch, but never ``Bot.paused``: it goes on to every chat."""
    monkeypatch.setattr("app.services.publisher.BATCH_SIZE", 1)
    pks = await make_chats(app, 3)
    cids = [await chat_id_of(app, pk) for pk in pks]
    post_id = await make_post(app)
    gate, started = hold_deliver(monkeypatch)
    assert await app.publisher.run(post_id, pks, kind=RunKind.SCHEDULE) is not None
    await asyncio.wait_for(started.wait(), 5)  # the first chat's batch is out
    await set_bot(app, paused=True)  # the owner presses ⏸ Pausar todo
    gate.set()
    await app.publisher.wait_idle(10)
    assert [len(texts_in(app, cid)) for cid in cids] == [1, 0, 0]


async def test_review_a_post_is_not_sent_twice_after_long_half_done_runs(app: App,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """``_sends`` first resumes the half-done runs (``wait``: minutes in a big network). The posts after them must be
    claimed with a fresh ``now``: with the old one their next time can already be past, so the next tick sends the
    same post again right away."""
    real_now = utcnow()
    [pk] = await make_chats(app)
    post_id = await make_post(app, freq={"mode": "interval", "every": 10, "window": "", "days": "0123456"},
                              next_send_at=real_now - timedelta(minutes=21))
    cid = await chat_id_of(app, pk)
    # The tick starts 20 minutes ago and the half-done runs (a big network) take those 20 minutes.
    clock = {"now": real_now - timedelta(minutes=20)}
    monkeypatch.setattr("app.services.scheduler.utcnow", lambda: clock["now"])

    async def long_resume(bot_id: int) -> None:
        clock["now"] = real_now

    monkeypatch.setattr(app.publisher, "resume_bot", long_resume)
    await app.scheduler._sends(MAIN_BOT_ID)  # noqa: SLF001
    assert len(texts_in(app, cid)) == 1
    monkeypatch.setattr("app.services.scheduler.utcnow", utcnow)
    await app.scheduler._sends(MAIN_BOT_ID)  # noqa: SLF001 - the very next tick
    nxt = (await get(app, Post, post_id)).next_send_at
    assert len(texts_in(app, cid)) == 1, f"sent again at once (next time {nxt}, now {utcnow()})"


def test_review_next_slot_never_skips_a_slot_on_the_dst_change() -> None:
    """Spring forward in Madrid (02:00 → 03:00): "02:30" doesn't exist and maps to 01:30 UTC, after 03:15 CEST
    (01:15 UTC). ``next_slot`` returns the first slot in wall-clock order, so the 03:15 slot is never sent."""
    f = {"mode": "times", "times": "02:30,03:15", "days": "0123456"}
    tz = "Europe/Madrid"
    s315 = datetime(2027, 3, 28, 3, 15, tzinfo=freq.zone(tz)).astimezone(timezone.utc)
    slots = freq.upcoming(f, tz, datetime(2027, 3, 28, 0, 0, tzinfo=timezone.utc), 2)
    assert s315 in slots, slots


async def test_review_enable_while_the_disable_still_withdraws_leaves_the_bot_running(
        app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    """disable_bot() withdraws the clone's posts (up to 60 s) before dropping it. An enable_bot() meanwhile (e.g. the
    super admin's ▶️ Activar in 👑 Panel) sets it ACTIVE, but start_bot() returns at once because the bot is still in
    ``manager.bots``; then the stop drops it: ACTIVE in the database, not running until a restart."""
    await app.add_clone(CLONE_ID, "clon_cine_bot", OWNER2_ID)
    gate, started = asyncio.Event(), asyncio.Event()
    withdraw = app.publisher.withdraw_bot

    async def slow_withdraw(bot_id: int, *, timeout: float | None = None) -> int:  # many auto deletes to do
        started.set()
        await gate.wait()
        return await withdraw(bot_id, timeout=timeout)

    monkeypatch.setattr(app.publisher, "withdraw_bot", slow_withdraw)
    disabling = asyncio.create_task(app.manager.disable_bot(CLONE_ID, "owner"))
    await asyncio.wait_for(started.wait(), 5)
    assert await app.manager.enable_bot(CLONE_ID)  # reported as activated
    gate.set()
    await disabling
    assert (await get(app, BotRecord, CLONE_ID)).status == BotStatus.ACTIVE
    assert app.manager.is_running(CLONE_ID), "ACTIVE in the database but stopped"
