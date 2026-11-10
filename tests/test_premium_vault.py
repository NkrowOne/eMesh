"""💎 Premium emoji in channels: the canal almacén (prepare the message, the admin forwards it there, the bot links
it to the post), the `post_premium` screen and what the other screens say about it."""
from __future__ import annotations

import time
from typing import Any

from app.bot.routers.premium import PmCB
from app.db.models import Chat, ChatOrigin, Post
from app.services import content
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, SUPER_ID, App
from tests.test_posts_helpers import add_chat, add_post, answers, button_texts, load, open_menu, started

EMOJI_ID = "5368324170671202286"
PREMIUM = f'<tg-emoji emoji-id="{EMOJI_ID}">🔥</tg-emoji> <b>Estreno</b> esta semana'
BUTTONS = [[{"text": "Web", "url": "https://example.com"}]]
VAULT = -100_900_001
OTHER = -100_900_002


async def channel(app: App, chat_id: int, title: str, **values: Any) -> int:
    app.fake.add_chat(chat_id, title, type="channel", admin_bots={MAIN_BOT_ID: "full"})
    return await add_chat(app, chat_id, title, **values)


async def premium_post(app: App, **values: Any) -> int:
    return await add_post(app, text=PREMIUM, buttons=BUTTONS, **values)


async def prepare(app: App, pid: int) -> dict[str, Any]:
    """📨 Preparar para reenviar: returns the message the bot sent to the admin."""
    await app.press(SUPER_ID, PmCB(a="prep", id=pid).pack())
    sent = [c for c in app.fake.calls_of("sendMessage") if c.params.get("chat_id") == SUPER_ID
            and "tg-emoji" in str(c.params.get("text"))]
    assert sent, "the premium message was not sent"
    return sent[-1].result


def forward_of(app: App, chat_id: int, sent: dict[str, Any], *, buttons: bool = True, emoji: bool = True,
               bot_id: int = MAIN_BOT_ID) -> dict[str, Any]:
    """The admin forwarded ``sent`` to ``chat_id``: the channel post the bot receives (also stored in the fake)."""
    extra: dict[str, Any] = {"forward_origin": {"type": "user", "sender_user": app.bot_user_json(bot_id),
                                                "date": sent["date"]}}
    if emoji:
        extra["entities"] = [{"type": "custom_emoji", "offset": 0, "length": 2, "custom_emoji_id": EMOJI_ID}]
    if buttons and sent.get("reply_markup"):
        extra["reply_markup"] = sent["reply_markup"]
    update = app.channel_post_update(chat_id, "🔥 Estreno esta semana", **extra)
    msg = update["channel_post"]
    app.fake.chats[chat_id].messages[msg["message_id"]] = msg
    return update


async def dm_texts(app: App) -> list[str]:
    return [str(c.params.get("text")) for c in app.fake.calls_of("sendMessage") if c.params.get("chat_id") == SUPER_ID]


# --------------------------------------------------------------------------- the whole flow
async def test_prepare_and_forward_links_the_copy_and_the_vault(app: App) -> None:
    vault_pk = await channel(app, VAULT, "Almacén")
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post_premium", pid)
    assert "Falta prepararlo" in app.last_text(SUPER_ID)

    sent = await prepare(app, pid)
    assert sent["chat"]["id"] == SUPER_ID and "protect_content" not in app.fake.calls_of("sendMessage")[-2].params
    assert "Ahora reenvía el mensaje de arriba" in app.last_text(SUPER_ID)

    update = forward_of(app, VAULT, sent)
    await app.feed(update)
    post = await load(app, Post, pid)
    assert (post.vault_chat_id, post.vault_msg_id) == (VAULT, update["channel_post"]["message_id"])
    assert post.vault_sig == content.signature(post) and content.vault_copy(post) == (VAULT, post.vault_msg_id)
    assert (await load(app, Chat, vault_pk)).vault
    texts = await dm_texts(app)
    assert any("listo" in t and "Almacén" in t for t in texts)
    assert any("es ahora tu canal almacén" in t for t in texts)

    await open_menu(app, SUPER_ID, "post", pid)
    assert "Premium en canales: ✅ listo" in app.last_text(SUPER_ID)
    await open_menu(app, SUPER_ID, "chat", vault_pk)
    assert "Canal almacén" in app.last_text(SUPER_ID)


