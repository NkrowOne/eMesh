"""Chats module: admin decisions on requests (notices, the requests list, a chat's detail)."""
from __future__ import annotations

from sqlalchemy import select

from app.db.models import ChatOrigin, ChatStatus, EventKind, RequestNotice
from app.services.chats import SRC_CHAT, RqCB
from tests.conftest import OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_chats_support import (  # noqa: F401  (reset_chat_caches is an autouse fixture)
    CHANNEL,
    GROUP,
    add_chat,
    button,
    db_chat,
    dms,
    events_of,
    full_rights,
    get_chat,
    is_alert,
    labels,
    last_answer,
    make_admin,
    notices,
    press_notice,
    reset_chat_caches,
    set_bot,
    start,
)


async def _request(app: App, *admins: int) -> None:
    await start(app, SUPER_ID, USER_ID, *admins)
    for uid in admins:
        await make_admin(app, uid)
    await set_bot(app, join_open=True)
    await add_chat(app)


def _closed(app: App, user_id: int, message_id: int) -> dict:
    edits = [c for c in app.fake.calls_of("editMessageReplyMarkup", chat_id=user_id)
             if c.params["message_id"] == message_id]
    assert edits, f"the notice {message_id} of {user_id} was not closed"
    [[closed]] = edits[-1].params["reply_markup"]["inline_keyboard"]
    return closed


async def test_accept_from_a_notice_closes_every_notice(app: App) -> None:
    await _request(app, OWNER2_ID)
    [mine] = notices(app, SUPER_ID)
    [theirs] = notices(app, OWNER2_ID)

    await press_notice(app, "Aceptar")
    chat = await get_chat(app)
    assert chat.status == ChatStatus.APPROVED and chat.decided_by == SUPER_ID and chat.approved_at
    assert last_answer(app)["text"] == "✅ Solicitud aceptada"
    for uid, notice in ((SUPER_ID, mine), (OWNER2_ID, theirs)):
        closed = _closed(app, uid, notice.result["message_id"])
        assert closed["text"] == "✅ Aceptada · @superadmin" and "disabled" in closed
    async with app.db() as s:
        assert (await s.execute(select(RequestNotice))).first() is None
    assert any("✅ <b>Solicitud aceptada</b>" in t and "Tu canal <b>Cine HD</b> se ha unido a la red" in t
               for t in dms(app))
    [joined] = await events_of(app, EventKind.CHAT_JOINED)
    assert joined.actor_id == SUPER_ID
    assert any("se ha unido a la red (aceptado por @superadmin)" in t for t in dms(app, OWNER2_ID)), "the other admins are told"

    # The other admin presses their old notice: nothing changes.
    await app.press(OWNER2_ID, button(theirs, "Rechazar")["callback_data"], theirs.result["message_id"])
    assert is_alert(app, "Esta solicitud ya está resuelta: ✅ Recibe mensajes")
    assert (await get_chat(app)).status == ChatStatus.APPROVED


async def test_reject_with_a_reason(app: App) -> None:
    await _request(app, OWNER2_ID)
    notice = notices(app)[-1]
    await press_notice(app, "Rechazar")
    prompt = app.fake.calls_of("sendMessage", chat_id=SUPER_ID)[-1]
    assert "❌ <b>Rechazar solicitud</b> · Cine HD" in prompt.params["text"]
    assert button(prompt, "Rechazar sin motivo") and button(prompt, "Cancelar")
    assert (await get_chat(app)).status == ChatStatus.PENDING

    await app.send(SUPER_ID, "x" * 501)  # too long: asked again
    assert "Envía el motivo como texto (máximo 500 caracteres)" in app.last_text(SUPER_ID)
    assert (await get_chat(app)).status == ChatStatus.PENDING

    await app.send(SUPER_ID, "El canal no tiene contenido propio")
    chat = await get_chat(app)
    assert chat.status == ChatStatus.REJECTED and chat.reject_reason == "El canal no tiene contenido propio"
    assert chat.decided_by == SUPER_ID
    assert ("❌ La solicitud de tu canal <b>Cine HD</b> para unirse a la red no se ha aceptado.\n"
            "📝 Motivo: El canal no tiene contenido propio") in dms(app)
    assert app.fake.calls_of("leaveChat", chat_id=CHANNEL)
    assert _closed(app, SUPER_ID, notice.result["message_id"])["text"] == "❌ Rechazada · @superadmin"
    assert _closed(app, OWNER2_ID, notices(app, OWNER2_ID)[-1].result["message_id"])["text"] == \
        "❌ Rechazada · @superadmin"
    assert "❌ Se ha rechazado la solicitud del canal <b>Cine HD</b>." in app.last_text(SUPER_ID)
    [event] = await events_of(app, EventKind.CHAT_REJECTED)
    assert event.data == {"reason": "El canal no tiene contenido propio"}

    # The next message of the admin is no reason any more.
    await app.send(SUPER_ID, "hola")
    assert (await get_chat(app)).reject_reason == "El canal no tiene contenido propio"


