"""Engine: the publisher (runs, anti-spam, deletions, errors of the chats, media across bots, resume, reports)."""
from __future__ import annotations

import asyncio
import itertools
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import (
    BotUser,
    Chat,
    ChatOrigin,
    ChatStatus,
    ChatType,
    Delivery,
    DeliveryStatus,
    Event,
    EventKind,
    Post,
    PostStatus,
    Role,
    Run,
    RunKind,
    RunStatus,
    SchedMode,
    User,
)
from app.services import content
from app.services.publisher import live_count
from app.telegram.ratelimit import RateLimitMiddleware
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.fake_tg import ADMIN_RIGHTS_FULL

CLONE_ID = 7_000_000_020
_chat_ids = itertools.count(1)


# ------------------------------------------------------------------ helpers
async def make_chats(app: App, n: int = 1, *, bot_id: int = MAIN_BOT_ID, type: str = ChatType.CHANNEL,
                     members: int = 1000, origin: str = ChatOrigin.OWN, owner: int | None = None,
                     title: str = "Canal de Cine") -> list[int]:
    """``n`` approved chats of a bot (in the fake world, with the bot as admin, and in the DB). Returns their pks."""
    pks: list[int] = []
    async with app.db() as s:
        for i in range(n):
            chat_id = -100_500_000 - next(_chat_ids)
            name = f"{title} {i + 1}" if n > 1 else title
            app.fake.add_chat(chat_id, name, type="channel" if type == ChatType.CHANNEL else "supergroup",
                              members=members, admin_bots={bot_id: "full"}, creator=owner)
            chat = Chat(bot_id=bot_id, chat_id=chat_id, type=type, title=name, members=members, origin=origin,
                        owner_user_id=owner, status=ChatStatus.APPROVED, rights_ok=True, approved_at=utcnow())
            s.add(chat)
            await s.flush()
            pks.append(chat.id)
    return pks


async def make_post(app: App, *, bot_id: int = MAIN_BOT_ID, name: str = "Promo Cine",
                    text: str = "🎬 <b>Estreno</b> esta semana", **kw: Any) -> int:
    values: dict[str, Any] = dict(bot_id=bot_id, name=name, kind="text", text=text, media={}, buttons=[],
                                  targets=["all"], mode=SchedMode.ROTATION, status=PostStatus.ACTIVE,
                                  delete_previous=False)
    values.update(kw)
    async with app.db() as s:
        post = Post(**values)
        s.add(post)
        await s.flush()
        return post.id


async def start_user(app: App, uid: int, *, bot_id: int = MAIN_BOT_ID, role: str = Role.USER, **flags: Any) -> None:
    """``uid`` started the bot (a ``BotUser`` row), with these flags (notify, summary, run_reports...)."""
    async with app.db() as s:
        if await s.get(User, uid) is None:
            s.add(User(id=uid, first_name=f"U{uid}", username=f"user{uid}"))
            await s.flush()
        bu = await s.get(BotUser, (bot_id, uid))
        if bu is None:
            bu = BotUser(bot_id=bot_id, user_id=uid)
            s.add(bu)
        bu.role = role
        for key, value in flags.items():
            setattr(bu, key, value)


async def set_bot(app: App, bot_id: int = MAIN_BOT_ID, **values: Any) -> None:
    async with app.db() as s:
        rec = await s.get(BotRecord, bot_id)
        assert rec is not None
        for key, value in values.items():
            setattr(rec, key, value)


async def get(app: App, model: Any, pk: Any) -> Any:
    async with app.db() as s:
        return await s.get(model, pk)


async def chat_id_of(app: App, pk: int) -> int:
    return (await get(app, Chat, pk)).chat_id


async def deliveries(app: App, run_id: int) -> list[Delivery]:
    async with app.db() as s:
        return list((await s.execute(select(Delivery).where(Delivery.run_id == run_id).order_by(Delivery.id)))
                    .scalars())


async def events_of(app: App, kind: str) -> list[Event]:
    async with app.db() as s:
        return list((await s.execute(select(Event).where(Event.kind == kind).order_by(Event.id))).scalars())


def dm_texts(app: App, uid: int) -> list[str]:
    return [str(c.params.get("text", "")) for c in app.fake.calls_of("sendMessage", chat_id=uid)]


def texts_in(app: App, chat_id: int) -> list[str]:
    """What the bots sent to a chat, oldest first."""
    return [str(c.params.get("text") or c.params.get("caption") or "") for c in app.fake.messages_to(chat_id)]