async def test_a_new_copy_replaces_the_old_one(app: App) -> None:
    await channel(app, VAULT, "Almacén", vault=True)
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    first = forward_of(app, VAULT, await prepare(app, pid))
    await app.feed(first)
    old_id = first["channel_post"]["message_id"]
    second = forward_of(app, VAULT, await prepare(app, pid))
    await app.feed(second)
    assert (await load(app, Post, pid)).vault_msg_id == second["channel_post"]["message_id"]
    assert app.fake.calls_of("deleteMessage", chat_id=VAULT, message_id=old_id)


async def test_missing_buttons_are_put_back_on_the_copy(app: App) -> None:
    await channel(app, VAULT, "Almacén", vault=True)
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    update = forward_of(app, VAULT, await prepare(app, pid), buttons=False)
    await app.feed(update)
    mid = update["channel_post"]["message_id"]
    call = app.fake.calls_of("editMessageReplyMarkup", chat_id=VAULT, message_id=mid)
    assert call and "example.com" in str(call[-1].params.get("reply_markup"))
    assert (await load(app, Post, pid)).vault_msg_id == mid


async def test_buttons_that_cant_be_put_back_leave_the_post_as_it_was(app: App) -> None:
    await channel(app, VAULT, "Almacén", vault=True)
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    app.fake.fail("editMessageReplyMarkup", description="Bad Request: message can't be edited")
    update = forward_of(app, VAULT, await prepare(app, pid), buttons=False)
    await app.feed(update)
    assert (await load(app, Post, pid)).vault_msg_id is None
    assert any("los botones no han llegado" in t for t in await dm_texts(app))
    assert app.fake.calls_of("deleteMessage", chat_id=VAULT, message_id=update["channel_post"]["message_id"])


async def test_copies_without_the_custom_emoji_are_not_used(app: App) -> None:
    await channel(app, VAULT, "Almacén", vault=True)
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    await app.feed(forward_of(app, VAULT, await prepare(app, pid), emoji=False))
    assert (await load(app, Post, pid)).vault_msg_id is None
    assert any("los emojis premium no han llegado" in t for t in await dm_texts(app))


# --------------------------------------------------------------------------- forwards that can't be used
async def test_a_partner_channel_cant_be_the_vault(app: App) -> None:
    pk = await channel(app, OTHER, "Canal de un socio", origin=ChatOrigin.EXTERNAL, owner_user_id=444)
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    update = forward_of(app, OTHER, await prepare(app, pid))
    await app.feed(update)
    assert (await load(app, Post, pid)).vault_msg_id is None
    assert not (await load(app, Chat, pk)).vault
    assert any("no sirve como canal almacén" in t for t in await dm_texts(app))
    assert not app.fake.calls_of("deleteMessage", chat_id=OTHER)  # a partner's channel is left alone


async def test_a_forward_to_another_own_channel_is_refused_while_there_is_a_vault(app: App) -> None:
    await channel(app, VAULT, "Almacén", vault=True)
    other_pk = await channel(app, OTHER, "Canal de Cine")
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    update = forward_of(app, OTHER, await prepare(app, pid))
    await app.feed(update)
    assert (await load(app, Post, pid)).vault_msg_id is None
    assert not (await load(app, Chat, other_pk)).vault
    assert any("tu canal almacén es <b>Almacén</b>" in t for t in await dm_texts(app))
    assert app.fake.calls_of("deleteMessage", chat_id=OTHER, message_id=update["channel_post"]["message_id"])


async def test_a_post_changed_after_preparing_it_is_not_linked(app: App) -> None:
    await channel(app, VAULT, "Almacén", vault=True)
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    sent = await prepare(app, pid)
    async with app.db() as s:
        (await s.get(Post, pid)).text = PREMIUM + " (nuevo)"
    await app.feed(forward_of(app, VAULT, sent))
    assert (await load(app, Post, pid)).vault_msg_id is None
    assert any("ha cambiado o ya no existe" in t for t in await dm_texts(app))