async def test_reject_without_a_reason(app: App) -> None:
    await _request(app)
    await press_notice(app, "Rechazar")
    await app.click(SUPER_ID, "Rechazar sin motivo")
    chat = await get_chat(app)
    assert chat.status == ChatStatus.REJECTED and chat.reject_reason is None
    rejected = [t for t in dms(app) if "no se ha aceptado" in t]
    assert rejected and "Motivo" not in rejected[-1]
    assert app.fake.calls_of("leaveChat", chat_id=CHANNEL)

    # A rejected chat can ask again: adding the bot again is a new request.
    await add_chat(app)
    assert (await get_chat(app)).status == ChatStatus.PENDING and len(notices(app)) == 2


async def test_reject_prompt_can_be_cancelled(app: App) -> None:
    await _request(app)
    await press_notice(app, "Rechazar")
    await app.click(SUPER_ID, "Cancelar")
    await app.send(SUPER_ID, "no era un motivo")
    assert (await get_chat(app)).status == ChatStatus.PENDING


async def test_requests_screen_and_decisions_from_the_list(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True)
    await add_chat(app, username="cinehd")
    await add_chat(app, GROUP, "Tertulias", type="supergroup", rights=full_rights(can_pin_messages=False))

    await app.press(SUPER_ID, "m:requests:0")
    text = app.last_text(SUPER_ID)
    assert "⏳ <b>Solicitudes pendientes</b> (2)" in text
    assert '1. 📣 <a href="https://t.me/cinehd">Cine HD</a>\n   └👤 1,200 · 🤝 @pepe' in text
    assert '2. 👥 <a href="https://t.me/+1001000000002x1">Tertulias</a> ⚠️\n   └👤 1,200 · 🤝 @pepe' in text
    panel = app.last_panel(SUPER_ID)
    assert labels(panel)[:3] == ["#1 📣 Cine HD", "✅", "❌"]
    assert button(panel, "✅")["style"] == "success"

    await app.press(SUPER_ID, button(panel, "✅")["callback_data"])
    assert (await get_chat(app)).status == ChatStatus.APPROVED
    assert "(1)" in app.last_text(SUPER_ID) and "Tertulias" in app.last_text(SUPER_ID)

    await app.press(SUPER_ID, button(app.last_panel(SUPER_ID), "❌")["callback_data"])
    assert "Rechazar solicitud" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Sin temática de cine")
    assert (await get_chat(app, GROUP)).status == ChatStatus.REJECTED
    assert "✅ No hay solicitudes pendientes." in app.last_text(SUPER_ID)


async def test_accept_from_the_chat_detail(app: App) -> None:
    await _request(app)
    chat = await get_chat(app)
    await app.press(SUPER_ID, f"m:chat:{chat.id}")
    panel = app.last_panel(SUPER_ID)
    assert "📌 Estado: ⏳ Pendiente de aprobación" in app.last_text(SUPER_ID)
    assert button(panel, "Aceptar")["callback_data"] == RqCB(a="ok", pk=chat.id, s=SRC_CHAT).pack()
    await app.press(SUPER_ID, button(panel, "Aceptar")["callback_data"])
    assert (await get_chat(app)).status == ChatStatus.APPROVED
    assert "📌 Estado: ✅ Recibe mensajes" in app.last_text(SUPER_ID)


async def test_partners_cant_decide_requests(app: App) -> None:
    await _request(app)
    chat = await get_chat(app)
    for action in ("ok", "no", "nr"):
        await app.press(USER_ID, RqCB(a=action, pk=chat.id).pack())
        assert is_alert(app, "No tienes permiso")
    await app.press(USER_ID, "m:requests:0")
    assert "No tienes permiso" in app.last_text(USER_ID)
    assert (await get_chat(app)).status == ChatStatus.PENDING


async def test_requests_of_another_network_are_out_of_reach(app: App) -> None:
    await app.add_clone(7_000_000_031, "otra_red_bot", OWNER2_ID)
    await start(app, SUPER_ID)
    pk = await db_chat(app, -1009, "Ajeno", bot_id=7_000_000_031, origin=ChatOrigin.EXTERNAL,
                       status=ChatStatus.PENDING, owner=USER_ID)
    await app.press(SUPER_ID, RqCB(a="ok", pk=pk).pack())
    assert is_alert(app, "Ya no existe")
    async with app.db() as s:
        from app.db.models import Chat

        assert (await s.get(Chat, pk)).status == ChatStatus.PENDING
