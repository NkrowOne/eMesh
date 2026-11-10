"""Engine and the canal almacén: channels get the premium copy of a post as a forward (Telegram keeps its custom
emoji), groups a normal message; a stale or deleted copy means a normal send; 🔄 Actualizar publicados replaces the
messages of the channels (a forward can't be edited) and edits the rest."""
from __future__ import annotations

import itertools
import time
from datetime import timedelta
from typing import Any

import pytest

from app.db.base import utcnow
from app.db.models import Chat, ChatOrigin, ChatStatus, ChatType, DeliveryStatus, Post
from app.services import content
from tests.conftest import MAIN_BOT_ID, App
from tests.fake_tg import ADMIN_RIGHTS_FULL
from tests.test_engine import chat_id_of, deliveries, get, make_chats, make_post, run_post

EMOJI_ID = "5368324170671202286"
TEXT = f'<tg-emoji emoji-id="{EMOJI_ID}">🔥</tg-emoji> Hola'
_vault_ids = itertools.count(1)
_copy_ids = itertools.count(500)


def put_copy(app: App, vault_id: int, text: str = "🔥 Hola") -> int:
    """A message with custom emoji in the canal almacén (as the admin's forward left it). Returns its id."""
    mid = next(_copy_ids)
    app.fake.chats[vault_id].messages[mid] = {
        "message_id": mid, "date": int(time.time()), "chat": app.fake.chat_json(vault_id),
        "sender_chat": app.fake.chat_json(vault_id), "text": text,
        "entities": [{"type": "custom_emoji", "offset": 0, "length": 2, "custom_emoji_id": EMOJI_ID}],
    }
    return mid


async def link_copy(app: App, post_id: int, vault_id: int, mid: int) -> None:
    """The post points to that copy, made from its current content."""
    async with app.db() as s:
        post = await s.get(Post, post_id)
        post.vault_chat_id, post.vault_msg_id = vault_id, mid
        post.vault_sig = content.signature(post)


async def make_vault(app: App, post_id: int) -> tuple[int, int, int]:
    """The canal almacén of the network with the premium copy of the post. Returns (chat pk, chat id, message id)."""
    vault_id = -100_900_000 - next(_vault_ids)
    app.fake.add_chat(vault_id, "Almacén", type="channel", admin_bots={MAIN_BOT_ID: "full"})
    async with app.db() as s:
        chat = Chat(bot_id=MAIN_BOT_ID, chat_id=vault_id, type=ChatType.CHANNEL, title="Almacén", members=1,
                    origin=ChatOrigin.OWN, status=ChatStatus.APPROVED, rights_ok=True, approved_at=utcnow(),
                    vault=True)
        s.add(chat)
        await s.flush()
        pk = chat.id
    mid = put_copy(app, vault_id)
    await link_copy(app, post_id, vault_id, mid)
    return pk, vault_id, mid


def forwards_to(app: App, chat_id: int) -> list[Any]:
    return app.fake.calls_of("forwardMessage", chat_id=chat_id)


async def set_text(app: App, post_id: int, text: str) -> None:
    async with app.db() as s:
        (await s.get(Post, post_id)).text = text


# --------------------------------------------------------------------- runs
async def test_channels_get_the_premium_copy_and_groups_a_normal_message(app: App) -> None:
    [channel] = await make_chats(app)
    [group] = await make_chats(app, type=ChatType.GROUP, title="Grupo de Cine")
    cid, gid = await chat_id_of(app, channel), await chat_id_of(app, group)
    post_id = await make_post(app, text=TEXT, silent=True)
    vault_pk, vault_id, mid = await make_vault(app, post_id)

    run_id = await run_post(app, post_id, [channel, group, vault_pk])

    [fwd] = forwards_to(app, cid)
    assert (int(fwd.params["from_chat_id"]), int(fwd.params["message_id"])) == (vault_id, mid)
    assert str(fwd.params["disable_notification"]).lower() == "true"  # the options of the post
    assert not app.fake.messages_to(cid)
    assert [c.params["text"] for c in app.fake.messages_to(gid)] == [TEXT]
    assert not forwards_to(app, gid)
    assert not app.fake.messages_to(vault_id) and not forwards_to(app, vault_id)  # it receives nothing

    ds = {d.chat_pk: d for d in await deliveries(app, run_id)}
    assert set(ds) == {channel, group}
    assert [(ds[pk].status, ds[pk].forwarded) for pk in (channel, group)] == [(DeliveryStatus.SENT, True),
                                                                              (DeliveryStatus.SENT, False)]
    out = app.fake.chats[cid].messages[ds[channel].message_id]
    assert out["forward_origin"] and out["entities"][0]["type"] == "custom_emoji"  # the premium emoji got there
    assert (await get(app, Post, post_id)).vault_msg_id == mid


