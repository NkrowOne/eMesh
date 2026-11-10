"""Engine: the scheduler (own-schedule and one-time posts, groups of chats as targets, late posts, paused networks, hub
mode, pauses that end, chat refresh, daily summary, cleanup, the loop)."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import (
    Chat,
    ChatGroup,
    ChatOrigin,
    ChatStatus,
    Delivery,
    DeliveryStatus,
    Event,
    EventKind,
    GroupChat,
    Post,
    PostStatus,
    Role,
    Run,
    RunKind,
    RunStatus,
    SchedMode,
)
from app.services import content, freq
from app.services.scheduler import Scheduler
from app.ui.fmt import zone
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_engine import (
    CLONE_ID,
    chat_id_of,
    deliveries,
    dm_texts,
    events_of,
    get,
    make_chats,
    make_post,
    start_user,
    texts_in,
)

TZ = "Europe/Madrid"
HOURLY = {"mode": "interval", "every": 60, "window": "", "days": "0123456"}


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """No chat refresh nor daily summary in the ticks of a test (they have their own tests)."""
    monkeypatch.setattr(Scheduler, "_refresh_chats", AsyncMock())
    monkeypatch.setattr(Scheduler, "_summary", AsyncMock())


async def post_due(app: App, post_id: int, *, minutes: int = 1) -> None:
    async with app.db() as s:
        (await s.get(Post, post_id)).next_send_at = utcnow() - timedelta(minutes=minutes)


async def all_runs(app: App) -> list[Run]:
    async with app.db() as s:
        return list((await s.execute(select(Run).order_by(Run.id))).scalars())


# ------------------------------------------------------- own and one-time posts
async def test_an_own_post_without_next_time_gets_it_and_goes_out_on_time(app: App, quiet: None,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    await make_chats(app, 2)
    own = await make_post(app, freq=dict(HOURLY))  # no next time yet (e.g. a post converted by a migration)
    assert (await get(app, Post, own)).next_send_at is None
    await app.scheduler.tick()
    due = (await get(app, Post, own)).next_send_at
    assert utcnow() < due <= utcnow() + timedelta(minutes=61)
    assert not app.fake.calls_of("sendMessage") and await all_runs(app) == []

    monkeypatch.setattr("app.services.scheduler.utcnow", lambda: due + timedelta(seconds=30))
    await app.scheduler.tick()
    [run] = await all_runs(app)
    assert (run.post_id, run.kind, run.sent) == (own, RunKind.SCHEDULE, 2)
    assert (await get(app, Post, own)).next_send_at == due + timedelta(hours=1)


async def test_an_own_post_aimed_at_a_group_of_chats_goes_to_its_chats(app: App, quiet: None) -> None:
    a, b, c = await make_chats(app, 3)
    async with app.db() as s:
        cine = ChatGroup(bot_id=MAIN_BOT_ID, name="Cine", sort=0)
        s.add(cine)
        await s.flush()
        s.add_all([GroupChat(group_id=cine.id, chat_pk=a), GroupChat(group_id=cine.id, chat_pk=b)])
        cine_id = cine.id
    post_id = await make_post(app, targets=[f"g{cine_id}"], freq=dict(HOURLY),
                              next_send_at=utcnow() - timedelta(minutes=1))
    cids = [await chat_id_of(app, pk) for pk in (a, b, c)]
    await app.scheduler.tick()
    assert [len(texts_in(app, cid)) for cid in cids] == [1, 1, 0]
    [run] = await all_runs(app)
    assert (run.post_id, run.kind, run.sent) == (post_id, RunKind.SCHEDULE, 2)


async def test_late_posts_are_skipped_not_sent_late(app: App, quiet: None) -> None:
    await make_chats(app)
    late = utcnow() - timedelta(hours=2)
    own = await make_post(app, name="Propio", mode=SchedMode.OWN, freq=dict(HOURLY), next_send_at=late)
    once = await make_post(app, name="Una vez", mode=SchedMode.ONCE, send_at=late, next_send_at=late)
    await app.scheduler.tick()
    assert not app.fake.calls_of("sendMessage") and await all_runs(app) == []
    p = await get(app, Post, own)
    assert p.status == PostStatus.ACTIVE and p.next_send_at > utcnow()
    p = await get(app, Post, once)
    assert (p.status, p.next_send_at, p.runs_count) == (PostStatus.DONE, None, 0)


async def test_own_frequency_post_goes_to_its_audience_and_is_rescheduled(app: App, quiet: None) -> None:
    pks = await make_chats(app, 2)
    own = await make_post(app, name="Propio", mode=SchedMode.OWN, freq={**HOURLY, "every": 120},
                          next_send_at=utcnow() - timedelta(minutes=1))
    await app.scheduler.tick()
    [run] = await all_runs(app)
    assert (run.post_id, run.kind, run.sent) == (own, RunKind.SCHEDULE, 2)
    post = await get(app, Post, own)
    assert post.status == PostStatus.ACTIVE and post.runs_count == 1
    assert utcnow() < post.next_send_at <= utcnow() + timedelta(minutes=121)
    assert (await get(app, Chat, pks[0])).posts_total == 1
    await app.scheduler.tick()
    assert len(await all_runs(app)) == 1


async def test_a_one_time_post_is_done_after_its_run(app: App, quiet: None) -> None:
    await make_chats(app, 2)
    when = utcnow() - timedelta(minutes=1)
    once = await make_post(app, name="Una vez", mode=SchedMode.ONCE, send_at=when, next_send_at=when)
    await app.scheduler.tick()
    [run] = await all_runs(app)
    assert (run.post_id, run.kind, run.sent) == (once, RunKind.ONCE, 2)
    post = await get(app, Post, once)
    assert (post.status, post.next_send_at, post.runs_count) == (PostStatus.DONE, None, 1)
    await app.scheduler.tick()
    assert len(await all_runs(app)) == 1


async def test_a_campaign_that_ended_is_done(app: App, quiet: None) -> None:
    today = utcnow().astimezone(zone(TZ)).date()
    over = await make_post(app, name="Pasada", ends_on=today - timedelta(days=1))
    current = await make_post(app, name="Vigente", ends_on=today)
    await app.scheduler.tick()
    assert (await get(app, Post, over)).status == PostStatus.DONE
    assert (await get(app, Post, current)).status == PostStatus.ACTIVE


# ----------------------------------------------------------- paused / hub
async def test_a_paused_network_sends_nothing_but_still_deletes_and_ends_pauses(app: App, quiet: None) -> None:
    [pk, ext] = await make_chats(app, 2)
    post_id = await make_post(app, delete_after=60)
    run_id = await app.publisher.run(post_id, [pk], kind=RunKind.MANUAL, wait=True)
    async with app.db() as s:
        d = (await s.execute(select(Delivery).where(Delivery.run_id == run_id))).scalar_one()
        d.delete_at = utcnow() - timedelta(seconds=5)
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        rec.paused = True
        chat = await s.get(Chat, ext)
        chat.owner_paused, chat.owner_paused_until = True, utcnow() - timedelta(minutes=1)
    due = await make_post(app, name="Propio", mode=SchedMode.OWN, freq=dict(HOURLY),
                          next_send_at=utcnow() - timedelta(minutes=1))
    app.fake.reset_calls()
    await app.scheduler.tick()
    assert not app.fake.calls_of("sendMessage")
    assert app.fake.calls_of("deleteMessage", chat_id=await chat_id_of(app, pk))
    assert (await deliveries(app, run_id))[0].status == DeliveryStatus.DELETED
    assert len(await all_runs(app)) == 1
    assert (await get(app, Post, due)).next_send_at < utcnow()  # left for when it is resumed
    assert not (await get(app, Chat, ext)).owner_paused


async def test_a_hub_main_bot_runs_no_network(app: App, quiet: None) -> None:
    app.settings.MAIN_BOT_MODE = "hub"
    await make_chats(app)
    post_id = await make_post(app, freq=dict(HOURLY), next_send_at=utcnow() - timedelta(minutes=1))
    await app.scheduler.tick()
    assert not app.fake.calls_of("sendMessage")
    assert (await get(app, Post, post_id)).next_send_at < utcnow()


async def test_a_slow_bot_never_delays_the_others(app: App, quiet: None, monkeypatch: pytest.MonkeyPatch) -> None:
    await app.add_clone(CLONE_ID, "clon_cine_bot", OWNER2_ID)
    [mine] = await make_chats(app)
    [theirs] = await make_chats(app, bot_id=CLONE_ID)
    for bot_id in (MAIN_BOT_ID, CLONE_ID):
        await make_post(app, bot_id=bot_id, freq=dict(HOURLY), next_send_at=utcnow() - timedelta(minutes=1))
    main_cid, clone_cid = await chat_id_of(app, mine), await chat_id_of(app, theirs)
    gate = asyncio.Event()
    deliver = content.deliver

    async def held(bot: Any, *args: Any, **kwargs: Any) -> Any:
        if bot.id == CLONE_ID:
            await gate.wait()
        return await deliver(bot, *args, **kwargs)

    monkeypatch.setattr("app.services.publisher.content.deliver", held)
    await app.scheduler.tick(wait=False)
    await app.wait_for(lambda: app.fake.messages_to(main_cid))  # the main bot sends while the clone is stuck
    assert not app.fake.messages_to(clone_cid)
    await app.scheduler.tick(wait=False)  # the clone's job is still running: it isn't started twice
    gate.set()
    await app.scheduler.tick()
    assert len(app.fake.messages_to(clone_cid)) == 1 and len(app.fake.messages_to(main_cid)) == 1


# ------------------------------------------------------------- owner pauses
async def test_an_owner_pause_that_ended_is_cleared_and_told(app: App, quiet: None) -> None:
    await start_user(app, SUPER_ID)
    await start_user(app, USER_ID)
    ended, ongoing = await make_chats(app, 2, origin=ChatOrigin.EXTERNAL, owner=USER_ID, title="Series")
    now = utcnow()
    async with app.db() as s:
        for pk, until in ((ended, now - timedelta(minutes=1)), (ongoing, now + timedelta(hours=1))):
            chat = await s.get(Chat, pk)
            chat.owner_paused, chat.owner_paused_until, chat.paused_at = True, until, now - timedelta(hours=2)
    await app.scheduler.tick()
    chat = await get(app, Chat, ended)
    assert (chat.owner_paused, chat.owner_paused_until, chat.paused_at) == (False, None, None)
    assert (await get(app, Chat, ongoing)).owner_paused
    [ev] = await events_of(app, EventKind.CHAT_RESUMED)
    assert (ev.chat_pk, ev.data) == (ended, {"by": "auto"})
    assert any("<b>Series 1</b>: la pausa ha terminado" in x for x in dm_texts(app, SUPER_ID))
    assert dm_texts(app, USER_ID) == [
        "▶️ La pausa de tu canal <b>Series 1</b> ha terminado: vuelve a recibir los mensajes de la red."]
    await app.scheduler.tick()
    assert len(await events_of(app, EventKind.CHAT_RESUMED)) == 1


# -------------------------------------------------------------- maintenance
async def test_chats_are_refreshed_once_per_interval(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Scheduler, "_summary", AsyncMock())
    ok, gone, pending = await make_chats(app, 3, members=100)
    async with app.db() as s:
        (await s.get(Chat, pending)).status = ChatStatus.PENDING
    app.fake.chats[await chat_id_of(app, ok)].members = 2500
    app.fake.chats[await chat_id_of(app, gone)].bot_admin.pop(MAIN_BOT_ID)
    await app.scheduler.tick()
    assert (await get(app, Chat, ok)).members == 2500
    assert (await get(app, Chat, gone)).status == ChatStatus.LEFT
    still = await get(app, Chat, pending)
    assert (still.status, still.checked_at is not None) == (ChatStatus.PENDING, True)
    checks = len(app.fake.calls_of("getChat"))
    assert checks == 3
    await app.scheduler.tick()
    assert len(app.fake.calls_of("getChat")) == checks  # not again before MAINTENANCE_INTERVAL_HOURS


async def test_daily_summary_is_sent_once(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Scheduler, "_refresh_chats", AsyncMock())
    app.settings.SUMMARY_HOUR = 0
    await start_user(app, SUPER_ID)
    await start_user(app, OWNER2_ID, role=Role.ADMIN, summary=False)
    await make_chats(app, 2, members=2000)
    today = utcnow().astimezone(zone(TZ)).date()
    yesterday = today - timedelta(days=1)
    async with app.db() as s:
        for day, sent in ((yesterday, 10), (today - timedelta(days=3), 99)):
            s.add(Run(bot_id=MAIN_BOT_ID, post_name="Promo", kind=RunKind.SCHEDULE, status=RunStatus.DONE, total=12,
                      sent=sent, failed=2, skipped=1, reach=20_000,
                      started_at=freq.day_start(day, TZ) + timedelta(hours=10)))
    await app.scheduler.tick()
    await app.scheduler.tick()
    [summary] = [x for x in dm_texts(app, SUPER_ID) if "Resumen diario" in x]
    assert summary.startswith(f"📋 <b>Resumen diario</b> · @emesh_test_bot\n📅 {yesterday.strftime('%d/%m/%Y')}")
    for line in ("📤 Envíos: <b>1</b>", "✅ Entregados: <b>10</b>", "❌ Fallidos: <b>2</b>",
                 "🛡 Omitidos por anti-spam: <b>1</b>", "👁 Alcance: <b>20,000</b>", "📣 Chats: <b>2</b> · 👤 4,000"):
        assert line in summary
    assert not dm_texts(app, OWNER2_ID)  # summary off


async def test_cleanup_deletes_old_runs_and_activity(app: App, quiet: None) -> None:
    [pk] = await make_chats(app)
    post_id = await make_post(app)
    now = utcnow()
    old = now - timedelta(days=40)
    async with app.db() as s:
        chat_id = (await s.get(Chat, pk)).chat_id
        runs = [Run(bot_id=MAIN_BOT_ID, post_id=post_id, post_name="Promo", kind=RunKind.MANUAL, status=RunStatus.DONE,
                    started_at=started) for started in (old, old, now - timedelta(days=1))]
        s.add_all(runs)
        await s.flush()
        expired, waiting, recent = (r.id for r in runs)
        common = dict(bot_id=MAIN_BOT_ID, post_id=post_id, chat_pk=pk, chat_id=chat_id)
        s.add_all([
            Delivery(run_id=expired, status=DeliveryStatus.DELETED, sent_at=old, **common),
            # still waiting for its auto delete: kept with its run
            Delivery(run_id=waiting, status=DeliveryStatus.SENT, message_id=9, sent_at=now - timedelta(hours=1),
                     delete_at=now + timedelta(hours=1), **common),
            Delivery(run_id=recent, status=DeliveryStatus.SENT, sent_at=now - timedelta(days=1), **common),
            Event(bot_id=MAIN_BOT_ID, kind=EventKind.CHAT_ADDED, created_at=old),
            Event(bot_id=MAIN_BOT_ID, kind=EventKind.CHAT_ADDED, created_at=now),
        ])
    await app.scheduler.tick()
    assert [r.id for r in await all_runs(app)] == [waiting, recent]
    assert await deliveries(app, expired) == []
    async with app.db() as s:
        assert len((await s.execute(select(Event))).scalars().all()) == 1


async def test_a_run_whose_task_died_goes_on(app: App, quiet: None) -> None:
    pks = await make_chats(app, 2)
    post_id = await make_post(app)
    async with app.db() as s:
        run = Run(bot_id=MAIN_BOT_ID, post_id=post_id, post_name="Promo Cine", kind=RunKind.MANUAL,
                  status=RunStatus.SENDING, total=2, started_at=utcnow() - timedelta(minutes=1))
        s.add(run)
        await s.flush()
        run_id = run.id
        for pk in pks:
            s.add(Delivery(run_id=run_id, bot_id=MAIN_BOT_ID, post_id=post_id, chat_pk=pk,
                           chat_id=(await s.get(Chat, pk)).chat_id, status=DeliveryStatus.QUEUED))
    await app.scheduler.tick()
    await app.publisher.wait_idle(10)
    run = await get(app, Run, run_id)
    assert (run.status, run.sent) == (RunStatus.DONE, 2)
    assert [d.status for d in await deliveries(app, run_id)] == [DeliveryStatus.SENT] * 2


# ---------------------------------------------------------------------- loop
async def test_the_loop_ticks_and_wakes_up(app: App, quiet: None) -> None:
    app.settings.SCHEDULER_TICK_SECONDS = 3600  # only wake() can trigger the next tick
    [pk] = await make_chats(app)
    post_id = await make_post(app, freq=dict(HOURLY))
    cid = await chat_id_of(app, pk)

    async def next_time_known() -> bool:
        return (await get(app, Post, post_id)).next_send_at is not None

    await app.scheduler.start()
    await app.wait_for(next_time_known)  # the first tick ran
    await app.wait_for(lambda: not app.scheduler._jobs)  # noqa: SLF001
    await post_due(app, post_id)
    app.scheduler.wake()
    await app.wait_for(lambda: app.fake.messages_to(cid))
    await app.scheduler.stop()
    assert len(await all_runs(app)) == 1
