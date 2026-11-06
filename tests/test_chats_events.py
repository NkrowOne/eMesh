"""Chats module: the bot added to / removed from channels and groups (``my_chat_member``), pins, migrations and the
discovery of chats where the bot already is an administrator."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from sqlalchemy import select

from app.bot.routers import chat_events
from app.db.base import utcnow
from app.db.models import (
    Chat,
    ChatGroup,
    ChatOrigin,
    ChatStatus,
    ChatType,
    Delivery,
    DeliveryStatus,
    EventKind,
    GroupChat,
    RequestNotice,
    Run,
)
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_chats_support import (  # noqa: F401  (reset_chat_caches is an autouse fixture)
    CHANNEL,
    GROUP,
    add_chat,
    button,
    chat_message_update,
    db_chat,
    dms,
    events_of,
    full_rights,
    get_chat,
    last_answer,
    make_admin,
    make_group,
    notices,
    partner_chat,
    remove_bot,
    reset_chat_caches,
    set_bot,
    start,
)


# --------------------------------------------------------------------------- own chats
async def test_admin_adds_own_channel_and_group(app: App) -> None:
    await start(app, SUPER_ID, OWNER2_ID)
    await make_admin(app, OWNER2_ID)
    await add_chat(app, user=SUPER_ID, username="cinehd")

    chat = await get_chat(app)
    assert chat is not None and chat.status == ChatStatus.APPROVED and chat.origin == ChatOrigin.OWN
    assert chat.owner_user_id == SUPER_ID and chat.rights_ok and chat.members == 1200 and chat.approved_at
    assert chat.username == "cinehd" and chat.type == ChatType.CHANNEL
    dm = app.fake.calls_of("sendMessage", chat_id=SUPER_ID)[-1]
    assert dm.params["text"] == ("✅ El canal <b>Cine HD</b> se ha añadido a la red. Recibirá los mensajes para "
                                 "🌐 Todos y 🏠 Propios.")
    assert button(dm, "Añadir a grupos de canales")["callback_data"] == MenuCB(screen="chat_groups", arg=chat.id).pack()
    [event] = await events_of(app, EventKind.CHAT_ADDED)
    assert event.chat_pk == chat.id and event.actor_id == SUPER_ID
    # The other admins are alerted; the one who added it gets the DM instead.
    assert any("se ha añadido a la red" in text and "@superadmin" in text for text in dms(app, OWNER2_ID))
    assert not any("se ha añadido a la red (" in text for text in dms(app, SUPER_ID))

    await add_chat(app, GROUP, "Tertulias de Cine", user=SUPER_ID, type="supergroup")
    group = await get_chat(app, GROUP)
    assert group.status == ChatStatus.APPROVED and group.type == ChatType.GROUP
    assert "El grupo <b>Tertulias de Cine</b> se ha añadido" in dms(app, SUPER_ID)[-1]


async def test_own_chat_without_rights_waits_then_is_approved(app: App) -> None:
    await start(app, SUPER_ID)
    await add_chat(app, user=SUPER_ID, rights=full_rights(can_post_messages=False, can_delete_messages=False))
    chat = await get_chat(app)
    assert chat.status == ChatStatus.PENDING and not chat.rights_ok
    assert chat.missing_rights == "can_post_messages,can_delete_messages"
    dm = app.fake.calls_of("sendMessage", chat_id=SUPER_ID)[-1]
    assert "Faltan permisos en tu canal <b>Cine HD</b>" in dm.params["text"]
    assert "• publicar mensajes\n• eliminar mensajes" in dm.params["text"]
    assert button(dm, "Comprobar de nuevo")
    assert not await events_of(app, EventKind.CHAT_ADDED)

    # The rights are granted: Telegram sends the change and the chat goes on with its admission.
    await add_chat(app, user=SUPER_ID, old="administrator")
    chat = await get_chat(app)
    assert chat.status == ChatStatus.APPROVED and chat.rights_ok and chat.missing_rights == ""
    assert "se ha añadido a la red" in dms(app, SUPER_ID)[-1]
    assert len(await events_of(app, EventKind.CHAT_ADDED)) == 1


async def test_group_where_the_bot_is_only_a_member(app: App) -> None:
    await start(app, SUPER_ID)
    await add_chat(app, GROUP, "Tertulias de Cine", user=SUPER_ID, type="supergroup", new="member")
    chat = await get_chat(app, GROUP)
    assert chat.status == ChatStatus.PENDING and chat.missing_rights == "admin"
    assert "• ser administrador" in dms(app, SUPER_ID)[-1]


# --------------------------------------------------------------------------- external chats
async def test_external_chat_refused_when_the_network_is_private(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await add_chat(app)
    assert await get_chat(app) is None
    assert app.fake.calls_of("leaveChat", chat_id=CHANNEL)
    dm = app.fake.calls_of("sendMessage", chat_id=USER_ID)[-1]
    assert dm.params["text"] == "🔒 Este bot no admite canales de otras personas, así que ha salido de <b>Cine HD</b>."
    assert button(dm, "Crea tu propio bot")["callback_data"] == MenuCB(screen="clone").pack()


async def test_external_chat_without_approval_joins_at_once(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True, join_approval=False)
    cine = await make_group(app, "Cine", open=True)
    await make_group(app, "Privado")
    await add_chat(app)

    chat = await get_chat(app)
    assert chat.status == ChatStatus.APPROVED and chat.origin == ChatOrigin.EXTERNAL and chat.owner_user_id == USER_ID
    async with app.db() as s:
        rows = (await s.execute(select(GroupChat.group_id).where(GroupChat.chat_pk == chat.id))).all()
        assert [g for (g,) in rows] == [cine], "external chats join every open group"
    dm = app.fake.calls_of("sendMessage", chat_id=USER_ID)[-1]
    text = dm.params["text"]
    assert "¡Ya formas parte de la red!" in text and "Tu canal <b>Cine HD</b> se ha unido a la red de @emesh_test_bot" \
        in text
    assert "🗂 Categorías: Cine" in text and "Mis canales" in text
    assert button(dm, "Mis canales")["callback_data"] == MenuCB(screen="my_chats").pack()
    [event] = await events_of(app, EventKind.CHAT_JOINED)
    assert event.actor_id == USER_ID
    assert any("🤝 <b>Cine HD</b> se ha unido a la red (@pepe)." in t for t in dms(app, SUPER_ID))
    assert not notices(app)


async def test_external_chat_with_approval_sends_a_request(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True)
    await add_chat(app, username="cinehd")

    chat = await get_chat(app)
    assert chat.status == ChatStatus.PENDING and chat.rights_ok
    assert any("Solicitud enviada" in t and "Tu canal <b>Cine HD</b> está pendiente de aprobación" in t
               for t in dms(app))
    [notice] = notices(app)
    assert notice.params["text"] == (
        "📨 <b>Solicitud para unirse a la red</b>\n👤 @pepe\n📣 <b>Cine HD</b> · 👤 1,200\n"
        f"🆔 <code>{CHANNEL}</code> · 🔗 https://t.me/cinehd")
    assert button(notice, "Aceptar")["style"] == "success" and button(notice, "Rechazar")["style"] == "danger"
    [event] = await events_of(app, EventKind.CHAT_REQUEST)
    assert event.actor_id == USER_ID
    assert not any("quiere unirse" in t for t in dms(app, SUPER_ID)), "a request is no alert (the notice is enough)"
    async with app.db() as s:
        rows = (await s.execute(select(RequestNotice))).scalars().all()
        assert [(r.user_id, r.message_id) for r in rows] == [(SUPER_ID, notice.result["message_id"])]


async def test_external_chat_below_the_minimum_is_refused(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True, min_members=500)
    await add_chat(app, members=120)
    chat = await get_chat(app)
    assert chat.status == ChatStatus.REJECTED and chat.reject_reason == "Menos de 500 miembros (120)"
    assert ("ℹ️ Tu canal <b>Cine HD</b> necesita al menos <b>500</b> miembros para unirse a la red (ahora tiene 120). "
            "Vuelve a añadir el bot cuando los tenga.") in dms(app)
    assert app.fake.calls_of("leaveChat", chat_id=CHANNEL) and not notices(app)

    # Telegram reports the bot's own leave: nothing changes and nobody is told.
    await remove_bot(app, by=MAIN_BOT_ID)
    assert (await get_chat(app)).status == ChatStatus.REJECTED
    assert not await events_of(app, EventKind.CHAT_LEFT)

    # Once it has grown, adding the bot again is a new request.
    app.fake.chats[CHANNEL].members = 800
    await add_chat(app)
    assert (await get_chat(app)).status == ChatStatus.PENDING and len(notices(app)) == 1


async def test_external_chat_with_a_platform_word_is_refused(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True, join_approval=False)
    app.fake.add_chat(CHANNEL, "Cine HD", creator=USER_ID)
    app.fake.chats[CHANNEL].description = "Vídeos filtrados cada día"
    await add_chat(app)
    chat = await get_chat(app)
    assert chat.status == ChatStatus.REJECTED and app.fake.calls_of("leaveChat", chat_id=CHANNEL)
    last = dms(app)[-1]
    assert last == "🚫 Tu canal <b>Cine HD</b> no puede unirse a esta red." and "filtrad" not in last
    assert not await events_of(app, EventKind.CHAT_JOINED)


async def test_chat_limit_refuses_new_chats(app: App) -> None:
    await app.add_clone(7_000_000_021, "red_limitada_bot", OWNER2_ID)
    await set_bot(app, 7_000_000_021, limit_chats=1)
    await add_chat(app, GROUP, "Primero", user=OWNER2_ID, type="supergroup", bot_id=7_000_000_021)
    assert (await get_chat(app, GROUP, 7_000_000_021)).status == ChatStatus.APPROVED
    await add_chat(app, user=OWNER2_ID, bot_id=7_000_000_021)
    assert await get_chat(app, CHANNEL, 7_000_000_021) is None
    assert app.fake.calls_of("leaveChat", chat_id=CHANNEL)
    assert ("⚠️ La red ha llegado a su límite de 1 canales y grupos: no se ha podido añadir el canal "
            "<b>Cine HD</b>.") in dms(app, OWNER2_ID)


async def test_banned_chat_added_again_is_refused(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True, join_approval=False)
    await db_chat(app, CHANNEL, "Cine HD", origin=ChatOrigin.EXTERNAL, status=ChatStatus.BANNED, owner=USER_ID)
    await add_chat(app)
    chat = await get_chat(app)
    assert chat.status == ChatStatus.BANNED
    assert app.fake.calls_of("leaveChat", chat_id=CHANNEL)
    assert dms(app)[-1] == "🚫 El canal <b>Cine HD</b> no puede volver a esta red."
    assert sum("no puede volver" in t for t in dms(app)) == 1


async def test_external_chat_missing_rights_then_check_again(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True)
    await add_chat(app, rights=full_rights(can_edit_messages=False))
    chat = await get_chat(app)
    assert chat.status == ChatStatus.PENDING and chat.missing_rights == "can_edit_messages"
    assert "editar mensajes" in dms(app)[-1] and not notices(app), "the admins wait until the rights are fine"

    await app.click(USER_ID, "Comprobar de nuevo")
    assert last_answer(app)["text"] == "⚠️ Aún faltan permisos"
    assert "Faltan permisos en tu canal" in app.last_text(USER_ID) and not notices(app)

    app.fake.chats[CHANNEL].bot_admin[MAIN_BOT_ID] = full_rights()
    await app.click(USER_ID, "Comprobar de nuevo")
    chat = await get_chat(app)
    assert chat.status == ChatStatus.PENDING and chat.rights_ok
    assert "La solicitud está pendiente de aprobación" in app.last_text(USER_ID)
    assert any("Solicitud enviada" in t for t in dms(app)) and len(notices(app)) == 1

    # An old copy of the button doesn't send the request twice.
    old = next(c for c in app.fake.calls_of("sendMessage", chat_id=USER_ID)
               if any("Comprobar de nuevo" in b["text"] for b in App.buttons(c)))
    await app.press(USER_ID, button(old, "Comprobar de nuevo")["callback_data"], old.result["message_id"])
    assert len(notices(app)) == 1


async def test_someone_else_cant_check_a_chat(app: App) -> None:
    await start(app, SUPER_ID, USER_ID, OWNER2_ID)
    await set_bot(app, join_open=True)
    await add_chat(app, rights=full_rights(can_edit_messages=False))
    chat = await get_chat(app)
    from app.services.chats import RqCB

    await app.press(OWNER2_ID, RqCB(a="chk", pk=chat.id).pack())
    assert "Ya no existe" in last_answer(app)["text"]


# --------------------------------------------------------------------------- the bot removed, rights changed
async def test_bot_removed_marks_the_chat_left(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await remove_bot(app, by=USER_ID, new="kicked")
    chat = await get_chat(app)
    assert chat.status == ChatStatus.LEFT and not chat.rights_ok
    [event] = await events_of(app, EventKind.CHAT_LEFT)
    assert event.chat_pk == chat.id
    assert any("El bot ya no está en <b>Cine HD</b>" in t for t in dms(app, SUPER_ID))
    assert any("El bot ya no está en tu canal <b>Cine HD</b>" in t for t in dms(app))

    # Back after an accident: it was accepted before, so it enters again directly (no new request).
    await set_bot(app, join_open=True, join_approval=True)
    await add_chat(app)
    chat = await get_chat(app)
    assert chat.status == ChatStatus.APPROVED and not notices(app)


async def test_pending_request_closed_when_the_bot_is_removed(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True)
    await add_chat(app)
    notice = notices(app)[-1]
    await remove_bot(app)
    assert (await get_chat(app)).status == ChatStatus.LEFT
    edit = app.fake.last("editMessageReplyMarkup", chat_id=SUPER_ID)
    assert edit.params["message_id"] == notice.result["message_id"]
    [[closed]] = edit.params["reply_markup"]["inline_keyboard"]
    assert closed["text"] == "🚪 El bot ya no está en el chat" and "disabled" in closed


async def test_rights_lost_and_back(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await partner_chat(app)
    await add_chat(app, old="administrator", rights=full_rights(can_post_messages=False))
    chat = await get_chat(app)
    assert chat.status == ChatStatus.APPROVED and not chat.rights_ok and chat.missing_rights == "can_post_messages"
    [lost] = await events_of(app, EventKind.CHAT_RIGHTS)
    assert lost.data == {"missing": "can_post_messages"}
    assert any("Al bot le faltan permisos en tu canal" in t for t in dms(app))

    await add_chat(app, old="administrator")
    chat = await get_chat(app)
    assert chat.rights_ok and len(await events_of(app, EventKind.CHAT_RIGHTS_OK)) == 1


async def test_older_update_is_ignored(app: App) -> None:
    await start(app, SUPER_ID)
    await add_chat(app, user=SUPER_ID)
    upd = app.my_chat_member_update(CHANNEL, SUPER_ID, new="left", old="administrator")
    upd["my_chat_member"]["date"] = int(time.time()) - 3600
    await app.feed(upd)
    assert (await get_chat(app)).status == ChatStatus.APPROVED


async def test_hub_main_bot_leaves(app: App) -> None:
    app.settings.MAIN_BOT_MODE = "hub"
    await start(app, USER_ID)
    await add_chat(app)
    assert await get_chat(app) is None
    assert app.fake.calls_of("leaveChat", chat_id=CHANNEL)
    dm = app.fake.calls_of("sendMessage", chat_id=USER_ID)[-1]
    assert dm.params["text"] == "ℹ️ Este bot no distribuye mensajes. Crea tu propio bot con <b>🤖 Crear mi bot</b>."
    assert button(dm, "Crear mi bot")["callback_data"] == MenuCB(screen="clone").pack()


async def test_clone_refusal_links_to_the_main_bot(app: App) -> None:
    await app.add_clone(7_000_000_022, "red_privada_bot", OWNER2_ID)
    await start(app, USER_ID, bot_id=7_000_000_022)
    await add_chat(app, bot_id=7_000_000_022)
    dm = app.fake.calls_of("sendMessage", chat_id=USER_ID)[-1]
    assert button(dm, "Crea tu propio bot")["url"] == "https://t.me/emesh_test_bot?start=clone"


# --------------------------------------------------------------------------- pins, migrations
async def test_group_pin_of_the_bot_is_deleted(app: App) -> None:
    await start(app, SUPER_ID)
    await add_chat(app, GROUP, "Tertulias de Cine", user=SUPER_ID, type="supergroup")
    group = app.fake.chat_json(GROUP)
    ours = {"message_id": 40, "date": int(time.time()), "chat": group, "from": app.bot_user_json(), "text": "promo"}
    await app.feed(chat_message_update(app, group, 41, pinned_message=ours, **{"from": app.bot_user_json()}))
    assert app.fake.calls_of("deleteMessage", chat_id=GROUP, message_id=41)

    theirs = {**ours, "message_id": 42, "from": app._user(USER_ID)}  # noqa: SLF001
    await app.feed(chat_message_update(app, group, 43, pinned_message=theirs))
    assert not app.fake.calls_of("deleteMessage", chat_id=GROUP, message_id=43)


async def _delivery(app: App, chat_pk: int, message_id: int) -> None:
    async with app.db() as s:
        run = Run(bot_id=MAIN_BOT_ID, post_name="Promo Cine")
        s.add(run)
        await s.flush()
        s.add(Delivery(run_id=run.id, bot_id=MAIN_BOT_ID, chat_pk=chat_pk, chat_id=CHANNEL, message_id=message_id,
                       status=DeliveryStatus.SENT, sent_at=utcnow(), pinned=True))


async def test_channel_pin_of_a_live_delivery_is_deleted(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_events, "PIN_RECHECK_DELAY", 0.2)
    await start(app, SUPER_ID)
    await add_chat(app, user=SUPER_ID)
    chat = await get_chat(app)
    channel = app.fake.chat_json(CHANNEL)

    def pinned(message_id: int) -> dict[str, Any]:
        return {"message_id": message_id, "date": int(time.time()), "chat": channel, "sender_chat": channel,
                "text": "promo"}

    await _delivery(app, chat.id, 700)
    await app.feed(chat_message_update(app, channel, 701, pinned_message=pinned(700)))
    assert app.fake.calls_of("deleteMessage", chat_id=CHANNEL, message_id=701)

    # The engine had not stored the delivery yet: looked up again a moment later.
    await app.feed(chat_message_update(app, channel, 711, pinned_message=pinned(710)))
    assert not app.fake.calls_of("deleteMessage", chat_id=CHANNEL, message_id=711)
    await _delivery(app, chat.id, 710)
    await app.wait_for(lambda: app.fake.calls_of("deleteMessage", chat_id=CHANNEL, message_id=711), timeout=3)

    # A pin of the owner's own post stays.
    await app.feed(chat_message_update(app, channel, 721, pinned_message=pinned(720)))
    await asyncio.sleep(0.4)
    assert not app.fake.calls_of("deleteMessage", chat_id=CHANNEL, message_id=721)


async def test_migration_to_supergroup_updates_the_chat_id(app: App) -> None:
    await start(app, SUPER_ID)
    pk = await db_chat(app, -555, "Tertulias", type=ChatType.GROUP)
    old_group = {"id": -555, "type": "group", "title": "Tertulias"}
    await app.feed(chat_message_update(app, old_group, 9, migrate_to_chat_id=-1000000000555))
    async with app.db() as s:
        assert (await s.get(Chat, pk)).chat_id == -1000000000555

    pk2 = await db_chat(app, -556, "Tertulias 2", type=ChatType.GROUP)
    dup = await db_chat(app, -1000000000556, "Tertulias 2", status=ChatStatus.PENDING, type=ChatType.GROUP)
    new_group = {"id": -1000000000556, "type": "supergroup", "title": "Tertulias 2"}
    await app.feed(chat_message_update(app, new_group, 1, migrate_from_chat_id=-556))
    async with app.db() as s:
        kept = await s.get(Chat, pk2)
        assert kept.chat_id == -1000000000556 and kept.status == ChatStatus.APPROVED
        assert await s.get(Chat, dup) is None


# --------------------------------------------------------------------------- discovery
async def _registered(app: App, chat_id: int) -> Chat:
    async def found() -> Chat | None:
        return await get_chat(app, chat_id)

    return await app.wait_for(found)


async def test_discovery_registers_a_chat_where_the_bot_already_is_admin(app: App) -> None:
    await start(app, SUPER_ID)
    app.fake.add_chat(-1003, "Canal Antiguo", members=900, admin_bots={MAIN_BOT_ID: "full"}, creator=SUPER_ID)
    await app.feed(app.channel_post_update(-1003, "hola"))
    chat = await _registered(app, -1003)
    assert chat.status == ChatStatus.APPROVED and chat.origin == ChatOrigin.OWN
    assert chat.owner_user_id == SUPER_ID and chat.members == 900
    await app.wait_for(lambda: any("<b>Canal Antiguo</b> se ha añadido a la red" in t for t in dms(app, SUPER_ID)))

    # Looked up once: later posts of a known (or recently seen) chat cost nothing.
    calls = len(app.fake.calls_of("getChat", chat_id=-1003))
    await app.feed(app.channel_post_update(-1003, "otra"))
    await asyncio.sleep(0.1)
    assert len(app.fake.calls_of("getChat", chat_id=-1003)) == calls

    # A chat where the bot isn't admin is looked up once an hour at most.
    app.fake.add_chat(-1004, "Grupo Ajeno", type="supergroup", admin_bots={MAIN_BOT_ID: None}, creator=USER_ID)
    await app.feed(app.channel_post_update(-1004, "uno"))
    await app.wait_for(lambda: app.fake.calls_of("getChatMember", chat_id=-1004))
    await app.feed(app.channel_post_update(-1004, "dos"))
    await asyncio.sleep(0.1)
    assert await get_chat(app, -1004) is None
    assert len(app.fake.calls_of("getChat", chat_id=-1004)) == 1


async def test_discovered_partner_chat_waits_for_an_admin(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True, join_approval=False)
    app.fake.add_chat(-1005, "Canal de Pepe", admin_bots={MAIN_BOT_ID: "full"}, creator=USER_ID)
    await app.feed(app.channel_post_update(-1005))
    chat = await _registered(app, -1005)
    assert chat.status == ChatStatus.PENDING and chat.origin == ChatOrigin.EXTERNAL and chat.owner_user_id == USER_ID
    await app.wait_for(lambda: len(notices(app)) == 1)  # its owner asked for nothing now: an admin decides


async def test_bot_added_to_a_private_network_is_not_discovered(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    """The "bot joined" service message of a group arrives with the my_chat_member update: discovery must not
    register a chat that update refused."""
    monkeypatch.setattr(chat_events, "DISCOVERY_DELAY", 0.3)
    await start(app, SUPER_ID, USER_ID)
    app.fake.add_chat(GROUP, "Grupo de Pepe", type="supergroup", creator=USER_ID)
    group = app.fake.chat_json(GROUP)
    joined = chat_message_update(app, group, 5, new_chat_members=[app.bot_user_json()])
    first_post = chat_message_update(app, group, 6, text="hola")
    await asyncio.gather(app.feed(first_post), app.feed(joined), add_chat(app, GROUP, type="supergroup"))
    await asyncio.sleep(0.6)
    assert await get_chat(app, GROUP) is None, "join_open is off: the bot left and nothing was registered"
    assert app.fake.calls_of("leaveChat", chat_id=GROUP)
    assert not notices(app)


async def test_groups_kept_when_a_chat_comes_back(app: App) -> None:
    await start(app, SUPER_ID)
    await add_chat(app, user=SUPER_ID)
    chat = await get_chat(app)
    gid = await make_group(app, "Cine")
    async with app.db() as s:
        s.add(GroupChat(group_id=gid, chat_pk=chat.id))
    await remove_bot(app, by=SUPER_ID)
    assert (await get_chat(app)).status == ChatStatus.LEFT
    await add_chat(app, user=SUPER_ID)
    back = await get_chat(app)
    assert back.id == chat.id and back.status == ChatStatus.APPROVED
    async with app.db() as s:
        assert await s.get(GroupChat, (gid, chat.id)) is not None
        assert (await s.execute(select(ChatGroup))).scalars().first() is not None
