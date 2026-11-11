"""Chats module: 📣 list, chat detail and the admins' actions, paused chats, import, message to the partners and
the workspace of a super admin."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.bot.routers.chats import ChCB
from app.db.base import utcnow
from app.db.models import BotUser, Chat, ChatOrigin, ChatStatus, Delivery, DeliveryStatus, EventKind, GroupChat, Run
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_chats_support import (  # noqa: F401  (reset_chat_caches is an autouse fixture)
    CHANNEL,
    CLONE_ID,
    CLONE_USERNAME,
    GROUP,
    add_chat,
    button,
    db_chat,
    dms,
    events_of,
    get_chat,
    is_alert,
    labels,
    last_answer,
    make_group,
    partner_chat,
    record_drops,
    reset_chat_caches,
    set_bot,
    start,
)


async def press(app: App, user_id: int, action: str, pk: int = 0, **kw: int) -> None:
    await app.press(user_id, ChCB(a=action, id=pk, **kw).pack())


# --------------------------------------------------------------------------- list
async def test_list_totals_rows_and_buttons(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    cine = await make_group(app, "Cine")
    own = await db_chat(app, CHANNEL, "Cine HD", members=12000, username="cinehd")
    async with app.db() as s:
        s.add(GroupChat(group_id=cine, chat_pk=own))
    until = utcnow() + timedelta(hours=5)
    await db_chat(app, GROUP, "Grupo Series", type="group", origin=ChatOrigin.EXTERNAL, owner=USER_ID, members=800,
                  owner_paused=True, owner_paused_until=until)
    await db_chat(app, -1003, "Pendiente", status=ChatStatus.PENDING, members=10)
    await db_chat(app, -1004, "Se fue", status=ChatStatus.LEFT)
    await db_chat(app, -1005, "Rechazado", status=ChatStatus.REJECTED)

    await app.press(SUPER_ID, "m:chats:0")
    text = app.last_text(SUPER_ID)
    assert text.startswith("📣 <b>Canales y grupos</b>\n📣 Canales: 2 · 👥 Grupos: 1 · 👤 12,810\n"
                           "🏠 Propios: 2 · 🤝 Externos: 1")
    assert '📣 <a href="https://t.me/cinehd">Cine HD</a> ✅\n   └👤 12,000 · 🏠 · 🗂 Cine' in text
    from app.ui.fmt import dt

    assert f"👥 Grupo Series ⏸\n   └👤 800 · 🤝 @pepe · hasta {dt(until, 'Europe/Madrid')}" in text
    assert "📣 Pendiente ⏳" in text
    assert "Se fue" not in text and "Rechazado" not in text
    panel = app.last_panel(SUPER_ID)
    assert button(panel, "Todos")["style"] == "primary"
    assert button(panel, "#1 📣 Cine HD")["callback_data"] == ChCB(a="op", id=own).pack()
    assert "startchannel" in button(panel, "Añadir canal")["url"]
    assert "startgroup" in button(panel, "Añadir grupo")["url"]
    assert not [label for label in labels(panel) if "Importar" in label]
    assert button(panel, "Avisar a los dueños")["callback_data"] == MenuCB(screen="partners_msg").pack()
    assert button(panel, "Solicitudes (1)")["callback_data"] == MenuCB(screen="requests").pack()
    assert labels(panel)[-1] == "🔙 Regresar"


async def test_list_filters(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await db_chat(app, CHANNEL, "Canal Uno")
    await db_chat(app, GROUP, "Canal Dos", origin=ChatOrigin.EXTERNAL, owner=USER_ID)
    await db_chat(app, -1003, "Canal Tres", admin_paused=True)
    await db_chat(app, -1004, "Canal Cuatro", rights_ok=False, missing_rights="can_post_messages")

    async def shown(flt: int) -> str:
        await press(app, SUPER_ID, "ls", f=flt)
        return app.last_text(SUPER_ID)

    text = await shown(1)
    assert "Canal Uno" in text and "Canal Tres" in text and "Canal Dos" not in text
    assert button(app.last_panel(SUPER_ID), "🏠")["style"] == "primary"
    text = await shown(2)
    assert "Canal Dos" in text and "Canal Uno" not in text
    text = await shown(3)
    assert "Canal Tres ⏸" in text and "pausado por un admin" in text and "Canal Uno" not in text
    text = await shown(4)
    assert "Canal Cuatro ⚠️" in text and "Canal Uno" not in text
    async with app.db() as s:  # nothing paused any more: an empty filter says so
        for chat in (await s.execute(select(Chat).where(Chat.admin_paused.is_(True)))).scalars():
            chat.admin_paused = False
    assert "No hay chats con este filtro" in await shown(3)


async def test_list_paginates_ten_per_page(app: App) -> None:
    await start(app, SUPER_ID)
    for i in range(12):
        await db_chat(app, -1002000000000 - i, f"Canal de Cine {i:02d}")
    await app.press(SUPER_ID, "m:chats:0")
    text = app.last_text(SUPER_ID)
    assert "10. 📣 Canal de Cine 09" in text and "11." not in text and "📄 Página 1 de 2" in text
    await app.click(SUPER_ID, "Siguiente")
    text = app.last_text(SUPER_ID)
    assert "11. 📣 Canal de Cine 10" in text and "12. 📣 Canal de Cine 11" in text and "📄 Página 2 de 2" in text
    # The page and filter are kept when a chat is opened and closed again.
    await app.click(SUPER_ID, "#11")
    await app.click(SUPER_ID, "Regresar")
    assert "📄 Página 2 de 2" in app.last_text(SUPER_ID)


async def test_empty_list_and_permissions(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await app.press(SUPER_ID, "m:chats:0")
    assert "Aún no hay canales ni grupos en la red" in app.last_text(SUPER_ID)
    assert not any("Avisar" in label for label in labels(app.last_panel(SUPER_ID)))
    await app.press(USER_ID, "m:chats:0")
    assert "No tienes permiso" in app.last_text(USER_ID)


# --------------------------------------------------------------------------- detail
async def test_chat_detail(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    cine = await make_group(app, "Cine")
    last = utcnow() - timedelta(hours=2)
    pk = await db_chat(app, CHANNEL, "Cine HD", members=12000, username="cinehd", posts_total=120, last_post_at=last)
    async with app.db() as s:
        s.add(GroupChat(group_id=cine, chat_pk=pk))
        run = Run(bot_id=MAIN_BOT_ID, post_name="Promo")
        s.add(run)
        await s.flush()
        for days in (1, 3, 10):
            s.add(Delivery(run_id=run.id, bot_id=MAIN_BOT_ID, chat_pk=pk, chat_id=CHANNEL, message_id=days,
                           status=DeliveryStatus.SENT, sent_at=utcnow() - timedelta(days=days)))
    await press(app, SUPER_ID, "op", pk)
    text = app.last_text(SUPER_ID)
    from app.ui.fmt import dt

    assert text == "\n".join([
        "📣 <b>Cine HD</b>",
        f"🆔 <code>{CHANNEL}</code>",
        "🔗 https://t.me/cinehd",
        "👤 Miembros: <b>12,000</b>",
        "🏷 Origen: 🏠 Propio",
        "📌 Estado: ✅ Recibe mensajes",
        "🗂 Grupos de canales: Cine",
        "📨 Recibidos: 120 · últimos 7 días: 2",
        f"🕐 Último: {dt(last, 'Europe/Madrid')}",
    ])
    panel = app.last_panel(SUPER_ID)
    assert labels(panel) == ["🗂 Grupos de canales", "🔄 Comprobar permisos", "⏸ Pausar", "🗑 Quitar de la red", "🚫 Bloquear",
                             "↗️ Abrir", "🔙 Regresar"]
    assert button(panel, "Abrir")["url"] == "https://t.me/cinehd"

    ext = await db_chat(app, GROUP, "Grupo Series", type="group", origin=ChatOrigin.EXTERNAL, owner=USER_ID,
                        owner_paused=True, rights_ok=False, missing_rights="can_pin_messages")
    await app.press(SUPER_ID, f"m:chat:{ext}")
    text = app.last_text(SUPER_ID)
    assert "🏷 Origen: 🤝 Externo · @pepe" in text
    assert ("📌 Estado: ⚠️ Faltan permisos: fijar mensajes · ⏸ Pausado por su asociado hasta que lo reanude"
            in text)
    assert "   └ Si lo reanudas, se anula su pausa y se le avisa." in text
    assert "⏰" not in text and "🕐 Último: —" in text
    assert labels(app.last_panel(SUPER_ID))[2:4] == ["▶️ Reanudar (anula la pausa del socio)", "⏸ Pausar"]


async def test_chat_detail_of_another_network_or_for_partners(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    await start(app, SUPER_ID, USER_ID)
    other = await db_chat(app, CHANNEL, "Ajeno", bot_id=CLONE_ID)
    await app.press(SUPER_ID, f"m:chat:{other}")
    assert "Ya no existe" in app.last_text(SUPER_ID)
    await press(app, SUPER_ID, "pz", other)
    assert is_alert(app, "Ya no existe")

    mine = await db_chat(app, GROUP, "Grupo de Pepe", type="group", origin=ChatOrigin.EXTERNAL, owner=USER_ID)
    await app.press(USER_ID, f"m:chat:{mine}")
    assert "📌 Estado: ✅ Recibe los mensajes de la red" in app.last_text(USER_ID), "partners get their own panel"
    for action in ("op", "pz", "rs", "rsy", "pr", "pry", "rm", "rmy", "bny", "gr", "up"):
        await press(app, USER_ID, action, mine)
        assert is_alert(app, "No tienes permiso"), action
    assert (await get_chat(app, GROUP)).status == ChatStatus.APPROVED


# --------------------------------------------------------------------------- groups of a chat
async def test_chat_groups_toggles(app: App) -> None:
    await start(app, SUPER_ID)
    cine = await make_group(app, "Cine")
    await make_group(app, "Estrenos", open=True)
    pk = await db_chat(app, CHANNEL, "Cine HD")
    await app.press(SUPER_ID, f"m:chat_groups:{pk}")
    text = app.last_text(SUPER_ID)
    assert text.startswith("🗂 <b>Grupos de canales</b> · Cine HD") and "🤝 abierto a externos" in text
    assert labels(app.last_panel(SUPER_ID)) == ["✖️ Cine", "✖️ Estrenos 🤝", "🔙 Regresar"]

    await app.click(SUPER_ID, "Cine")
    assert last_answer(app)["text"] == "✅ Añadido a Cine"
    assert labels(app.last_panel(SUPER_ID))[0] == "✅ Cine"
    async with app.db() as s:
        assert await s.get(GroupChat, (cine, pk)) is not None
    await app.click(SUPER_ID, "Cine")
    async with app.db() as s:
        assert await s.get(GroupChat, (cine, pk)) is None

    # A group of another network can't be used (forged button).
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    foreign = await make_group(app, "Ajeno", bot_id=CLONE_ID)
    await press(app, SUPER_ID, "gt", pk, v=foreign)
    assert is_alert(app, "Ya no existe")
    async with app.db() as s:
        assert await s.get(GroupChat, (foreign, pk)) is None


async def test_chat_groups_without_groups(app: App) -> None:
    await start(app, SUPER_ID)
    pk = await db_chat(app, CHANNEL, "Cine HD")
    await press(app, SUPER_ID, "gr", pk)
    assert "Aún no hay grupos de canales" in app.last_text(SUPER_ID)
    assert button(app.last_panel(SUPER_ID), "Grupos de canales")["callback_data"] == MenuCB(screen="groups").pack()


# --------------------------------------------------------------------------- 🔄 Comprobar
async def test_check_updates_members_and_rights(app: App) -> None:
    await start(app, SUPER_ID)
    await add_chat(app, user=SUPER_ID)
    chat = await get_chat(app)
    app.fake.chats[CHANNEL].members = 1300
    await press(app, SUPER_ID, "up", chat.id)
    text = app.last_text(SUPER_ID)
    assert text.startswith("🔄 <b>Comprobado</b>\n👤 Miembros: 1,200 → <b>1,300</b>\n🛡 Permisos: ✅")
    assert last_answer(app)["text"] == "🔄 Comprobado"

    app.fake.chats[CHANNEL].bot_admin[MAIN_BOT_ID]["can_post_messages"] = False
    await press(app, SUPER_ID, "up", chat.id)
    assert "🛡 Faltan permisos: publicar mensajes" in app.last_text(SUPER_ID)
    assert len(await events_of(app, EventKind.CHAT_RIGHTS)) == 1

    app.fake.chats[CHANNEL].bot_admin.pop(MAIN_BOT_ID)  # the bot was removed while the bot was down
    await press(app, SUPER_ID, "up", chat.id)
    assert "El bot ya no está en el chat" in app.last_text(SUPER_ID)
    assert (await get_chat(app)).status == ChatStatus.LEFT


async def test_check_admits_a_chat_that_was_waiting_for_its_rights(app: App) -> None:
    await start(app, SUPER_ID)
    from tests.test_chats_support import full_rights

    await add_chat(app, user=SUPER_ID, rights=full_rights(can_post_messages=False))
    chat = await get_chat(app)
    assert chat.status == ChatStatus.PENDING
    app.fake.chats[CHANNEL].bot_admin[MAIN_BOT_ID] = full_rights()
    await press(app, SUPER_ID, "up", chat.id)
    assert (await get_chat(app)).status == ChatStatus.APPROVED
    assert "📌 Estado: ✅ Recibe mensajes" in app.last_text(SUPER_ID)


# --------------------------------------------------------------------------- ⏸ admin pause
async def test_admin_pause_and_resume(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await press(app, SUPER_ID, "pz", chat.id)
    chat = await get_chat(app)
    assert chat.admin_paused and chat.paused_at is not None and chat.is_paused()
    assert last_answer(app)["text"] == "⏸ Pausado"
    assert "📌 Estado: ⏸ Pausado por un admin" in app.last_text(SUPER_ID)
    assert "▶️ Reanudar" in labels(app.last_panel(SUPER_ID))
    [paused] = await events_of(app, EventKind.CHAT_PAUSED)
    assert paused.data == {"by": "admin", "until": None} and paused.actor_id == SUPER_ID
    assert "⏸ La administración ha pausado la distribución en tu canal <b>Cine HD</b>." in dms(app)

    await press(app, SUPER_ID, "rs", chat.id)
    chat = await get_chat(app)
    assert not chat.admin_paused and chat.paused_at is None
    [resumed] = await events_of(app, EventKind.CHAT_RESUMED)
    assert resumed.data == {"by": "admin"}
    assert "▶️ La administración ha reanudado la distribución en tu canal <b>Cine HD</b>." in dms(app)


async def test_resuming_an_owner_pause_asks_first(app: App) -> None:
    """The admins rule over the partners: an admin may lift a partner's pause, after a confirmation (the whole flow:
    tests/test_chats_rules.py)."""
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    async with app.db() as s:
        row = await s.get(Chat, chat.id)
        row.owner_paused, row.paused_at = True, utcnow()
    await press(app, SUPER_ID, "rs", chat.id)
    assert "El dueño lo ha pausado hasta que lo reanude. Se le avisará." in app.last_text(SUPER_ID)
    assert (await get_chat(app)).owner_paused and not await events_of(app, EventKind.CHAT_RESUMED)
    await press(app, SUPER_ID, "rsy", chat.id)
    assert not (await get_chat(app)).owner_paused
    assert "▶️ La administración ha reanudado la distribución en tu canal <b>Cine HD</b>." in dms(app)
    await press(app, SUPER_ID, "rs", chat.id)
    assert is_alert(app, "ℹ️ No está pausado.")


# --------------------------------------------------------------------------- 🗑 remove / 🚫 ban
async def test_remove_from_the_network(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    drops = record_drops(app, monkeypatch)
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await press(app, SUPER_ID, "rm", chat.id)
    assert "🗑 ¿Quitar el canal <b>Cine HD</b> de la red?" in app.last_text(SUPER_ID)
    assert not drops.calls
    await app.click(SUPER_ID, "Sí, quitar")

    assert drops.calls == [chat.id] and drops.left_before == [False], "its posts are deleted before the bot leaves"
    assert app.fake.calls_of("leaveChat", chat_id=CHANNEL)
    chat = await get_chat(app)
    assert chat.status == ChatStatus.LEFT and chat.decided_by == SUPER_ID and chat.approved_at is None
    [event] = await events_of(app, EventKind.CHAT_REMOVED)
    assert event.data == {"by": "admin"} and event.actor_id == SUPER_ID
    assert "🗑 La administración ha retirado tu canal <b>Cine HD</b> de la red. El bot ha salido." in dms(app)
    assert last_answer(app)["text"] == "🗑 Cine HD se ha quitado de la red"
    assert "Canales y grupos" in app.last_text(SUPER_ID)

    # The bot's own "left" update changes nothing.
    await app.feed(app.my_chat_member_update(CHANNEL, MAIN_BOT_ID, new="left", old="administrator"))
    assert not await events_of(app, EventKind.CHAT_LEFT)

    # It can come back: a new admission (it was removed, so a network with approval asks again).
    await set_bot(app, join_open=True, join_approval=True)
    await add_chat(app)
    assert (await get_chat(app)).status == ChatStatus.PENDING


async def test_ban(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    drops = record_drops(app, monkeypatch)
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await press(app, SUPER_ID, "bn", chat.id)
    assert "🚫 ¿Bloquear el canal <b>Cine HD</b>?" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Sí, bloquear")
    assert drops.calls == [chat.id]
    chat = await get_chat(app)
    assert chat.status == ChatStatus.BANNED
    assert len(await events_of(app, EventKind.CHAT_BANNED)) == 1
    assert any("se ha bloqueado en esta red" in t for t in dms(app))

    await set_bot(app, join_open=True, join_approval=False)
    await add_chat(app)
    assert (await get_chat(app)).status == ChatStatus.BANNED
    assert dms(app)[-1] == "🚫 El canal <b>Cine HD</b> no puede volver a esta red."

    # Unbanned from its detail: it may come back (a new admission).
    await app.press(SUPER_ID, f"m:chat:{chat.id}")
    assert "📌 Estado: 🚫 Bloqueado" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Desbloquear")
    assert (await get_chat(app)).status == ChatStatus.LEFT
    await add_chat(app)
    assert (await get_chat(app)).status == ChatStatus.APPROVED


async def test_remove_a_pending_request_closes_its_notices(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    record_drops(app, monkeypatch)
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, join_open=True)
    await add_chat(app)
    chat = await get_chat(app)
    await press(app, SUPER_ID, "rmy", chat.id)
    edit = app.fake.last("editMessageReplyMarkup", chat_id=SUPER_ID)
    assert edit.params["reply_markup"]["inline_keyboard"][0][0]["text"] == "🗑 Quitada de la red · @superadmin"


# --------------------------------------------------------------------------- ⏸ paused chats
async def test_paused_screen(app: App) -> None:
    """Every pause is listed, by its owner or by an admin (more: tests/test_chats_rules.py)."""
    await start(app, SUPER_ID, USER_ID)
    since = utcnow() - timedelta(hours=1)
    until = utcnow() + timedelta(days=1)
    pk = await db_chat(app, CHANNEL, "Cine HD", origin=ChatOrigin.EXTERNAL, owner=USER_ID, owner_paused=True,
                       owner_paused_until=until, paused_at=since)
    await db_chat(app, GROUP, "Pausa vencida", origin=ChatOrigin.EXTERNAL, owner=USER_ID, owner_paused=True,
                  owner_paused_until=utcnow() - timedelta(minutes=1))
    admin = await db_chat(app, -1003, "Pausa de un admin", admin_paused=True, paused_at=since)
    await app.press(SUPER_ID, "m:paused:0")
    text = app.last_text(SUPER_ID)
    from app.ui.fmt import dt

    assert "⏸ <b>Pausados</b> (2)" in text
    assert (f"1. 📣 Cine HD\n   └🤝 @pepe · hasta {dt(until, 'Europe/Madrid')} · desde "
            f"{dt(since, 'Europe/Madrid')}") in text
    assert f"2. 📣 Pausa de un admin\n   └👮 un admin · sin fecha de fin · desde {dt(since, 'Europe/Madrid')}" in text
    assert "Pausa vencida" not in text
    panel = app.last_panel(SUPER_ID)
    assert button(panel, "#1")["callback_data"] == MenuCB(screen="chat", arg=pk).pack()
    assert button(panel, "▶️ #1")["callback_data"] == ChCB(a="pr", id=pk).pack()
    assert button(panel, "▶️ #2")["callback_data"] == ChCB(a="pr", id=admin).pack()

    async with app.db() as s:  # nothing paused any more
        for chat in (await s.execute(select(Chat))).scalars():
            chat.owner_paused, chat.admin_paused = False, False
    await app.press(SUPER_ID, "m:paused:0")
    assert app.last_text(SUPER_ID) == "⏸ <b>Pausados</b> (0)\n\n✅ No hay chats pausados."


# --------------------------------------------------------------------------- 📥 import (removed)
async def test_there_is_no_import_any_more(app: App) -> None:
    """Nothing is imported: chats join when the bot is added to them (or when it sees a post of a chat where it
    already was an admin)."""
    await start(app, SUPER_ID)
    await app.press(SUPER_ID, "m:import:0")  # a button of an old panel
    assert "Tu red de distribución" in app.last_text(SUPER_ID)


# --------------------------------------------------------------------------- 📢 message to the partners
async def test_message_to_the_partners(app: App) -> None:
    await start(app, SUPER_ID, USER_ID, OWNER2_ID)
    await partner_chat(app)
    await partner_chat(app, GROUP, "Tertulias", user=OWNER2_ID, type="supergroup")
    await db_chat(app, -1003, "Otro de Pepe", origin=ChatOrigin.EXTERNAL, owner=USER_ID)
    await db_chat(app, -1004, "Se fue", origin=ChatOrigin.EXTERNAL, owner=777, status=ChatStatus.LEFT)

    await app.press(SUPER_ID, "m:partners_msg:0")
    assert "(<b>2</b> personas)" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Hola, dueños: mañana hay novedades")
    assert "📢 Se enviará a <b>2</b> personas." in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Enviar")
    assert last_answer(app)["text"] == "📢 Enviando…"

    def report() -> bool:
        return any("Aviso a los dueños enviado" in t for t in dms(app, SUPER_ID))

    await app.wait_for(report)
    copies = app.fake.calls_of("copyMessage")
    assert sorted(c.params["chat_id"] for c in copies) == sorted([USER_ID, OWNER2_ID])
    assert all(c.params["from_chat_id"] == SUPER_ID for c in copies)
    assert "✅ Entregados: 2\n❌ Fallidos: 0\n🚫 Han bloqueado el bot: 0" in dms(app, SUPER_ID)[-1]


async def test_message_to_the_partners_without_partners(app: App) -> None:
    await start(app, SUPER_ID)
    await app.press(SUPER_ID, "m:partners_msg:0")
    assert "no hay dueños a quienes avisar" in app.last_text(SUPER_ID)
    await press(app, SUPER_ID, "bs")
    assert is_alert(app, "ya no está disponible")
    assert not app.fake.calls_of("copyMessage")


# --------------------------------------------------------------------------- workspace (🛠 Gestionar)
async def _manage_clone(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    await start(app, SUPER_ID)
    async with app.db() as s:
        bu = await s.get(BotUser, (MAIN_BOT_ID, SUPER_ID))
        bu.ws_bot_id = CLONE_ID


async def test_super_admin_manages_the_chats_of_a_clone(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    drops = record_drops(app, monkeypatch)
    await _manage_clone(app)
    await add_chat(app, GROUP, "Grupo Principal", user=SUPER_ID, type="supergroup")  # the main bot's own network
    await start(app, OWNER2_ID, bot_id=CLONE_ID)
    await add_chat(app, user=OWNER2_ID, bot_id=CLONE_ID)
    clone_chat = await get_chat(app, CHANNEL, CLONE_ID)
    assert clone_chat.status == ChatStatus.APPROVED and clone_chat.bot_id == CLONE_ID

    await app.press(SUPER_ID, "m:chats:0")
    text = app.last_text(SUPER_ID)
    assert text.startswith("🛠 Gestionando <b>@clon_cine_bot</b>")
    assert "Cine HD" in text and "Grupo Principal" not in text
    add = button(app.last_panel(SUPER_ID), "Añadir canal")["url"]
    assert add.startswith(f"https://t.me/{CLONE_USERNAME}?startchannel")

    await app.click(SUPER_ID, "#1 📣 Cine HD")
    assert "📣 <b>Cine HD</b>" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Quitar de la red")
    await app.click(SUPER_ID, "Sí, quitar")
    assert drops.calls == [clone_chat.id]
    clone_token = next(tok for tok, b in app.fake.bots.items() if b["id"] == CLONE_ID)
    [leave] = app.fake.calls_of("leaveChat", chat_id=CHANNEL)
    assert leave.token == clone_token, "chat calls go through the managed bot"
    assert (await get_chat(app, CHANNEL, CLONE_ID)).status == ChatStatus.LEFT
    assert (await get_chat(app, GROUP)).status == ChatStatus.APPROVED
    # The removal alert reaches the clone's owner through the clone.
    assert any("de la red. El bot ha salido" in t for t in dms(app, OWNER2_ID, clone_token))


async def test_message_to_the_partners_of_a_managed_clone(app: App) -> None:
    await _manage_clone(app)
    await start(app, USER_ID, bot_id=CLONE_ID)
    await partner_chat(app, user=USER_ID, bot_id=CLONE_ID)
    await app.press(SUPER_ID, "m:partners_msg:0")
    await app.send(SUPER_ID, "Aviso para los dueños", entities=[{"type": "bold", "offset": 0, "length": 5}])
    await app.click(SUPER_ID, "Enviar")
    clone_token = next(tok for tok, b in app.fake.bots.items() if b["id"] == CLONE_ID)

    def sent() -> bool:
        return any("<b>Aviso</b> para los dueños" in t for t in dms(app, USER_ID, clone_token)) and \
            any("Aviso a los dueños enviado" in t for t in dms(app, SUPER_ID))

    await app.wait_for(sent)
    assert not app.fake.calls_of("copyMessage"), "the clone can't copy a message of the main bot's chat"
    main_token = next(tok for tok, b in app.fake.bots.items() if b["id"] == MAIN_BOT_ID)
    assert any("Entregados: 1" in t for t in dms(app, SUPER_ID, main_token))