async def test_a_stale_copy_is_not_forwarded(app: App) -> None:
    [channel] = await make_chats(app)
    cid = await chat_id_of(app, channel)
    post_id = await make_post(app, text=TEXT)
    _, _, mid = await make_vault(app, post_id)
    await set_text(app, post_id, TEXT + " (nuevo)")  # the copy was made from the old text

    run_id = await run_post(app, post_id, [channel])

    assert not forwards_to(app, cid)
    assert len(app.fake.messages_to(cid)) == 1
    [d] = await deliveries(app, run_id)
    assert (d.status, d.forwarded) == (DeliveryStatus.SENT, False)
    assert (await get(app, Post, post_id)).vault_msg_id == mid  # still linked: it only needs a new copy


async def test_a_deleted_copy_means_a_normal_send_and_its_link_is_cleared(app: App,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.publisher.BATCH_SIZE", 1)
    channels = await make_chats(app, 2)
    cids = [await chat_id_of(app, pk) for pk in channels]
    post_id = await make_post(app, text=TEXT)
    _, vault_id, mid = await make_vault(app, post_id)
    del app.fake.chats[vault_id].messages[mid]  # deleted from the canal almacén

    run_id = await run_post(app, post_id, channels)

    assert [len(app.fake.messages_to(cid)) for cid in cids] == [1, 1]
    assert [len(forwards_to(app, cid)) for cid in cids] == [1, 0]  # the next chats don't try it again
    ds = await deliveries(app, run_id)
    assert [(d.status, d.forwarded) for d in ds] == [(DeliveryStatus.SENT, False)] * 2
    post = await get(app, Post, post_id)
    assert (post.vault_chat_id, post.vault_msg_id) == (vault_id, None)
    assert content.vault_copy(post) is None


async def test_a_forward_refused_by_the_chat_is_its_usual_failure(app: App) -> None:
    good, bad = await make_chats(app, 2)
    good_id, bad_id = await chat_id_of(app, good), await chat_id_of(app, bad)
    app.fake.chats[bad_id].bot_admin[MAIN_BOT_ID] = {**ADMIN_RIGHTS_FULL, "can_post_messages": False}
    post_id = await make_post(app, text=TEXT)
    _, _, mid = await make_vault(app, post_id)

    run_id = await run_post(app, post_id, [good, bad])

    ds = {d.chat_pk: d for d in await deliveries(app, run_id)}
    assert (ds[good].status, ds[good].forwarded) == (DeliveryStatus.SENT, True)
    assert (ds[bad].status, ds[bad].forwarded) == (DeliveryStatus.FAILED, False)
    assert forwards_to(app, good_id) and forwards_to(app, bad_id)
    assert app.fake.calls_of("sendMessage", chat_id=bad_id)  # the normal send failed too: the chat's problem
    chat = await get(app, Chat, bad)
    assert (chat.rights_ok, chat.missing_rights) == (False, "can_post_messages")
    assert (await get(app, Post, post_id)).vault_msg_id == mid  # the copy is fine


# ------------------------------------------------------------------ updates
async def test_update_live_replaces_the_forwards_and_edits_the_groups(app: App) -> None:
    [channel] = await make_chats(app)
    [group] = await make_chats(app, type=ChatType.GROUP, title="Grupo de Cine")
    cid, gid = await chat_id_of(app, channel), await chat_id_of(app, group)
    post_id = await make_post(app, text=TEXT, pin=True, delete_after=60)
    _, vault_id, _ = await make_vault(app, post_id)
    run_id = await run_post(app, post_id, [channel, group])
    old = {d.chat_pk: d for d in await deliveries(app, run_id)}
    assert old[channel].forwarded and old[channel].pinned and old[group].pinned

    new_text = TEXT + " y adiós"
    await set_text(app, post_id, new_text)
    new_mid = put_copy(app, vault_id, "🔥 Hola y adiós")
    await link_copy(app, post_id, vault_id, new_mid)  # the admin made the new copy
    before = utcnow()

    assert await app.publisher.update_live(post_id) == (2, 0)

    ds = {d.chat_pk: d for d in await deliveries(app, run_id)}
    ch = ds[channel]
    assert int(forwards_to(app, cid)[-1].params["message_id"]) == new_mid
    assert app.fake.calls_of("deleteMessage", chat_id=cid, message_id=old[channel].message_id)
    assert ch.message_id != old[channel].message_id
    assert old[channel].message_id not in app.fake.chats[cid].messages
    assert app.fake.chats[cid].messages[ch.message_id]["text"] == "🔥 Hola y adiós"
    assert (ch.status, ch.forwarded, ch.pinned) == (DeliveryStatus.SENT, True, True)
    assert ch.sent_at >= before - timedelta(seconds=1) and ch.delete_at == ch.sent_at + timedelta(minutes=60)
    pin = app.fake.calls_of("pinChatMessage", chat_id=cid, message_id=ch.message_id)[0]
    assert str(pin.params["disable_notification"]).lower() == "true"
    assert app.fake.chats[cid].pinned[-1] == ch.message_id
    assert not app.fake.calls_of("editMessageText", chat_id=cid)

    gr = ds[group]
    assert (gr.message_id, gr.sent_at, gr.forwarded, gr.pinned) == (old[group].message_id, old[group].sent_at,
                                                                    False, True)
    assert app.fake.calls_of("editMessageText", chat_id=gid, message_id=gr.message_id)
    assert app.fake.chats[gid].messages[gr.message_id]["text"] == new_text
    assert not app.fake.calls_of("deleteMessage", chat_id=gid)


async def test_update_live_in_a_channel_without_and_with_a_copy(app: App) -> None:
    [channel] = await make_chats(app)
    cid = await chat_id_of(app, channel)
    post_id = await make_post(app, text=TEXT)
    run_id = await run_post(app, post_id, [channel])  # no copy yet: a normal message
    [first] = await deliveries(app, run_id)
    assert not first.forwarded

    _, _, mid = await make_vault(app, post_id)  # now there is one: the channel gets it
    assert await app.publisher.update_live(post_id) == (1, 0)
    [second] = await deliveries(app, run_id)
    assert second.forwarded and second.message_id != first.message_id
    assert int(forwards_to(app, cid)[-1].params["message_id"]) == mid
    assert first.message_id not in app.fake.chats[cid].messages

    await set_text(app, post_id, TEXT + " (nuevo)")  # the copy is out of date: a forward can't be edited
    assert await app.publisher.update_live(post_id) == (1, 0)
    [third] = await deliveries(app, run_id)
    assert not third.forwarded and third.message_id != second.message_id
    assert len(forwards_to(app, cid)) == 1 and len(app.fake.messages_to(cid)) == 2
    assert second.message_id not in app.fake.chats[cid].messages

    assert await app.publisher.update_live(post_id) == (1, 0)  # a normal message without a copy: edited
    [fourth] = await deliveries(app, run_id)
    assert fourth.message_id == third.message_id
    assert app.fake.calls_of("editMessageText", chat_id=cid, message_id=third.message_id)


async def test_update_live_reports_a_replacement_that_could_not_be_sent(app: App) -> None:
    """The old message goes first (never two copies): when the new one can't be sent, the delivery is deleted."""
    [channel] = await make_chats(app)
    cid = await chat_id_of(app, channel)
    post_id = await make_post(app, text=TEXT)
    await make_vault(app, post_id)
    run_id = await run_post(app, post_id, [channel])
    [before] = await deliveries(app, run_id)
    app.fake.fail("forwardMessage", description="Bad Request: CHAT_WRITE_FORBIDDEN")
    app.fake.fail("sendMessage", description="Bad Request: CHAT_WRITE_FORBIDDEN")

    assert await app.publisher.update_live(post_id) == (0, 1)

    [after] = await deliveries(app, run_id)
    assert (after.message_id, after.status) == (before.message_id, DeliveryStatus.DELETED)
    assert before.message_id not in app.fake.chats[cid].messages


async def test_update_live_doesnt_bring_back_a_message_deleted_in_the_channel(app: App) -> None:
    [channel] = await make_chats(app)
    cid = await chat_id_of(app, channel)
    post_id = await make_post(app, text=TEXT)
    await make_vault(app, post_id)
    run_id = await run_post(app, post_id, [channel])
    [before] = await deliveries(app, run_id)
    app.fake.chats[cid].messages.pop(before.message_id)  # its owner deleted it
    forwards = len(app.fake.calls_of("forwardMessage"))

    assert await app.publisher.update_live(post_id) == (0, 1)

    [after] = await deliveries(app, run_id)
    assert after.status == DeliveryStatus.MISSING
    assert len(app.fake.calls_of("forwardMessage")) == forwards


async def test_update_live_leaves_a_message_that_cant_be_deleted(app: App) -> None:
    [channel] = await make_chats(app)
    cid = await chat_id_of(app, channel)
    post_id = await make_post(app, text=TEXT)
    await make_vault(app, post_id)
    run_id = await run_post(app, post_id, [channel])
    [before] = await deliveries(app, run_id)
    app.fake.fail("deleteMessage", description="Bad Request: message can't be deleted")
    forwards = len(app.fake.calls_of("forwardMessage"))

    assert await app.publisher.update_live(post_id) == (0, 1)

    [after] = await deliveries(app, run_id)
    assert (after.message_id, after.status) == (before.message_id, DeliveryStatus.SENT)
    assert before.message_id in app.fake.chats[cid].messages
    assert len(app.fake.calls_of("forwardMessage")) == forwards  # never two copies
