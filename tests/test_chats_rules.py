"""Chats module: the admins rule over the partners (docs/ARCHITECTURE.md, section 4). Partners pause their chats
only as the admins allow (``Bot.partners_can_pause``, ``Bot.pause_max_hours``) and the admins see every pause and can
resume any of them, from a chat's detail or from ⏸ Pausados."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.bot.routers.chats import ChCB
from app.bot.routers.partners import PaCB
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import BotUser, Chat, ChatOrigin, ChatStatus, EventKind
from app.services import chats as chat_svc
from app.ui.fmt import dt
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_chats_support import (  # noqa: F401  (reset_chat_caches is an autouse fixture)
    CHANNEL,
    CLONE_ID,
    CLONE_USERNAME,
    GROUP,
    db_chat,
    dms,
    events_of,
    get_chat,
    is_alert,
    labels,
    last_answer,
    make_admin,
    partner_chat,
    reset_chat_caches,
    set_bot,
    start,
)

TZ = "Europe/Madrid"
EXT = ChatOrigin.EXTERNAL
ALL_PAUSES = ["⏸ 1 h", "⏸ 6 h", "⏸ 24 h", "⏸ 3 días", "⏸ 7 días", "⏸ Hasta que la reanude"]
NOT_ALLOWED = "⏸ La administración no permite pausar en esta red."
LIFT = "▶️ Reanudar (anula la pausa del socio)"


async def pa(app: App, user_id: int, action: str, pk: int = 0, *, bot_id: int = MAIN_BOT_ID, **kw: int) -> None:
    await app.press(user_id, PaCB(a=action, id=pk, **kw).pack(), bot_id=bot_id)


async def ch(app: App, user_id: int, action: str, pk: int = 0, **kw: int) -> None:
    await app.press(user_id, ChCB(a=action, id=pk, **kw).pack())


def resumed_alert(chat: str, actor: str) -> str:
    return f"▶️ <b>{chat}</b>: distribución reanudada por {actor}."


def partner_told(chat: str) -> str:
    return f"▶️ La administración ha reanudado la distribución en tu canal <b>{chat}</b>."


# --------------------------------------------------------------------------- the partners' pause menu
def test_pause_allowed() -> None:
    ws = BotRecord(partners_can_pause=True, pause_max_hours=24)
    assert chat_svc.pause_allowed(ws, timedelta(hours=1)) and chat_svc.pause_allowed(ws, timedelta(hours=24))
    assert not chat_svc.pause_allowed(ws, timedelta(hours=24, minutes=1))
    assert not chat_svc.pause_allowed(ws, None), "until they resume it needs no limit"
    ws.pause_max_hours = 0
    assert chat_svc.pause_allowed(ws, None) and chat_svc.pause_allowed(ws, timedelta(days=7))
    ws.partners_can_pause = False
    assert not chat_svc.pause_allowed(ws, timedelta(hours=1)) and not chat_svc.pause_allowed(ws, None)


async def test_default_rules_allow_any_pause(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await pa(app, USER_ID, "op", chat.id)
    await app.click(USER_ID, "Pausar")
    assert "¿Cuánto tiempo?" in app.last_text(USER_ID)
    assert labels(app.last_panel(USER_ID)) == [*ALL_PAUSES, "🔙 Regresar"]

    await app.click(USER_ID, "7 días")
    chat = await get_chat(app)
    assert chat.owner_pause_active()
    assert timedelta(days=6, hours=23) < chat.owner_paused_until - utcnow() <= timedelta(days=7)
    [event] = await events_of(app, EventKind.CHAT_PAUSED)
    assert event.data == {"by": "owner", "until": chat.owner_paused_until.isoformat()}


async def test_a_forged_long_pause_is_refused_when_the_rules_limit_it(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, pause_max_hours=24)
    chat = await partner_chat(app)
    await pa(app, USER_ID, "op", chat.id)
    await app.click(USER_ID, "Pausar")
    assert labels(app.last_panel(USER_ID)) == ["⏸ 1 h", "⏸ 6 h", "⏸ 24 h", "🔙 Regresar"]

    for value in (4, 5, 6):  # forged: 3 días, 7 días, hasta que la reanude
        await pa(app, USER_ID, "pz", chat.id, v=value)
        assert is_alert(app, "⏸ La administración no permite pausas tan largas."), value
        assert labels(app.last_panel(USER_ID)) == ["⏸ 1 h", "⏸ 6 h", "⏸ 24 h", "🔙 Regresar"], "the menu again"
    chat = await get_chat(app)
    assert not chat.owner_paused and chat.paused_at is None
    assert not await events_of(app, EventKind.CHAT_PAUSED)

    await app.click(USER_ID, "24 h")
    chat = await get_chat(app)
    assert chat.owner_pause_active()
    assert timedelta(hours=23, minutes=59) < chat.owner_paused_until - utcnow() <= timedelta(hours=24)
    [event] = await events_of(app, EventKind.CHAT_PAUSED)
    assert event.data == {"by": "owner", "until": chat.owner_paused_until.isoformat()}


@pytest.mark.parametrize(("max_hours", "offered"), [
    (24, ALL_PAUSES[:3]),
    (72, ALL_PAUSES[:4]),
    (168, ALL_PAUSES[:5]),
    (0, ALL_PAUSES),
])
async def test_the_menu_offers_the_allowed_durations(app: App, max_hours: int, offered: list[str]) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, pause_max_hours=max_hours)
    chat = await partner_chat(app)
    await pa(app, USER_ID, "pm", chat.id)
    assert labels(app.last_panel(USER_ID)) == [*offered, "🔙 Regresar"]
    await app.click(USER_ID, offered[-1].removeprefix("⏸ "))  # the longest one allowed
    chat = await get_chat(app)
    assert chat.owner_pause_active()
    assert (chat.owner_paused_until is None) == (max_hours == 0)


async def test_partners_cant_pause_when_the_admins_say_no(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, partners_can_pause=False)
    chat = await partner_chat(app)
    assert not any("Puedes pausarlos" in t for t in dms(app)), "the welcome doesn't offer it"
    await pa(app, USER_ID, "op", chat.id)
    assert f"📌 Estado: ✅ Recibe los mensajes de la red\n{NOT_ALLOWED}\n" in app.last_text(USER_ID)
    assert labels(app.last_panel(USER_ID)) == ["🚪 Salir de la red", "🔙 Regresar"]

    for action, value in (("pm", 0), ("pz", 1), ("pz", 6)):  # forged or old buttons
        await pa(app, USER_ID, action, chat.id, v=value)
        assert is_alert(app, NOT_ALLOWED), action
        assert "⏸ Pausar" not in labels(app.last_panel(USER_ID)), "back to the panel"
    assert not (await get_chat(app)).owner_paused
    assert not await events_of(app, EventKind.CHAT_PAUSED)

    await set_bot(app, join_open=True)
    await app.press(USER_ID, "m:join:0")
    assert "Puedes pausar" not in app.last_text(USER_ID)


async def test_a_rule_changed_later_applies_to_new_pauses(app: App) -> None:
    """A pause made before the rule changed stays, and the partner can still resume it (only new pauses obey)."""
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, pause_max_hours=0)
    chat = await partner_chat(app)
    await pa(app, USER_ID, "pz", chat.id, v=6)  # until they resume it
    await set_bot(app, partners_can_pause=False)

    await pa(app, USER_ID, "op", chat.id)
    assert "📌 Estado: ⏸ Pausado hasta que lo reanudes" in app.last_text(USER_ID)
    assert NOT_ALLOWED not in app.last_text(USER_ID)
    assert labels(app.last_panel(USER_ID))[0] == "▶️ Reanudar"
    await app.click(USER_ID, "Reanudar")
    chat = await get_chat(app)
    assert not chat.owner_paused and chat.paused_at is None
    [resumed] = await events_of(app, EventKind.CHAT_RESUMED)
    assert resumed.data == {"by": "owner"} and resumed.actor_id == USER_ID
    assert NOT_ALLOWED in app.last_text(USER_ID) and "⏸ Pausar" not in labels(app.last_panel(USER_ID))


async def test_pause_by_owner_refuses_what_the_rules_dont_allow(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    bot = app.manager.get(MAIN_BOT_ID)
    async with app.db() as s:
        ws, row = await s.get(BotRecord, MAIN_BOT_ID), await s.get(Chat, chat.id)
        assert ws.pause_max_hours == 0, "unlimited by default"
        ws.pause_max_hours = 24
        assert not await chat_svc.pause_by_owner(bot, s, ws, row, USER_ID, utcnow() + timedelta(hours=25))
        assert not await chat_svc.pause_by_owner(bot, s, ws, row, USER_ID, None)
        ws.partners_can_pause = False
        assert not await chat_svc.pause_by_owner(bot, s, ws, row, USER_ID, utcnow() + timedelta(hours=1))
        assert not row.owner_paused and row.paused_at is None
        ws.partners_can_pause, ws.pause_max_hours = True, 0
        assert await chat_svc.pause_by_owner(bot, s, ws, row, USER_ID, None)
        assert row.owner_paused and row.owner_paused_until is None and row.paused_at is not None
    assert len(await events_of(app, EventKind.CHAT_PAUSED)) == 1


# --------------------------------------------------------------------------- the admins resume a partner's pause
async def test_an_admin_resumes_a_partner_pause_from_the_chat_detail(app: App) -> None:
    await start(app, SUPER_ID, USER_ID, OWNER2_ID)
    await make_admin(app, OWNER2_ID)  # a promoted admin does it: the owner of the network is alerted
    chat = await partner_chat(app)
    await pa(app, USER_ID, "pz", chat.id, v=2)  # ⏸ 6 h
    until = (await get_chat(app)).owner_paused_until

    await app.press(OWNER2_ID, f"m:chat:{chat.id}")
    text = app.last_text(OWNER2_ID)
    assert f"📌 Estado: ⏸ Pausado por su asociado hasta {dt(until, TZ)}\n" in text
    assert "   └ Si lo reanudas, se anula su pausa y se le avisa." in text
    assert labels(app.last_panel(OWNER2_ID)) == ["🗂 Grupos de canales", "🔄 Comprobar permisos", LIFT, "⏸ Pausar",
                                                 "🗑 Quitar de la red", "🚫 Bloquear", "↗️ Abrir", "🔙 Regresar"]
    await app.click(OWNER2_ID, LIFT)
    assert app.last_text(OWNER2_ID) == ("▶️ ¿Reanudar el canal <b>Cine HD</b>?\n\nEl dueño lo ha pausado hasta "
                                        f"{dt(until, TZ)}. Se le avisará.")
    assert labels(app.last_panel(OWNER2_ID)) == ["▶️ Sí, reanudar", "🔙 No"]
    assert (await get_chat(app)).owner_pause_active(), "nothing changes before the confirmation"
    await app.click(OWNER2_ID, "🔙 No")
    assert app.last_text(OWNER2_ID).startswith("📣 <b>Cine HD</b>")
    assert not await events_of(app, EventKind.CHAT_RESUMED)

    await app.click(OWNER2_ID, LIFT)
    await app.click(OWNER2_ID, "Sí, reanudar")
    chat = await get_chat(app)
    assert not chat.owner_paused and chat.owner_paused_until is None and chat.paused_at is None
    assert last_answer(app)["text"] == "▶️ Reanudado"
    assert "📌 Estado: ✅ Recibe mensajes" in app.last_text(OWNER2_ID)
    assert labels(app.last_panel(OWNER2_ID))[2] == "⏸ Pausar"
    [resumed] = await events_of(app, EventKind.CHAT_RESUMED)
    assert resumed.data == {"by": "admin"} and resumed.actor_id == OWNER2_ID
    assert resumed_alert("Cine HD", "@owner2") in dms(app, SUPER_ID), "the other admins are alerted"
    assert not any("distribución reanudada" in t for t in dms(app, OWNER2_ID)), "not the admin who did it"
    assert dms(app)[-1] == partner_told("Cine HD")

    await pa(app, USER_ID, "op", chat.id)  # the partner sees it receiving again and may pause again
    assert "📌 Estado: ✅ Recibe los mensajes de la red" in app.last_text(USER_ID)
    assert labels(app.last_panel(USER_ID))[0] == "⏸ Pausar"


async def test_paused_lists_every_pause_and_resumes_them(app: App) -> None:
    await start(app, SUPER_ID, USER_ID, OWNER2_ID)
    await make_admin(app, OWNER2_ID)
    since = utcnow() - timedelta(hours=2)
    until = utcnow() + timedelta(hours=20)
    await db_chat(app, CHANNEL, "Cine <HD>", origin=EXT, owner=USER_ID, owner_paused=True, owner_paused_until=until,
                  paused_at=since)
    await db_chat(app, GROUP, "Grupo Series", type="supergroup", admin_paused=True, paused_at=since)
    await db_chat(app, -1003, "Canal Tres", origin=EXT, owner=USER_ID, owner_paused=True, admin_paused=True,
                  paused_at=since)
    await db_chat(app, -1004, "Canal Cuatro")
    await db_chat(app, -1005, "Pausa vencida", origin=EXT, owner=USER_ID, owner_paused=True,
                  owner_paused_until=utcnow() - timedelta(minutes=1))
    await db_chat(app, -1006, "Pendiente", origin=EXT, owner=USER_ID, status=ChatStatus.PENDING,
                  admin_paused=True)

    await app.press(SUPER_ID, "m:paused:0")
    text = app.last_text(SUPER_ID)
    s = dt(since, TZ)
    assert text == (
        "⏸ <b>Pausados</b> (3)\nToca ▶️ para reanudar uno. Si lo pausó su dueño, se anula su pausa y se le avisa.\n\n"
        f"1. 📣 Canal Tres\n   └👮 un admin y 🤝 @pepe · sin fecha de fin · desde {s}\n"
        f"2. 📣 Cine &lt;HD&gt;\n   └🤝 @pepe · hasta {dt(until, TZ)} · desde {s}\n"
        f"3. 👥 Grupo Series\n   └👮 un admin · sin fecha de fin · desde {s}")
    assert labels(app.last_panel(SUPER_ID)) == ["#1 📣 Canal Tres", "▶️ #1", "#2 📣 Cine <HD>", "▶️ #2",
                                                "#3 👥 Grupo Series", "▶️ #3", "🔙 Regresar"]

    # An admin's pause: resumed at once.
    await app.click(SUPER_ID, "▶️ #3")
    assert last_answer(app)["text"] == "▶️ Reanudado"
    assert app.last_text(SUPER_ID).startswith("⏸ <b>Pausados</b> (2)") and "Grupo Series" not in app.last_text(SUPER_ID)

    # A partner's pause: asks first («El dueño lo ha pausado hasta …»), then lifts it and tells the partner.
    await app.click(SUPER_ID, "▶️ #2")
    assert app.last_text(SUPER_ID) == ("▶️ ¿Reanudar el canal <b>Cine &lt;HD&gt;</b>?\n\nEl dueño lo ha pausado "
                                       f"hasta {dt(until, TZ)}. Se le avisará.")
    await app.click(SUPER_ID, "🔙 No")
    assert app.last_text(SUPER_ID).startswith("⏸ <b>Pausados</b> (2)")
    await app.click(SUPER_ID, "▶️ #2")
    await app.click(SUPER_ID, "Sí, reanudar")
    assert app.last_text(SUPER_ID).startswith("⏸ <b>Pausados</b> (1)")
    assert not (await get_chat(app)).is_paused()
    assert dms(app)[-1] == partner_told("Cine &lt;HD&gt;")

    # Paused by both: one confirmation and one resume lift both pauses.
    await app.click(SUPER_ID, "▶️ #1")
    assert "El dueño lo ha pausado hasta que lo reanude. Se le avisará." in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Sí, reanudar")
    assert app.last_text(SUPER_ID) == "⏸ <b>Pausados</b> (0)\n\n✅ No hay chats pausados."
    both = await get_chat(app, -1003)
    assert not both.admin_paused and not both.owner_paused and both.paused_at is None
    assert dms(app)[-1] == partner_told("Canal Tres")

    resumed = await events_of(app, EventKind.CHAT_RESUMED)
    assert [(e.chat_title, e.data, e.actor_id) for e in resumed] == [
        ("Grupo Series", {"by": "admin"}, SUPER_ID), ("Cine <HD>", {"by": "admin"}, SUPER_ID),
        ("Canal Tres", {"by": "admin"}, SUPER_ID)]
    alerts = dms(app, OWNER2_ID)
    for name in ("Grupo Series", "Cine &lt;HD&gt;", "Canal Tres"):
        assert resumed_alert(name, "@superadmin") in alerts, name
    assert not any("distribución reanudada" in t for t in dms(app, SUPER_ID))
    assert len([t for t in dms(app) if "ha reanudado la distribución" in t]) == 2, "own chats have no partner"


async def test_paused_paginates_and_resumes_from_any_page(app: App) -> None:
    await start(app, SUPER_ID)
    for i in range(11):
        await db_chat(app, -1002000000000 - i, f"Canal de Cine {i:02d}", admin_paused=True, paused_at=utcnow())
    await app.press(SUPER_ID, "m:paused:0")
    text = app.last_text(SUPER_ID)
    assert "⏸ <b>Pausados</b> (11)" in text and "10. 📣 Canal de Cine 09" in text and "📄 Página 1 de 2" in text
    await app.click(SUPER_ID, "Siguiente")
    assert "11. 📣 Canal de Cine 10" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "▶️ #11")
    text = app.last_text(SUPER_ID)
    assert "⏸ <b>Pausados</b> (10)" in text and "Canal de Cine 10" not in text and "Página" not in text
    assert not (await get_chat(app, -1002000000010)).admin_paused


async def test_resume_buttons_check_rights_and_ownership(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    await start(app, SUPER_ID, USER_ID)
    mine = await partner_chat(app)
    await pa(app, USER_ID, "pz", mine.id, v=1)
    other = await db_chat(app, GROUP, "Ajeno", bot_id=CLONE_ID, admin_paused=True)
    for action in ("rs", "rsy", "pr", "pry"):
        await ch(app, USER_ID, action, mine.id)  # forged by the partner
        assert is_alert(app, "No tienes permiso"), action
        await ch(app, SUPER_ID, action, other)  # a chat of another network
        assert is_alert(app, "Ya no existe"), action
    assert (await get_chat(app)).owner_pause_active()
    assert (await get_chat(app, GROUP, CLONE_ID)).admin_paused
    assert not await events_of(app, EventKind.CHAT_RESUMED)

    await app.press(USER_ID, "m:paused:0")
    assert "No tienes permiso" in app.last_text(USER_ID)

    await ch(app, SUPER_ID, "pry", mine.id)  # confirmed
    await ch(app, SUPER_ID, "pry", mine.id)  # pressed twice: nothing left to resume
    assert is_alert(app, "ℹ️ No está pausado.")
    assert len(await events_of(app, EventKind.CHAT_RESUMED)) == 1


async def test_partners_still_cant_lift_an_admin_pause(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await ch(app, SUPER_ID, "pz", chat.id)  # ⏸ an admin
    since = (await get_chat(app)).paused_at
    await pa(app, USER_ID, "pz", chat.id, v=1)  # ⏸ the partner too
    chat = await get_chat(app)
    assert chat.admin_paused and chat.owner_pause_active() and chat.paused_at == since, "paused since the first one"

    await pa(app, USER_ID, "rs", chat.id)  # their own pause only
    chat = await get_chat(app)
    assert chat.admin_paused and not chat.owner_paused and chat.paused_at == since
    await pa(app, USER_ID, "rs", chat.id)  # forged: the admin's pause isn't theirs
    assert is_alert(app, "Lo ha pausado la administración")
    assert (await get_chat(app)).admin_paused

    # The admins rule: one resume lifts both pauses (one event, the partner told once).
    await pa(app, USER_ID, "pz", chat.id, v=3)
    await ch(app, SUPER_ID, "op", chat.id)
    buttons = labels(app.last_panel(SUPER_ID))
    assert LIFT in buttons and "⏸ Pausar" not in buttons and "▶️ Reanudar" not in buttons
    await app.click(SUPER_ID, LIFT)
    await app.click(SUPER_ID, "Sí, reanudar")
    chat = await get_chat(app)
    assert not chat.is_paused() and not chat.admin_paused and not chat.owner_paused
    resumed = await events_of(app, EventKind.CHAT_RESUMED)
    assert [e.data for e in resumed] == [{"by": "owner"}, {"by": "admin"}]
    assert dms(app).count(partner_told("Cine HD")) == 1


# --------------------------------------------------------------------------- workspace (🛠 Gestionar)
async def test_a_super_admin_managing_a_clone_resumes_a_partner_pause(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    clone_token = next(tok for tok, b in app.fake.bots.items() if b["id"] == CLONE_ID)
    await start(app, SUPER_ID)
    async with app.db() as s:
        bu = await s.get(BotUser, (MAIN_BOT_ID, SUPER_ID))
        bu.ws_bot_id = CLONE_ID
    await start(app, OWNER2_ID, USER_ID, bot_id=CLONE_ID)
    await set_bot(app, CLONE_ID, pause_max_hours=72)  # the clone's own rules: up to 3 days
    chat = await partner_chat(app, user=USER_ID, bot_id=CLONE_ID)
    await db_chat(app, GROUP, "Grupo Principal", admin_paused=True)  # the main bot's own network

    await pa(app, USER_ID, "pm", chat.id, bot_id=CLONE_ID)
    assert labels(app.last_panel(USER_ID)) == [*ALL_PAUSES[:4], "🔙 Regresar"]
    await pa(app, USER_ID, "pz", chat.id, v=4, bot_id=CLONE_ID)  # ⏸ 3 días
    until = (await get_chat(app, CHANNEL, CLONE_ID)).owner_paused_until
    assert until is not None

    await app.press(SUPER_ID, "m:paused:0")
    text = app.last_text(SUPER_ID)
    assert text.startswith("🛠 Gestionando <b>@clon_cine_bot</b>")
    assert f"Cine HD</a>\n   └🤝 @pepe · hasta {dt(until, TZ)} · desde " in text
    assert "Grupo Principal" not in text
    await app.click(SUPER_ID, "▶️ #1")
    assert f"El dueño lo ha pausado hasta {dt(until, TZ)}. Se le avisará." in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Sí, reanudar")

    assert not (await get_chat(app, CHANNEL, CLONE_ID)).is_paused()
    assert (await get_chat(app, GROUP)).admin_paused, "the main network is untouched"
    [resumed] = await events_of(app, EventKind.CHAT_RESUMED, bot_id=CLONE_ID)
    assert resumed.data == {"by": "admin"} and resumed.actor_id == SUPER_ID
    assert partner_told("Cine HD") in dms(app, USER_ID, clone_token), "the partner is told by the clone"
    assert resumed_alert("Cine HD", "@superadmin") in dms(app, OWNER2_ID, clone_token), "its owner is alerted there"