async def test_other_forwards_are_ignored(app: App) -> None:
    await channel(app, VAULT, "Almacén", vault=True)
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    before = len(await dm_texts(app))
    fake_sent = {"date": int(time.time()) - 3600, "reply_markup": None}  # never prepared
    await app.feed(forward_of(app, VAULT, fake_sent))
    assert (await load(app, Post, pid)).vault_msg_id is None
    assert len(await dm_texts(app)) == before


async def test_a_forward_is_used_once(app: App) -> None:
    await channel(app, VAULT, "Almacén", vault=True)
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    sent = await prepare(app, pid)
    first = forward_of(app, VAULT, sent)
    await app.feed(first)
    await app.feed(forward_of(app, VAULT, sent))  # the same message forwarded again
    assert (await load(app, Post, pid)).vault_msg_id == first["channel_post"]["message_id"]


# --------------------------------------------------------------------------- the screen
async def test_without_premium_owner_nothing_is_prepared(app: App) -> None:
    app.fake.premium_owners = False
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, PmCB(a="prep", id=pid).pack())
    assert any("no tiene Telegram Premium" in a for a in answers(app))
    assert app.fake.calls_of("deleteMessage", chat_id=SUPER_ID)


async def test_posts_without_premium_emoji_dont_offer_it(app: App) -> None:
    pid = await add_post(app)
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post", pid)
    assert "Premium en canales" not in app.last_text(SUPER_ID)
    assert not any("Premium en canales" in b for b in button_texts(app))
    await app.press(SUPER_ID, PmCB(a="prep", id=pid).pack())
    assert any("no tiene emojis premium" in a for a in answers(app))


async def test_the_detail_offers_it_and_says_when_it_is_stale(app: App) -> None:
    await channel(app, VAULT, "Almacén", vault=True)
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post", pid)
    assert "Premium en canales: ⚠️ falta prepararlo" in app.last_text(SUPER_ID)
    assert MenuCB(screen="post_premium", arg=pid).pack() in str(app.last_panel(SUPER_ID).params.get("reply_markup"))
    await app.feed(forward_of(app, VAULT, await prepare(app, pid)))
    async with app.db() as s:
        (await s.get(Post, pid)).buttons = [[{"text": "Otra", "url": "https://example.org"}]]
    await open_menu(app, SUPER_ID, "post_premium", pid)
    assert "El mensaje ha cambiado" in app.last_text(SUPER_ID)


async def test_change_the_vault(app: App) -> None:
    pk = await channel(app, VAULT, "Almacén", vault=True)
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post_premium", pid)
    await app.click(SUPER_ID, "Cambiar canal almacén")
    assert "volverá a recibir los mensajes" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Sí, cambiarlo")
    assert not (await load(app, Chat, pk)).vault
    other_pk = await channel(app, OTHER, "Nuevo almacén")
    await app.feed(forward_of(app, OTHER, await prepare(app, pid)))
    assert (await load(app, Chat, other_pk)).vault
    assert (await load(app, Post, pid)).vault_chat_id == OTHER


async def test_remove_the_premium_version(app: App) -> None:
    await channel(app, VAULT, "Almacén", vault=True)
    pid = await premium_post(app)
    await started(app, SUPER_ID)
    update = forward_of(app, VAULT, await prepare(app, pid))
    await app.feed(update)
    await open_menu(app, SUPER_ID, "post_premium", pid)
    await app.click(SUPER_ID, "Quitar la versión premium")
    post = await load(app, Post, pid)
    assert post.vault_msg_id is None and content.vault_copy(post) is None
    assert app.fake.calls_of("deleteMessage", chat_id=VAULT, message_id=update["channel_post"]["message_id"])


async def test_only_admins_can_use_it(app: App) -> None:
    pid = await premium_post(app)
    await started(app, 444)
    await app.press(444, PmCB(a="prep", id=pid).pack())
    await app.press(444, PmCB(a="chg_ok", id=pid).pack())
    assert not [c for c in app.fake.calls_of("sendMessage") if c.params.get("chat_id") == 444
                and "tg-emoji" in str(c.params.get("text"))]
