"""Engine and custom (premium) emoji in channels: Telegram refuses them in a message a bot sends to a channel but keeps
them in a forwarded one. So the first channel of a run makes the bot send the post, silently, to the private chat of
an admin of the network (the owner first): every channel gets that source message forwarded, the groups a normal
message, and it is deleted when the run is over. Without Telegram Premium, or with no admin to send it to, the
channels get the normal message. 🔄 Actualizar publicados replaces the messages of the channels (a forward can't be
edited) and edits the rest."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.db.base import utcnow
from app.db.models import Chat, ChatType, DeliveryStatus, Post, Role, Run, RunStatus
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, App
from tests.fake_tg import ADMIN_RIGHTS_FULL, Call
from tests.test_engine import (
    CLONE_ID,
    chat_id_of,
    deliveries,
    dm_texts,
    get,
    make_chats,
    make_post,
    run_post,
    set_bot,
    start_user,
)

EMOJI_ID = "5368324170671202286"
TEXT = f'<tg-emoji emoji-id="{EMOJI_ID}">🔥</tg-emoji> Hola'
PLAIN = "🔥 Hola"  # TEXT with its custom emoji turned into the normal one


def sources(app: App, uid: int = SUPER_ID) -> list[Call]:
    """What the bot sent to the private chat of ``uid`` (source messages, refused ones included; not run reports)."""
    return [c for c in app.fake.calls_of("sendMessage", chat_id=uid) if not str(c.params.get("text")).startswith("📤")]


def mid_of(call: Call) -> int:
    return int(call.result["message_id"])


def forwards_to(app: App, chat_id: int) -> list[Call]:
    return app.fake.calls_of("forwardMessage", chat_id=chat_id)


def origin_of(fwd: Call) -> tuple[int, int]:
    return int(fwd.params["from_chat_id"]), int(fwd.params["message_id"])


def is_true(value: Any) -> bool:
    return str(value).lower() == "true"


def assert_dropped(app: App, uid: int, src: Call) -> None:
    """The source message was deleted from the private chat of ``uid``."""
    assert app.fake.calls_of("deleteMessage", chat_id=uid, message_id=mid_of(src))
    assert mid_of(src) not in app.fake.private_messages[uid]


async def set_text(app: App, post_id: int, text: str) -> None:
    async with app.db() as s:
        (await s.get(Post, post_id)).text = text


# --------------------------------------------------------------------- runs
async def test_channels_get_a_forward_of_the_source_message_and_groups_a_normal_message(app: App) -> None:
    [channel] = await make_chats(app)
    [group] = await make_chats(app, type=ChatType.GROUP, title="Grupo de Cine")
    cid, gid = await chat_id_of(app, channel), await chat_id_of(app, group)
    post_id = await make_post(app, text=TEXT, silent=True, protect=True)

    run_id = await run_post(app, post_id, [channel, group])

    [src] = sources(app)  # to the owner: silent, forwardable, with the custom emoji
    assert src.params["text"] == TEXT
    assert is_true(src.params["disable_notification"]) and "protect_content" not in src.params
    [fwd] = forwards_to(app, cid)
    assert origin_of(fwd) == (SUPER_ID, mid_of(src))
    assert is_true(fwd.params["disable_notification"]) and is_true(fwd.params["protect_content"])  # the post's
    assert not app.fake.messages_to(cid)
    [normal] = app.fake.messages_to(gid)
    assert normal.method == "sendMessage" and normal.params["text"] == TEXT
    assert is_true(normal.params["protect_content"])
    assert not forwards_to(app, gid)
    assert_dropped(app, SUPER_ID, src)
    [drop] = app.fake.calls_of("deleteMessage", chat_id=SUPER_ID)
    assert app.fake.calls.index(drop) > app.fake.calls.index(fwd)  # once the run is over

    ds = {d.chat_pk: d for d in await deliveries(app, run_id)}
    assert [(ds[pk].status, ds[pk].forwarded) for pk in (channel, group)] == [(DeliveryStatus.SENT, True),
                                                                              (DeliveryStatus.SENT, False)]
    out = app.fake.chats[cid].messages[ds[channel].message_id]
    assert out["forward_origin"]["type"] == "user" and out["forward_origin"]["sender_user"]["id"] == MAIN_BOT_ID
    assert [e["type"] for e in out["entities"]] == ["custom_emoji"]  # the premium emoji got there
    assert app.fake.chats[gid].messages[ds[group].message_id]["entities"][0]["type"] == "custom_emoji"


async def test_one_source_message_per_run(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.publisher.BATCH_SIZE", 2)  # two batches of two chats at a time
    channels = await make_chats(app, 4)
    cids = [await chat_id_of(app, pk) for pk in channels]
    post_id = await make_post(app, text=TEXT)

    run_id = await run_post(app, post_id, channels)

    [src] = sources(app)
    assert [[origin_of(c) for c in forwards_to(app, cid)] for cid in cids] == [[(SUPER_ID, mid_of(src))]] * 4
    assert [(d.status, d.forwarded) for d in await deliveries(app, run_id)] == [(DeliveryStatus.SENT, True)] * 4
    assert len(app.fake.calls_of("deleteMessage", chat_id=SUPER_ID)) == 1
    assert_dropped(app, SUPER_ID, src)

    await run_post(app, post_id, channels)  # the next run makes its own

    first, second = sources(app)
    assert mid_of(second) != mid_of(first)
    assert [origin_of(forwards_to(app, cid)[-1]) for cid in cids] == [(SUPER_ID, mid_of(second))] * 4
    assert_dropped(app, SUPER_ID, second)


async def test_a_run_to_groups_only_makes_no_source_message(app: App) -> None:
    groups = await make_chats(app, 2, type=ChatType.GROUP, title="Grupo de Cine")
    gids = [await chat_id_of(app, pk) for pk in groups]
    post_id = await make_post(app, text=TEXT)

    run_id = await run_post(app, post_id, groups)

    assert not sources(app) and not app.fake.calls_of("forwardMessage")
    assert [[c.params["text"] for c in app.fake.messages_to(gid)] for gid in gids] == [[TEXT]] * 2
    assert [(d.status, d.forwarded) for d in await deliveries(app, run_id)] == [(DeliveryStatus.SENT, False)] * 2


async def test_a_post_without_custom_emoji_makes_no_source_message(app: App) -> None:
    [channel] = await make_chats(app)
    [group] = await make_chats(app, type=ChatType.GROUP, title="Grupo de Cine")
    cid, gid = await chat_id_of(app, channel), await chat_id_of(app, group)
    post_id = await make_post(app)

    run_id = await run_post(app, post_id, [channel, group])

    assert not sources(app) and not app.fake.calls_of("forwardMessage")
    assert [len(app.fake.calls_of("sendMessage", chat_id=c)) for c in (cid, gid)] == [1, 1]
    assert [(d.status, d.forwarded) for d in await deliveries(app, run_id)] == [(DeliveryStatus.SENT, False)] * 2


async def test_a_custom_emoji_icon_on_a_button_is_enough(app: App) -> None:
    [channel] = await make_chats(app)
    cid = await chat_id_of(app, channel)
    post_id = await make_post(app, text="Hola", buttons=[[{"text": "Web", "icon": EMOJI_ID, "emoji": "🔥",
                                                            "url": "https://example.com"}]])

    run_id = await run_post(app, post_id, [channel])

    [src] = sources(app)
    assert src.params["reply_markup"]["inline_keyboard"][0][0]["icon_custom_emoji_id"] == EMOJI_ID
    assert [origin_of(c) for c in forwards_to(app, cid)] == [(SUPER_ID, mid_of(src))]
    assert not app.fake.messages_to(cid)
    [d] = await deliveries(app, run_id)
    assert (d.status, d.forwarded) == (DeliveryStatus.SENT, True)
    out = app.fake.chats[cid].messages[d.message_id]
    assert out["reply_markup"]["inline_keyboard"][0][0]["icon_custom_emoji_id"] == EMOJI_ID
    assert_dropped(app, SUPER_ID, src)


async def test_without_telegram_premium_the_channels_get_the_normal_message(app: App) -> None:
    app.fake.premium_owners = False  # Telegram turns the custom emoji of the source message into normal ones
    channels = await make_chats(app, 2)
    post_id = await make_post(app, text=TEXT)

    run_id = await run_post(app, post_id, channels)

    [src] = sources(app)  # tried once for the whole run
    assert_dropped(app, SUPER_ID, src)
    assert not app.fake.calls_of("forwardMessage")
    ds = await deliveries(app, run_id)
    assert [(d.status, d.forwarded) for d in ds] == [(DeliveryStatus.SENT, False)] * 2
    for d in ds:
        assert [c.method for c in app.fake.messages_to(d.chat_id)] == ["sendMessage"]
        out = app.fake.chats[d.chat_id].messages[d.message_id]
        assert out["text"] == PLAIN and "entities" not in out


async def test_the_next_admin_gets_the_source_message_when_the_owner_blocked_the_bot(app: App) -> None:
    await start_user(app, OWNER2_ID, role=Role.ADMIN)
    app.fake.blocked.add((MAIN_BOT_ID, SUPER_ID))
    [channel] = await make_chats(app)
    cid = await chat_id_of(app, channel)
    post_id = await make_post(app, text=TEXT)

    run_id = await run_post(app, post_id, [channel])

    [refused] = sources(app, SUPER_ID)
    assert refused.result is None
    [src] = sources(app, OWNER2_ID)
    assert [origin_of(c) for c in forwards_to(app, cid)] == [(OWNER2_ID, mid_of(src))]
    assert_dropped(app, OWNER2_ID, src)
    [d] = await deliveries(app, run_id)
    assert (d.status, d.forwarded) == (DeliveryStatus.SENT, True)


async def test_when_no_admin_can_get_the_source_message_the_channels_get_the_normal_one(app: App) -> None:
    """Three admins are tried at most (the owner first): one blocked the bot, one never started it..."""
    blocked, never_started, fourth = 401, 402, 403
    for uid in (blocked, never_started, fourth):
        await start_user(app, uid, role=Role.ADMIN)
    app.fake.add_user(blocked)
    app.fake.add_user(fourth)
    app.fake.blocked.update({(MAIN_BOT_ID, SUPER_ID), (MAIN_BOT_ID, blocked)})
    channels = await make_chats(app, 2)
    post_id = await make_post(app, text=TEXT)

    run_id = await run_post(app, post_id, channels)

    assert [len(sources(app, uid)) for uid in (SUPER_ID, blocked, never_started, fourth)] == [1, 1, 1, 0]
    assert not app.fake.calls_of("forwardMessage")
    ds = await deliveries(app, run_id)
    assert [(d.status, d.forwarded) for d in ds] == [(DeliveryStatus.SENT, False)] * 2
    assert [[c.method for c in app.fake.messages_to(d.chat_id)] for d in ds] == [["sendMessage"]] * 2


async def test_a_source_message_deleted_meanwhile_means_normal_sends(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.publisher.BATCH_SIZE", 1)
    await start_user(app, SUPER_ID, run_reports=True)
    channels = await make_chats(app, 3)
    cids = [await chat_id_of(app, pk) for pk in channels]
    post_id = await make_post(app, text=TEXT)
    forward = app.fake.m_forwardMessage

    def forward_then_delete(token: str, p: dict[str, Any]) -> dict[str, Any]:
        out = forward(token, p)
        app.fake.private_messages[int(p["from_chat_id"])].pop(int(p["message_id"]))  # the owner deleted it
        return out

    monkeypatch.setattr(app.fake, "m_forwardMessage", forward_then_delete)

    run_id = await run_post(app, post_id, channels)

    assert [len(forwards_to(app, cid)) for cid in cids] == [1, 1, 0]  # the next chats don't try it again
    assert [len(app.fake.messages_to(cid)) for cid in cids] == [0, 1, 1]
    ds = await deliveries(app, run_id)
    assert [(d.status, d.forwarded) for d in ds] == [(DeliveryStatus.SENT, True), (DeliveryStatus.SENT, False),
                                                     (DeliveryStatus.SENT, False)]
    assert len(sources(app)) == 1
    assert dm_texts(app, SUPER_ID)[-1].endswith("emojis premium: 1 de 3 canales · 👥 Grupos: 0")  # what was forwarded


async def test_a_forward_refused_by_the_chat_is_its_usual_failure(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.publisher.BATCH_SIZE", 1)  # the failing channel goes first
    bad, good = await make_chats(app, 2)
    bad_id, good_id = await chat_id_of(app, bad), await chat_id_of(app, good)
    app.fake.chats[bad_id].bot_admin[MAIN_BOT_ID] = {**ADMIN_RIGHTS_FULL, "can_post_messages": False}
    post_id = await make_post(app, text=TEXT)

    run_id = await run_post(app, post_id, [bad, good])

    ds = {d.chat_pk: d for d in await deliveries(app, run_id)}
    assert (ds[bad].status, ds[bad].forwarded) == (DeliveryStatus.FAILED, False)
    assert (ds[good].status, ds[good].forwarded) == (DeliveryStatus.SENT, True)  # the source message is fine
    assert forwards_to(app, bad_id) and forwards_to(app, good_id)
    assert app.fake.calls_of("sendMessage", chat_id=bad_id)  # the normal send failed too: the chat's problem
    assert not app.fake.messages_to(good_id)
    chat = await get(app, Chat, bad)
    assert (chat.rights_ok, chat.missing_rights) == (False, "can_post_messages")
    [src] = sources(app)
    assert_dropped(app, SUPER_ID, src)


async def test_a_cancelled_run_deletes_its_source_message(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.publisher.BATCH_SIZE", 1)
    channels = await make_chats(app, 2)
    cids = [await chat_id_of(app, pk) for pk in channels]
    post_id = await make_post(app, text=TEXT)
    forward = app.fake.m_forwardMessage

    async def forward_then_pause(token: str, p: dict[str, Any]) -> dict[str, Any]:
        out = forward(token, p)
        await set_bot(app, paused=True)  # ⏸ Pausar todo while the run is going
        return out

    monkeypatch.setattr(app.fake, "m_forwardMessage", forward_then_pause)

    run_id = await run_post(app, post_id, channels)

    assert (await get(app, Run, run_id)).status == RunStatus.CANCELLED
    assert [len(forwards_to(app, cid)) for cid in cids] == [1, 0]
    [src] = sources(app)
    assert_dropped(app, SUPER_ID, src)


async def test_a_clone_sends_the_source_to_its_owner_and_uploads_the_media_once(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_cine_bot", OWNER2_ID)
    channels = await make_chats(app, 2, bot_id=CLONE_ID)
    [group] = await make_chats(app, bot_id=CLONE_ID, type=ChatType.GROUP, title="Grupo de Cine")
    cids = [await chat_id_of(app, pk) for pk in channels]
    gid = await chat_id_of(app, group)
    app.fake.files["PHOTO_MAIN"] = b"\x89PNG fake image"
    post_id = await make_post(app, bot_id=CLONE_ID, kind="photo", text=TEXT, media={str(MAIN_BOT_ID): "PHOTO_MAIN"})

    run_id = await run_post(app, post_id, [*channels, group])

    [src] = app.fake.calls_of("sendPhoto", chat_id=OWNER2_ID)  # the clone's owner
    assert (src.params["photo"], src.params["caption"]) == ("upl1", TEXT)
    assert not app.fake.calls_of("sendPhoto", chat_id=SUPER_ID)
    assert [[origin_of(c) for c in forwards_to(app, cid)] for cid in cids] == [[(OWNER2_ID, mid_of(src))]] * 2
    assert [c.params["photo"] for c in app.fake.messages_to(gid)] == ["upl1"]  # the file id of that upload
    assert [k for k in app.fake.files if k.startswith("upl")] == ["upl1"]  # uploaded once
    assert (await get(app, Post, post_id)).media == {str(MAIN_BOT_ID): "PHOTO_MAIN", str(CLONE_ID): "upl1"}
    ds = await deliveries(app, run_id)
    assert [(d.status, d.forwarded) for d in ds] == [(DeliveryStatus.SENT, True)] * 2 + [(DeliveryStatus.SENT, False)]
    out = app.fake.chats[cids[0]].messages[ds[0].message_id]
    assert out["photo"][0]["file_id"] == "upl1" and out["caption_entities"][0]["type"] == "custom_emoji"
    assert app.fake.calls_of("deleteMessage", chat_id=OWNER2_ID, message_id=mid_of(src))
    assert mid_of(src) not in app.fake.private_messages[OWNER2_ID]


# ------------------------------------------------------------------ reports
async def test_the_run_report_tells_what_was_forwarded(app: App) -> None:
    await start_user(app, SUPER_ID, run_reports=True)
    channels = await make_chats(app, 2)
    [group] = await make_chats(app, type=ChatType.GROUP, title="Grupo de Cine")
    post_id = await make_post(app, text=TEXT)

    await run_post(app, post_id, [*channels, group])

    assert dm_texts(app, SUPER_ID)[-1] == ("📤 <b>Promo Cine</b> enviado a 3/3 chats.\n"
                                           "💎 Reenviado para conservar los emojis premium: 2 de 2 canales · "
                                           "👥 Grupos: 1")

    app.fake.premium_owners = False  # nothing forwarded: no 💎 line
    await run_post(app, post_id, [*channels, group])

    assert dm_texts(app, SUPER_ID)[-1] == "📤 <b>Promo Cine</b> enviado a 3/3 chats."


# ------------------------------------------------------------------ updates
async def test_update_live_replaces_the_forwards_and_edits_the_groups(app: App) -> None:
    [channel] = await make_chats(app)
    [group] = await make_chats(app, type=ChatType.GROUP, title="Grupo de Cine")
    cid, gid = await chat_id_of(app, channel), await chat_id_of(app, group)
    post_id = await make_post(app, text=TEXT, pin=True, delete_after=60)
    run_id = await run_post(app, post_id, [channel, group])
    old = {d.chat_pk: d for d in await deliveries(app, run_id)}
    assert old[channel].forwarded and old[channel].pinned and old[group].pinned

    new_text = TEXT + " y adiós"
    await set_text(app, post_id, new_text)
    before = utcnow()

    assert await app.publisher.update_live(post_id) == (2, 0)

    ds = {d.chat_pk: d for d in await deliveries(app, run_id)}
    ch = ds[channel]
    first, second = sources(app)  # a new source message, with the new text
    assert second.params["text"] == new_text and mid_of(second) != mid_of(first)
    _, fwd = forwards_to(app, cid)
    assert origin_of(fwd) == (SUPER_ID, mid_of(second))
    [delete] = app.fake.calls_of("deleteMessage", chat_id=cid, message_id=old[channel].message_id)
    assert app.fake.calls.index(delete) < app.fake.calls.index(fwd)  # the old one goes first: never two copies
    assert_dropped(app, SUPER_ID, second)
    assert ch.message_id != old[channel].message_id
    assert list(app.fake.chats[cid].messages) == [ch.message_id]
    out = app.fake.chats[cid].messages[ch.message_id]
    assert out["text"] == new_text and out["entities"][0]["type"] == "custom_emoji"
    assert (ch.status, ch.forwarded, ch.pinned) == (DeliveryStatus.SENT, True, True)
    assert ch.sent_at >= before - timedelta(seconds=1) and ch.delete_at == ch.sent_at + timedelta(minutes=60)
    pin = app.fake.calls_of("pinChatMessage", chat_id=cid, message_id=ch.message_id)[0]
    assert is_true(pin.params["disable_notification"])
    assert app.fake.chats[cid].pinned[-1] == ch.message_id
    assert not app.fake.calls_of("editMessageText", chat_id=cid)

    gr = ds[group]
    assert (gr.message_id, gr.sent_at, gr.forwarded, gr.pinned) == (old[group].message_id, old[group].sent_at,
                                                                    False, True)
    assert app.fake.calls_of("editMessageText", chat_id=gid, message_id=gr.message_id)
    assert app.fake.chats[gid].messages[gr.message_id]["text"] == new_text
    assert not app.fake.calls_of("deleteMessage", chat_id=gid)
    assert not app.fake.calls_of("forwardMessage", chat_id=gid)


async def test_update_live_in_a_channel_follows_the_custom_emoji(app: App) -> None:
    [channel] = await make_chats(app)
    cid = await chat_id_of(app, channel)
    post_id = await make_post(app)  # no custom emoji: a normal message
    run_id = await run_post(app, post_id, [channel])
    [first] = await deliveries(app, run_id)
    assert not first.forwarded

    await set_text(app, post_id, "🎬 Estreno mañana")
    assert await app.publisher.update_live(post_id) == (1, 0)  # still none: edited
    [same] = await deliveries(app, run_id)
    assert same.message_id == first.message_id and not sources(app)
    assert app.fake.calls_of("editMessageText", chat_id=cid, message_id=first.message_id)

    await set_text(app, post_id, TEXT)  # custom emoji now: a forward replaces it
    assert await app.publisher.update_live(post_id) == (1, 0)
    [second] = await deliveries(app, run_id)
    [src] = sources(app)
    assert second.forwarded and second.message_id != first.message_id
    assert [origin_of(c) for c in forwards_to(app, cid)] == [(SUPER_ID, mid_of(src))]
    assert first.message_id not in app.fake.chats[cid].messages
    assert_dropped(app, SUPER_ID, src)

    app.fake.premium_owners = False  # no source message can be made: a normal message replaces the forward
    await set_text(app, post_id, TEXT + " (nuevo)")
    assert await app.publisher.update_live(post_id) == (1, 0)
    [third] = await deliveries(app, run_id)
    assert not third.forwarded and third.message_id != second.message_id
    assert len(forwards_to(app, cid)) == 1
    assert second.message_id not in app.fake.chats[cid].messages
    assert app.fake.chats[cid].messages[third.message_id]["text"] == PLAIN + " (nuevo)"
    assert not app.fake.private_messages[SUPER_ID]  # the source message it tried was deleted

    assert await app.publisher.update_live(post_id) == (1, 0)  # a normal message, no source message: edited
    [fourth] = await deliveries(app, run_id)
    assert (fourth.message_id, fourth.forwarded) == (third.message_id, False)
    assert app.fake.calls_of("editMessageText", chat_id=cid, message_id=third.message_id)
    assert len(forwards_to(app, cid)) == 1


async def test_update_live_doesnt_bring_back_a_message_deleted_in_the_channel(app: App) -> None:
    [channel] = await make_chats(app)
    cid = await chat_id_of(app, channel)
    post_id = await make_post(app, text=TEXT)
    run_id = await run_post(app, post_id, [channel])
    [before] = await deliveries(app, run_id)
    app.fake.chats[cid].messages.pop(before.message_id)  # its owner deleted it

    assert await app.publisher.update_live(post_id) == (0, 1)

    [after] = await deliveries(app, run_id)
    assert after.status == DeliveryStatus.MISSING
    assert len(forwards_to(app, cid)) == 1 and not app.fake.messages_to(cid)
    assert not app.fake.private_messages[SUPER_ID]


async def test_update_live_leaves_a_message_that_cant_be_deleted(app: App) -> None:
    [channel] = await make_chats(app)
    cid = await chat_id_of(app, channel)
    post_id = await make_post(app, text=TEXT)
    run_id = await run_post(app, post_id, [channel])
    [before] = await deliveries(app, run_id)
    app.fake.fail("deleteMessage", description="Bad Request: message can't be deleted",
                  when=lambda p: p.get("chat_id") == cid)

    assert await app.publisher.update_live(post_id) == (0, 1)

    [after] = await deliveries(app, run_id)
    assert (after.message_id, after.status, after.forwarded) == (before.message_id, DeliveryStatus.SENT, True)
    assert before.message_id in app.fake.chats[cid].messages
    assert len(forwards_to(app, cid)) == 1 and not app.fake.messages_to(cid)  # never two copies
    assert not app.fake.private_messages[SUPER_ID]


async def test_update_live_reports_a_replacement_that_could_not_be_sent(app: App) -> None:
    """The old message goes first (never two copies): when the new one can't be sent, the delivery is deleted."""
    [channel] = await make_chats(app)
    cid = await chat_id_of(app, channel)
    post_id = await make_post(app, text=TEXT)
    run_id = await run_post(app, post_id, [channel])
    [before] = await deliveries(app, run_id)
    for method in ("forwardMessage", "sendMessage"):
        app.fake.fail(method, description="Bad Request: CHAT_WRITE_FORBIDDEN", when=lambda p: p.get("chat_id") == cid)

    assert await app.publisher.update_live(post_id) == (0, 1)

    [after] = await deliveries(app, run_id)
    assert (after.message_id, after.status) == (before.message_id, DeliveryStatus.DELETED)
    assert before.message_id not in app.fake.chats[cid].messages
    assert len(forwards_to(app, cid)) == 2 and app.fake.calls_of("sendMessage", chat_id=cid)  # both tried
    _, second = sources(app)  # the run's source message, then the update's
    assert_dropped(app, SUPER_ID, second)