def use_production_limits(app: App) -> None:
    prod = Settings(_env_file=None, BOT_TOKEN="1:x")  # type: ignore[call-arg]
    mws = app.main_bot.session.middleware._middlewares  # noqa: SLF001
    for i, m in enumerate(mws):
        if isinstance(m, RateLimitMiddleware):
            mws[i] = RateLimitMiddleware(prod)


async def run_post(app: App, post_id: int, pks: list[int], kind: str = RunKind.MANUAL, **kw: Any) -> int:
    run_id = await app.publisher.run(post_id, pks, kind=kind, wait=True, **kw)
    assert run_id is not None
    return run_id


# --------------------------------------------------------------------- runs
async def test_run_sends_to_every_chat_and_counts(app: App) -> None:
    pks = await make_chats(app, 3, members=500)
    post_id = await make_post(app, delete_after=60,
                              buttons=[[{"text": "Web", "url": "https://example.com", "style": "success"}]])
    run_id = await run_post(app, post_id, pks, triggered_by=SUPER_ID)

    ds = await deliveries(app, run_id)
    assert [d.status for d in ds] == [DeliveryStatus.SENT] * 3
    for d in ds:
        assert d.message_id and d.sent_at and d.delete_at == d.sent_at + timedelta(minutes=60)
    run = await get(app, Run, run_id)
    assert (run.status, run.kind, run.total, run.sent, run.failed, run.skipped, run.reach, run.triggered_by) == \
        (RunStatus.DONE, RunKind.MANUAL, 3, 3, 0, 0, 1500, SUPER_ID)
    assert run.post_name == "Promo Cine" and run.finished_at is not None
    post = await get(app, Post, post_id)
    assert (post.runs_count, post.sent_count, post.last_sent_at) == (1, 3, run.started_at)
    chat = await get(app, Chat, pks[0])
    assert (chat.posts_total, chat.last_post_at, chat.rot_last_post_id) == (1, ds[0].sent_at, None)
    call = app.fake.messages_to(chat.chat_id)[0]
    assert call.params["text"] == "🎬 <b>Estreno</b> esta semana"
    assert call.params["reply_markup"]["inline_keyboard"][0][0] == {"text": "Web", "url": "https://example.com",
                                                                     "style": "success"}
    async with app.db() as s:
        assert await live_count(s, post_id) == 3


async def test_rotation_runs_move_the_rotation_pointer(app: App) -> None:
    [pk] = await make_chats(app)
    post_id = await make_post(app)
    await run_post(app, post_id, [pk], kind=RunKind.ROTATION, source="global")
    assert (await get(app, Chat, pk)).rot_last_post_id == post_id


async def test_only_sendable_chats_of_the_post_bot(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_cine_bot", OWNER2_ID)
    ok, paused, no_rights, pending = await make_chats(app, 4)
    [other] = await make_chats(app, bot_id=CLONE_ID)
    async with app.db() as s:
        (await s.get(Chat, paused)).owner_paused = True
        (await s.get(Chat, no_rights)).rights_ok = False
        (await s.get(Chat, pending)).status = ChatStatus.PENDING
    post_id = await make_post(app)
    run_id = await run_post(app, post_id, [ok, paused, no_rights, pending, other, ok])
    assert [d.chat_pk for d in await deliveries(app, run_id)] == [ok]
    assert (await get(app, Run, run_id)).total == 1
    assert await app.publisher.run(post_id, [paused, other], kind=RunKind.MANUAL, wait=True) is None


async def test_send_now_is_busy_while_it_runs(app: App) -> None:
    pks = await make_chats(app, 2)
    post_id = await make_post(app)
    run_id = await app.publisher.send_now(post_id, user_id=SUPER_ID)
    assert run_id is not None
    assert app.publisher.is_busy(post_id)
    assert await app.publisher.send_now(post_id) is None
    assert await app.publisher.run(post_id, pks, kind=RunKind.MANUAL) is None
    await app.publisher.wait_idle(10)
    assert not app.publisher.is_busy(post_id)
    run = await get(app, Run, run_id)
    assert (run.kind, run.status, run.sent, run.triggered_by) == (RunKind.MANUAL, RunStatus.DONE, 2, SUPER_ID)
    nobody = await make_post(app, targets=["ext"])  # no external chat in the network
    assert await app.publisher.send_now(nobody) is None


# ---------------------------------------------------------------- anti-spam
async def test_antispam_max_per_day(app: App) -> None:
    await set_bot(app, max_per_day=1)
    pks = await make_chats(app, 2)
    first, second = await make_post(app, name="Uno"), await make_post(app, name="Dos")
    await run_post(app, first, pks[:1])
    run_id = await run_post(app, second, pks)
    assert [(d.chat_pk, d.status, d.error) for d in await deliveries(app, run_id)] == [
        (pks[0], DeliveryStatus.SKIPPED, "max_per_day"), (pks[1], DeliveryStatus.SENT, None)]
    run = await get(app, Run, run_id)
    assert (run.status, run.sent, run.skipped) == (RunStatus.DONE, 1, 1)
    assert len(app.fake.messages_to(await chat_id_of(app, pks[0]))) == 1


async def test_antispam_min_gap(app: App) -> None:
    await set_bot(app, min_gap=30)
    [pk] = await make_chats(app)
    first, second, third = [await make_post(app, name=n) for n in ("Uno", "Dos", "Tres")]
    run1 = await run_post(app, first, [pk])
    run2 = await run_post(app, second, [pk])
    assert [(d.status, d.error) for d in await deliveries(app, run2)] == [(DeliveryStatus.SKIPPED, "min_gap")]
    async with app.db() as s:  # the first post went out 31 minutes ago
        d = (await s.execute(select(Delivery).where(Delivery.run_id == run1))).scalar_one()
        d.sent_at = utcnow() - timedelta(minutes=31)
    run3 = await run_post(app, third, [pk])
    assert [d.status for d in await deliveries(app, run3)] == [DeliveryStatus.SENT]


async def test_one_at_a_time_deletes_the_previous_post_of_the_network(app: App) -> None:
    await set_bot(app, one_at_a_time=True)
    [pk] = await make_chats(app)
    cid = await chat_id_of(app, pk)
    first = await make_post(app, name="Uno", text="Uno")
    second = await make_post(app, name="Dos", text="Dos")
    run1 = await run_post(app, first, [pk])
    old = (await deliveries(app, run1))[0]
    await run_post(app, second, [pk])
    assert app.fake.calls_of("deleteMessage", chat_id=cid, message_id=old.message_id)
    assert [m["text"] for m in app.fake.chats[cid].messages.values()] == ["Dos"]
    old = (await deliveries(app, run1))[0]
    assert (old.status, old.deleted_at is not None) == (DeliveryStatus.DELETED, True)
    async with app.db() as s:
        assert (await live_count(s, first), await live_count(s, second)) == (0, 1)


async def test_delete_previous_only_deletes_its_own_copy(app: App) -> None:
    [pk] = await make_chats(app)
    cid = await chat_id_of(app, pk)
    renewed = await make_post(app, name="Renovable", text="Renovable", delete_previous=True)
    kept = await make_post(app, name="Fijo", text="Fijo", delete_previous=False)
    for post_id in (renewed, kept, renewed, kept):
        await run_post(app, post_id, [pk])
    assert sorted(m["text"] for m in app.fake.chats[cid].messages.values()) == ["Fijo", "Fijo", "Renovable"]
    assert len(app.fake.calls_of("deleteMessage", chat_id=cid)) == 1


async def test_pin_silently_and_unpin_the_older_copy(app: App) -> None:
    [pk] = await make_chats(app)
    cid = await chat_id_of(app, pk)
    post_id = await make_post(app, pin=True)
    run1 = await run_post(app, post_id, [pk])
    first = (await deliveries(app, run1))[0]
    pin = app.fake.calls_of("pinChatMessage", chat_id=cid)[0]
    assert (pin.params["message_id"], str(pin.params["disable_notification"]).lower()) == (first.message_id, "true")
    assert first.pinned and app.fake.chats[cid].pinned == [first.message_id]
    run2 = await run_post(app, post_id, [pk])  # no "delete previous": the old copy stays, but not pinned
    second = (await deliveries(app, run2))[0]
    assert app.fake.calls_of("unpinChatMessage", chat_id=cid, message_id=first.message_id)
    assert app.fake.chats[cid].pinned == [second.message_id]
    assert second.pinned and not (await deliveries(app, run1))[0].pinned


# ----------------------------------------------------------------- deletions
async def test_delete_due_deletes_misses_and_expires(app: App) -> None:
    pks = await make_chats(app, 3)
    post_id = await make_post(app, delete_after=60, pin=True)
    run_id = await run_post(app, post_id, pks)
    ds = await deliveries(app, run_id)
    assert await app.publisher.delete_due() == 0  # nothing due yet
    cids = [d.chat_id for d in ds]
    app.fake.chats[cids[1]].messages.clear()  # deleted by someone else
    async with app.db() as s:
        for d in (await s.execute(select(Delivery).where(Delivery.run_id == run_id))).scalars():
            d.delete_at = utcnow() - timedelta(seconds=5)
            if d.chat_pk == pks[2]:
                d.sent_at = utcnow() - timedelta(hours=49)  # too old: Telegram doesn't let bots delete it
    assert await app.publisher.delete_due() == 1
    ds = await deliveries(app, run_id)
    assert [d.status for d in ds] == [DeliveryStatus.DELETED, DeliveryStatus.MISSING, DeliveryStatus.EXPIRED]
    assert not app.fake.chats[cids[0]].messages
    assert not app.fake.calls_of("deleteMessage", chat_id=cids[2])
    assert app.fake.calls_of("unpinChatMessage", chat_id=cids[2])  # it stays in the chat, at least not pinned
    assert await app.publisher.delete_due() == 0


async def test_delete_due_retries_when_telegram_does_not_answer(app: App) -> None:
    [pk] = await make_chats(app)
    post_id = await make_post(app, delete_after=60)
    run_id = await run_post(app, post_id, [pk])
    async with app.db() as s:
        d = (await s.execute(select(Delivery).where(Delivery.run_id == run_id))).scalar_one()
        d.delete_at = utcnow() - timedelta(seconds=5)
    app.fake.fail("deleteMessage", code=500, description="Internal Server Error")
    assert await app.publisher.delete_due() == 0
    d = (await deliveries(app, run_id))[0]
    assert d.status == DeliveryStatus.SENT and d.delete_at > utcnow() + timedelta(minutes=4)


async def test_retire_drop_chat_and_live_count(app: App) -> None:
    pks = await make_chats(app, 3)
    post_id = await make_post(app)
    other = await make_post(app, name="Otro", text="Otro")
    run_id = await run_post(app, post_id, pks)
    await run_post(app, other, pks)
    cids = [d.chat_id for d in await deliveries(app, run_id)]

    assert await app.publisher.drop_chat(pks[0]) == 2  # both posts, before the bot leaves the chat
    assert not app.fake.chats[cids[0]].messages
    assert await app.publisher.retire(post_id) == 2
    assert [d.status for d in await deliveries(app, run_id)] == [DeliveryStatus.DELETED] * 3
    assert [m["text"] for m in app.fake.chats[cids[1]].messages.values()] == ["Otro"]
    async with app.db() as s:
        assert (await live_count(s, post_id), await live_count(s, other)) == (0, 2)
    assert await app.publisher.retire(post_id) == 0
    assert not app.publisher.is_busy(post_id)


async def test_retire_stops_a_run_in_progress(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.publisher.BATCH_SIZE", 1)
    pks = await make_chats(app, 3)
    cids = [await chat_id_of(app, pk) for pk in pks]
    post_id = await make_post(app)
    gate = asyncio.Event()
    deliver = content.deliver

    async def held(*args: Any, **kwargs: Any) -> Any:
        await gate.wait()
        return await deliver(*args, **kwargs)

    monkeypatch.setattr("app.services.publisher.content.deliver", held)
    run_id = await app.publisher.send_now(post_id)
    assert run_id is not None
    await app.wait_for(lambda: app.publisher._in_flight.get(MAIN_BOT_ID))  # noqa: SLF001 - its first batch is out
    retire = asyncio.create_task(app.publisher.retire(post_id))
    await app.wait_for(lambda: run_id in app.publisher._cancel)  # noqa: SLF001
    gate.set()
    assert await retire == 1  # the run stopped after its first chat, and that copy was deleted
    run = await get(app, Run, run_id)
    assert (run.status, run.total, run.sent) == (RunStatus.CANCELLED, 3, 1)
    assert [d.status for d in await deliveries(app, run_id)] == [DeliveryStatus.DELETED]
    assert [len(app.fake.messages_to(cid)) for cid in cids] == [1, 0, 0]
    assert not app.fake.chats[cids[0]].messages
    second = await app.publisher.send_now(post_id)  # it can be sent again
    await app.publisher.wait_idle(10)
    assert (await get(app, Run, second)).status == RunStatus.DONE


async def test_update_live_edits_the_published_copies(app: App) -> None:
    pks = await make_chats(app, 3)
    post_id = await make_post(app, text="Antes")
    run_id = await run_post(app, post_id, pks)
    ds = await deliveries(app, run_id)
    async with app.db() as s:
        post = await s.get(Post, post_id)
        post.text = "Después"
        post.buttons = [[{"text": "Ver", "url": "https://example.com"}]]
    app.fake.chats[ds[2].chat_id].messages.clear()
    assert await app.publisher.update_live(post_id) == (2, 1)
    assert app.fake.chats[ds[0].chat_id].messages[ds[0].message_id]["text"] == "Después"
    assert [d.status for d in await deliveries(app, run_id)] == [DeliveryStatus.SENT, DeliveryStatus.SENT,
                                                                 DeliveryStatus.MISSING]
    assert await app.publisher.update_live(post_id) == (2, 0)  # "not modified" counts as edited


async def test_withdraw_when_a_clone_is_disabled(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_cine_bot", OWNER2_ID)
    pks = await make_chats(app, 2, bot_id=CLONE_ID)
    auto = await make_post(app, bot_id=CLONE_ID, name="Auto", text="Auto", delete_after=120)
    kept = await make_post(app, bot_id=CLONE_ID, name="Fijo", text="Fijo", delete_after=0)
    run_auto = await run_post(app, auto, pks)
    run_kept = await run_post(app, kept, pks)
    await app.manager.disable_bot(CLONE_ID, "owner")
    assert not app.manager.is_running(CLONE_ID)
    assert [d.status for d in await deliveries(app, run_auto)] == [DeliveryStatus.DELETED] * 2
    assert [d.status for d in await deliveries(app, run_kept)] == [DeliveryStatus.SENT] * 2
    for pk in pks:
        assert [m["text"] for m in app.fake.chats[await chat_id_of(app, pk)].messages.values()] == ["Fijo"]


async def test_withdraw_bot_returns_what_it_deleted(app: App) -> None:
    pks = await make_chats(app, 2)
    post_id = await make_post(app, delete_after=30)
    await run_post(app, post_id, pks)
    assert await app.publisher.withdraw_bot(MAIN_BOT_ID, timeout=10) == 2
    assert app.manager.is_running(MAIN_BOT_ID)
    assert await app.publisher.run(post_id, pks, kind=RunKind.MANUAL, wait=True) is not None  # sending again


# -------------------------------------------------------- errors of the chats
async def test_chat_gone_is_marked_left_with_event_and_notices(app: App) -> None:
    await start_user(app, SUPER_ID)
    await start_user(app, USER_ID)
    own, ext = await make_chats(app, 2, title="Cine")
    async with app.db() as s:
        chat = await s.get(Chat, ext)
        chat.origin, chat.owner_user_id = ChatOrigin.EXTERNAL, USER_ID
    ext_id = await chat_id_of(app, ext)
    app.fake.chats[ext_id].bot_admin.pop(MAIN_BOT_ID)  # the bot was removed: 403
    post_id = await make_post(app)
    run_id = await run_post(app, post_id, [own, ext])
    sent, failed = await deliveries(app, run_id)
    assert sent.status == DeliveryStatus.SENT
    assert failed.status == DeliveryStatus.FAILED and "Forbidden" in (failed.error or "")
    assert (await get(app, Chat, ext)).status == ChatStatus.LEFT
    assert [e.chat_pk for e in await events_of(app, EventKind.CHAT_LEFT)] == [ext]
    assert any("Cine 2" in x for x in dm_texts(app, SUPER_ID))  # admins alerted
    assert any("ya no está en tu canal <b>Cine 2</b>" in x for x in dm_texts(app, USER_ID))  # the partner told
    assert not app.fake.calls_of("getChatMember", chat_id=ext_id)  # a 403 is final: no probe
    run = await get(app, Run, run_id)
    assert (run.status, run.sent, run.failed) == (RunStatus.DONE, 1, 1)


async def test_chat_not_found_needs_a_second_call(app: App) -> None:
    unconfirmed, confirmed = await make_chats(app, 2)
    cid1, cid2 = await chat_id_of(app, unconfirmed), await chat_id_of(app, confirmed)
    app.fake.fail("sendMessage", description="Bad Request: chat not found", when=lambda p: p.get("chat_id") == cid1)
    del app.fake.chats[cid2]  # really gone
    run_id = await run_post(app, await make_post(app), [unconfirmed, confirmed])
    assert [d.status for d in await deliveries(app, run_id)] == [DeliveryStatus.FAILED] * 2
    assert app.fake.calls_of("getChatMember", chat_id=cid1) and app.fake.calls_of("getChatMember", chat_id=cid2)
    assert (await get(app, Chat, unconfirmed)).status == ChatStatus.APPROVED  # a hiccup never expels a chat
    assert (await get(app, Chat, confirmed)).status == ChatStatus.LEFT


async def test_lost_rights_and_closed_topic(app: App) -> None:
    await start_user(app, SUPER_ID)
    [channel] = await make_chats(app, title="Canal sin permisos")
    [group] = await make_chats(app, type=ChatType.GROUP, title="Foro")
    cid = await chat_id_of(app, channel)
    gid = await chat_id_of(app, group)
    app.fake.chats[cid].bot_admin[MAIN_BOT_ID] = {**ADMIN_RIGHTS_FULL, "can_post_messages": False}
    app.fake.fail("sendMessage", description="Bad Request: TOPIC_CLOSED", when=lambda p: p.get("chat_id") == gid)
    run_id = await run_post(app, await make_post(app), [channel, group])
    assert [d.status for d in await deliveries(app, run_id)] == [DeliveryStatus.FAILED] * 2
    ch, gr = await get(app, Chat, channel), await get(app, Chat, group)
    assert (ch.status, ch.rights_ok, ch.missing_rights) == (ChatStatus.APPROVED, False, "can_post_messages")
    assert (gr.rights_ok, gr.missing_rights) == (False, "can_manage_topics")
    assert {e.chat_pk for e in await events_of(app, EventKind.CHAT_RIGHTS)} == {channel, group}
    assert any("Canal sin permisos" in x for x in dm_texts(app, SUPER_ID))  # the admins are alerted


async def test_a_403_that_only_forbids_writing_is_not_a_chat_gone(app: App) -> None:
    [pk] = await make_chats(app, type=ChatType.GROUP)
    gid = await chat_id_of(app, pk)
    app.fake.chats[gid].bot_admin[MAIN_BOT_ID] = None  # a plain member now
    app.fake.fail("sendMessage", code=403, description="Forbidden: CHAT_WRITE_FORBIDDEN",
                  when=lambda p: p.get("chat_id") == gid)
    run_id = await run_post(app, await make_post(app), [pk])
    assert (await deliveries(app, run_id))[0].status == DeliveryStatus.FAILED
    chat = await get(app, Chat, pk)
    assert (chat.status, chat.rights_ok, chat.missing_rights) == (ChatStatus.APPROVED, False, "admin")


async def test_a_refusal_with_the_bot_in_the_chat_is_a_temporary_failure(app: App) -> None:
    [pk] = await make_chats(app, type=ChatType.GROUP)
    gid = await chat_id_of(app, pk)
    app.fake.fail("sendMessage", description="Bad Request: not enough rights to send text messages to the chat",
                  when=lambda p: p.get("chat_id") == gid)
    run_id = await run_post(app, await make_post(app), [pk])
    assert (await deliveries(app, run_id))[0].status == DeliveryStatus.FAILED
    chat = await get(app, Chat, pk)
    assert (chat.status, chat.rights_ok) == (ChatStatus.APPROVED, True)  # the bot is admin with its rights there


async def test_migrated_group_gets_the_post_in_the_supergroup(app: App) -> None:
    [pk] = await make_chats(app, type=ChatType.GROUP, title="Grupo de Cine")
    old_id = await chat_id_of(app, pk)
    new_id = -100_999_000_001
    app.fake.add_chat(new_id, "Grupo de Cine", type="supergroup", admin_bots={MAIN_BOT_ID: "full"})
    app.fake.fail("sendMessage", description="Bad Request: group chat was upgraded to a supergroup chat",
                  parameters={"migrate_to_chat_id": new_id}, when=lambda p: p.get("chat_id") == old_id)
    run_id = await run_post(app, await make_post(app), [pk])
    [d] = await deliveries(app, run_id)
    assert (d.status, d.chat_id) == (DeliveryStatus.SENT, new_id)
    assert (await get(app, Chat, pk)).chat_id == new_id
    assert len(app.fake.messages_to(new_id)) == 1


async def test_an_unknown_outcome_is_never_sent_again(app: App) -> None:
    [pk, other] = await make_chats(app, 2)
    cid = await chat_id_of(app, pk)
    app.fake.fail("sendMessage", code=500, description="Internal Server Error",
                  when=lambda p: p.get("chat_id") == cid)
    run_id = await run_post(app, await make_post(app), [pk, other])
    unknown, sent = await deliveries(app, run_id)
    assert (unknown.status, unknown.message_id) == (DeliveryStatus.UNKNOWN, None)
    assert sent.status == DeliveryStatus.SENT
    assert len(app.fake.calls_of("sendMessage", chat_id=cid)) == 1
    run = await get(app, Run, run_id)
    assert (run.status, run.sent, run.failed) == (RunStatus.DONE, 1, 0)
    assert (await get(app, Chat, pk)).status == ChatStatus.APPROVED


async def test_a_rejected_button_sends_without_buttons_and_tells_it(app: App) -> None:
    await start_user(app, SUPER_ID, run_reports=True)
    pks = await make_chats(app, 30)
    app.fake.fail("sendMessage", description="Bad Request: BUTTON_URL_INVALID", times=100,
                  when=lambda p: "reply_markup" in p and int(p.get("chat_id", 0)) < 0)
    post_id = await make_post(app, buttons=[[{"text": "Roto", "url": "https://bad.example.com"}]])
    run_id = await run_post(app, post_id, pks)
    ds = await deliveries(app, run_id)
    assert [d.status for d in ds] == [DeliveryStatus.SENT] * 30
    for d in ds:  # every chat got the post, without buttons
        assert "reply_markup" not in app.fake.messages_to(d.chat_id)[-1].params
    tried = [c for c in app.fake.calls_of("sendMessage") if "reply_markup" in c.params and int(c.params["chat_id"]) < 0]
    assert len(tried) <= 25  # once refused, the next batches go without buttons from the start
    assert ds[0].error is not None and ds[0].error.startswith("no buttons: ")
    assert ds[-1].error is None
    report = dm_texts(app, SUPER_ID)[-1]
    assert report.startswith("📤 <b>Promo Cine</b> enviado a 30/30 chats.")
    assert "BUTTON_URL_INVALID" in report


# --------------------------------------------------------------------- media
async def test_a_clone_sends_media_of_the_main_bot_and_remembers_its_file_id(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_cine_bot", OWNER2_ID)
    pks = await make_chats(app, 3, bot_id=CLONE_ID)
    app.fake.files["PHOTO_MAIN"] = b"\x89PNG fake image"
    post_id = await make_post(app, bot_id=CLONE_ID, kind="photo", text="Cartel", media={str(MAIN_BOT_ID): "PHOTO_MAIN"})
    run_id = await run_post(app, post_id, pks)
    assert [d.status for d in await deliveries(app, run_id)] == [DeliveryStatus.SENT] * 3
    [get_file] = app.fake.calls_of("getFile")
    assert get_file.token == app.settings.BOT_TOKEN and get_file.params["file_id"] == "PHOTO_MAIN"
    assert [k for k in app.fake.files if k.startswith("upl")] == ["upl1"]  # uploaded once
    assert app.fake.files["upl1"] == b"\x89PNG fake image"
    photos = app.fake.calls_of("sendPhoto")
    assert [c.params["photo"] for c in photos] == ["upl1"] * 3
    assert {c.token for c in photos} == {f"{CLONE_ID}:TEST{CLONE_ID}"}
    assert (await get(app, Post, post_id)).media == {str(MAIN_BOT_ID): "PHOTO_MAIN", str(CLONE_ID): "upl1"}
    await run_post(app, post_id, pks)  # its own file id now: no download
    assert len(app.fake.calls_of("getFile")) == 1


async def test_media_that_cannot_be_used_fails_the_run_and_tells_the_admins(app: App) -> None:
    await start_user(app, SUPER_ID)  # alerts on, run reports off
    pks = await make_chats(app, 2)
    post_id = await make_post(app, name="Cartel", kind="photo", text=None, media={"424242": "GONE"})
    run_id = await run_post(app, post_id, pks)
    ds = await deliveries(app, run_id)
    assert [(d.status, d.error) for d in ds] == [(DeliveryStatus.FAILED, "media: unavailable")] * 2
    run = await get(app, Run, run_id)
    assert (run.status, run.sent, run.failed) == (RunStatus.FAILED, 0, 2)
    assert dm_texts(app, SUPER_ID)[-1].startswith("⚠️ <b>Cartel</b> no se ha podido enviar")
    assert not app.fake.calls_of("sendPhoto")
    await run_post(app, post_id, pks)
    assert len(dm_texts(app, SUPER_ID)) == 1  # the same problem is told once a day


# --------------------------------------------------------------- run reports
async def test_run_report_to_the_admins_who_want_it(app: App) -> None:
    await start_user(app, SUPER_ID, run_reports=True)
    await start_user(app, OWNER2_ID, role=Role.ADMIN)  # an admin without run reports
    await set_bot(app, max_per_day=1)
    ok, skipped, failing = await make_chats(app, 3)
    await run_post(app, await make_post(app, name="Antes"), [skipped])
    app.fake.reset_calls()
    fid = await chat_id_of(app, failing)
    app.fake.fail("sendMessage", description="Bad Request: MESSAGE_EMPTY", when=lambda p: p.get("chat_id") == fid)
    post_id = await make_post(app, name="Promo <Cine>")
    await run_post(app, post_id, [ok, skipped, failing])
    [report] = [c for c in app.fake.calls_of("sendMessage", chat_id=SUPER_ID)]
    assert report.params["text"] == ("📤 <b>Promo &lt;Cine&gt;</b> enviado a 1/3 chats "
                                     "(1 fallo · 1 omitido por anti-spam).")
    assert report.params["reply_markup"]["inline_keyboard"][0][0]["text"] == "📝 Ver mensaje"
    assert not dm_texts(app, OWNER2_ID)


# -------------------------------------------------------------------- resume
async def test_resume_after_a_restart(app: App) -> None:
    pks = await make_chats(app, 4)
    post_id = await make_post(app)
    started = utcnow() - timedelta(minutes=2)
    async with app.db() as s:
        run = Run(bot_id=MAIN_BOT_ID, post_id=post_id, post_name="Promo Cine", kind=RunKind.ROTATION, source="global",
                  status=RunStatus.SENDING, total=4, started_at=started)
        s.add(run)
        await s.flush()
        run_id = run.id
        for pk, status in zip(pks, ("sent", "sending", "queued", "queued")):
            chat = await s.get(Chat, pk)
            s.add(Delivery(run_id=run_id, bot_id=MAIN_BOT_ID, post_id=post_id, chat_pk=pk, chat_id=chat.chat_id,
                           status=status, message_id=5 if status == "sent" else None,
                           sent_at=started if status == "sent" else None))
    await app.publisher.resume()
    await app.publisher.wait_idle(10)
    ds = await deliveries(app, run_id)
    assert [d.status for d in ds] == [DeliveryStatus.SENT, DeliveryStatus.UNKNOWN, DeliveryStatus.SENT,
                                      DeliveryStatus.SENT]
    assert [len(app.fake.messages_to(d.chat_id)) for d in ds] == [0, 0, 1, 1]  # the "sending" one is never resent
    run = await get(app, Run, run_id)
    assert (run.status, run.sent, run.failed) == (RunStatus.DONE, 3, 0)
    assert (await get(app, Chat, pks[2])).rot_last_post_id == post_id


async def test_a_run_interrupted_long_ago_is_not_sent_late(app: App) -> None:
    pks = await make_chats(app, 2)
    post_id = await make_post(app)
    async with app.db() as s:
        run = Run(bot_id=MAIN_BOT_ID, post_id=post_id, post_name="Promo Cine", kind=RunKind.ROTATION,
                  status=RunStatus.SENDING, total=2, started_at=utcnow() - timedelta(hours=3))
        s.add(run)
        await s.flush()
        run_id = run.id
        for pk in pks:
            s.add(Delivery(run_id=run_id, bot_id=MAIN_BOT_ID, post_id=post_id, chat_pk=pk,
                           chat_id=(await s.get(Chat, pk)).chat_id, status=DeliveryStatus.QUEUED))
    await app.publisher.resume()
    await app.publisher.wait_idle(10)
    assert [(d.status, d.error) for d in await deliveries(app, run_id)] == [(DeliveryStatus.FAILED, "interrupted")] * 2
    assert (await get(app, Run, run_id)).status == RunStatus.FAILED
    assert not app.fake.calls_of("sendMessage")


# --------------------------------------------------------------- rate limits
async def test_a_run_to_many_chats_never_breaks_telegram_limits(app: App) -> None:
    pks = await make_chats(app, 60)
    post_id = await make_post(app)
    app.fake.strict_limits = True
    use_production_limits(app)
    run_id = await run_post(app, post_id, pks)
    assert app.fake.limit_violations == 0
    run = await get(app, Run, run_id)
    assert (run.sent, run.failed) == (60, 0)
    assert len(app.fake.calls_of("sendMessage")) == 60
