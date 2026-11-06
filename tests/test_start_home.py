"""Start module: the home by role (admins, partners, visitors, hub, workspace), ⏸ Pausar todo, deep links, the basic
commands and the guide."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.bot.routers.start import StCB, deep_link_target
from app.db.base import utcnow
from app.db.models import ChatOrigin, ChatStatus, Event, EventKind, PostStatus
from app.services import freq, limits
from app.services.chatinfo import add_to_channel_url, add_to_group_url
from app.ui.callbacks import MenuCB
from app.ui.fmt import dt
from tests.conftest import MAIN_BOT_ID, MAIN_BOT_USERNAME, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_start_helpers import (
    CLONE_ID,
    CLONE_USERNAME,
    add_chat_row,
    add_clone,
    add_post,
    button_of,
    button_rows,
    button_texts,
    callback_of,
    denied,
    dms_to,
    edit_bot,
    force_state,
    fsm_state,
    get_bot,
    get_bu,
    has_button,
    last_answer,
    make_admin,
    manage,
    stub_screens,  # noqa: F401  (fixture)
    url_of,
)

ADMIN_BUTTONS = ("Mensajes", "Canales", "Grupos de canales", "Frecuencias", "Estadísticas", "Actividad",
                 "Añadir canal", "Añadir grupo", "Pausar todo", "Ajustes", "Guía")
NETWORK_SCREENS = {"📝 Mensajes": "posts", "📣 Canales": "chats", "🗂 Grupos de canales": "groups",
                   "⏰ Frecuencias": "freqs", "📊 Estadísticas": "stats", "📜 Actividad": "activity",
                   "⚙️ Ajustes": "settings", "📖 Guía": "guide"}


def hub(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.settings, "MAIN_BOT_MODE", "hub")


# ------------------------------------------------------------------------------------------ deep links
@pytest.mark.parametrize(
    "payload,admin,expected",
    [
        ("join", False, ("join", 0)),
        ("join", True, ("join", 0)),
        ("clone", False, ("clone", 0)),
        ("c12", True, ("chat", 12)),
        ("c12", False, ("my_chat", 12)),
        ("p5", True, ("post", 5)),
        ("p5", False, ("home", 0)),
        (None, True, ("home", 0)),
        ("", False, ("home", 0)),
        ("whatever", True, ("home", 0)),
        ("c", True, ("home", 0)),
        ("c12x", True, ("home", 0)),
        ("cc12", True, ("home", 0)),
        ("c-1", True, ("home", 0)),
        ("c1234567890", True, ("home", 0)),
        ("p", True, ("home", 0)),
    ],
)
def test_deep_link_target(payload: str | None, admin: bool, expected: tuple[str, int]) -> None:
    assert deep_link_target(payload, admin=admin) == expected


@pytest.mark.parametrize(
    "user_id,payload,call",
    [(SUPER_ID, "c12", ("chat", 12)), (USER_ID, "c12", ("my_chat", 12)), (SUPER_ID, "p5", ("post", 5)),
     (USER_ID, "join", ("join", 0)), (USER_ID, "clone", ("clone", 0))],
)
async def test_deep_links_open_the_target_screen(
    app: App, stub_screens: list, user_id: int, payload: str, call: tuple[str, int]  # noqa: F811
) -> None:
    await app.send(user_id, f"/start {payload}")
    assert stub_screens == [call]
    assert app.last_text(user_id) == f"stub:{call[0]}:{call[1]}"


async def test_unknown_deep_links_open_the_home(app: App, stub_screens: list) -> None:  # noqa: F811
    await app.send(USER_ID, "/start p5")  # posts are for admins
    await app.send(USER_ID, "/start nonsense")
    assert stub_screens == []
    assert "Esta red es privada" in app.last_text(USER_ID)


# ------------------------------------------------------------------------------------ admin view
async def test_owner_home_of_an_empty_network(app: App) -> None:
    await app.send(SUPER_ID, "/start")
    text = app.last_text(SUPER_ID)
    assert text.startswith("🕸 <b>Tu red de distribución</b>\n\n📣 Canales y grupos: <b>0</b>\n"
                           "   └ Añade el bot a tus canales y grupos con los botones ➕ de abajo.\n"
                           "📝 Mensajes activos: <b>0</b>\n   └ Crea el primero en 📝 Mensajes.\n"
                           "⏰ Frecuencia global: cada 4 h · 08:00-22:00\n📅 Próximo turno: <b>")
    for absent in ("Pausados por su dueño", "Solicitudes pendientes", "Sin permisos", "está pausada"):
        assert absent not in text
    for label in (*ADMIN_BUTTONS, "Crear mi bot", "Panel"):
        assert has_button(app, SUPER_ID, label), f"{label!r} missing in {button_texts(app, SUPER_ID)}"
    for label in ("Solicitudes", "Pausados", "Mis bots", "Salir", "Reanudar", "Crea tu propio bot"):
        assert not has_button(app, SUPER_ID, label), label
    assert url_of(app, SUPER_ID, "Añadir canal") == add_to_channel_url(MAIN_BOT_USERNAME)
    assert url_of(app, SUPER_ID, "Añadir grupo") == add_to_group_url(MAIN_BOT_USERNAME)
    for label, name in NETWORK_SCREENS.items():
        assert callback_of(app, SUPER_ID, label) == MenuCB(screen=name).pack(), label
    assert callback_of(app, SUPER_ID, "Crear mi bot") == MenuCB(screen="clone").pack()
    assert callback_of(app, SUPER_ID, "Panel") == MenuCB(screen="panel").pack()
    assert callback_of(app, SUPER_ID, "Pausar todo") == StCB(action="pause").pack()
    assert button_rows(app, SUPER_ID) == [
        ["📝 Mensajes", "📣 Canales"], ["🗂 Grupos de canales", "⏰ Frecuencias"], ["📊 Estadísticas", "📜 Actividad"],
        ["➕ Añadir canal ↗", "➕ Añadir grupo ↗"], ["⏸ Pausar todo"], ["⚙️ Ajustes", "📖 Guía"], ["🤖 Crear mi bot"],
        ["👑 Panel"],
    ]


async def test_admin_home_summarizes_the_network(app: App) -> None:
    future = utcnow() + timedelta(days=1)
    await add_chat_row(app, members=1000)
    await add_chat_row(app, members=500, type="group")
    await add_chat_row(app, members=200, origin=ChatOrigin.EXTERNAL, owner_user_id=USER_ID, owner_paused=True,
                       owner_paused_until=future)
    await add_chat_row(app, members=300, origin=ChatOrigin.EXTERNAL, owner_user_id=USER_ID, rights_ok=False)
    await add_chat_row(app, members=40, origin=ChatOrigin.EXTERNAL, status=ChatStatus.PENDING)
    await add_chat_row(app, members=9999, status=ChatStatus.LEFT)
    await add_post(app)
    await add_post(app, name="Promo Series")
    await add_post(app, name="Pausado", status=PostStatus.PAUSED)
    slot = datetime(2030, 1, 15, 10, 0, tzinfo=timezone.utc)
    async with edit_bot(app) as rec:
        rec.freq = {"mode": "interval", "every": 180, "window": "08:00-23:00", "days": "0123456"}
        rec.rot_next_at = slot
    await app.send(SUPER_ID, "/start")
    text = app.last_text(SUPER_ID)
    assert ("📣 Canales y grupos: <b>4</b> (👤 2,000)\n   └ 🏠 Propios: 2 · 🤝 Externos: 2\n"
            "📝 Mensajes activos: <b>2</b>\n⏰ Frecuencia global: cada 3 h · 08:00-23:00\n"
            f"📅 Próximo turno: <b>{dt(slot, 'Europe/Madrid')}</b>\n"
            "⏸ Pausados por su dueño: <b>1</b>\n⏳ Solicitudes pendientes: <b>1</b>\n⚠️ Sin permisos: <b>1</b>") in text
    assert "Añade el bot" not in text and "Crea el primero" not in text
    assert ["⏳ Solicitudes (1)", "⏸ Pausados (1)"] in button_rows(app, SUPER_ID)
    assert callback_of(app, SUPER_ID, "Solicitudes (1)") == MenuCB(screen="requests").pack()
    assert callback_of(app, SUPER_ID, "Pausados (1)") == MenuCB(screen="paused").pack()


async def test_next_turn_is_computed_when_missing_or_past(app: App) -> None:
    times = {"mode": "times", "times": "10:00", "days": "0123456"}
    for stored in (None, utcnow() - timedelta(hours=5)):
        async with edit_bot(app) as rec:
            rec.freq = times
            rec.rot_next_at = stored
        await app.send(SUPER_ID, "/start")
        expected = freq.next_slot(times, "Europe/Madrid", utcnow())
        assert f"📅 Próximo turno: <b>{dt(expected, 'Europe/Madrid')}</b>" in app.last_text(SUPER_ID)
        assert "10:00 AM" in dt(expected, "Europe/Madrid")


async def test_home_buttons_open_the_screens_of_other_modules(app: App, stub_screens: list) -> None:  # noqa: F811
    await add_chat_row(app, status=ChatStatus.PENDING)
    await add_chat_row(app, origin=ChatOrigin.EXTERNAL, owner_paused=True)
    expected = {"Mensajes": "posts", "📣 Canales": "chats", "Grupos de canales": "groups", "Frecuencias": "freqs",
                "Solicitudes": "requests", "Pausados (": "paused", "Crear mi bot": "clone", "Panel": "panel"}
    for label, name in expected.items():
        await app.send(SUPER_ID, "/start")
        await app.click(SUPER_ID, label)
        assert stub_screens[-1] == (name, 0), label


async def test_promoted_admin_sees_the_network_without_the_platform_panel(app: App) -> None:
    await make_admin(app, USER_ID)
    await app.send(USER_ID, "/start")
    assert "Tu red de distribución" in app.last_text(USER_ID)
    for label in (*ADMIN_BUTTONS, "Crear mi bot"):
        assert has_button(app, USER_ID, label), label
    assert not has_button(app, USER_ID, "Panel") and not has_button(app, USER_ID, "Crea tu propio bot")


async def test_admin_with_bots_sees_my_bots(app: App) -> None:
    await add_clone(app, owner_id=SUPER_ID)
    await app.send(SUPER_ID, "/start")
    assert ["🤖 Crear mi bot", "🤖 Mis bots (1)"] in button_rows(app, SUPER_ID)
    assert callback_of(app, SUPER_ID, "Mis bots") == MenuCB(screen="mybots").pack()


async def test_clone_owner_home(app: App) -> None:
    await add_clone(app)
    await add_chat_row(app, bot_id=CLONE_ID, members=321)
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    text = app.last_text(OWNER2_ID)
    assert "Tu red de distribución" in text and "📣 Canales y grupos: <b>1</b> (👤 321)" in text
    for label in ADMIN_BUTTONS:
        assert has_button(app, OWNER2_ID, label), label
    for label in ("Crear mi bot", "Mis bots", "Panel", "Salir", "Crea tu propio bot"):
        assert not has_button(app, OWNER2_ID, label), label
    assert url_of(app, OWNER2_ID, "Añadir canal") == add_to_channel_url(CLONE_USERNAME)
    # A super admin has owner rights in every bot, but the 👑 panel only exists in the main bot.
    await app.send(SUPER_ID, "/start", bot_id=CLONE_ID)
    assert has_button(app, SUPER_ID, "Pausar todo") and not has_button(app, SUPER_ID, "Panel")


# ---------------------------------------------------------------------------------- partners & visitors
async def test_visitor_home_of_a_private_main_network(app: App) -> None:
    await app.send(USER_ID, "/start")
    text = app.last_text(USER_ID)
    assert text == ("🕸 <b>eMesh</b> · Crea tu propio bot y publica mensajes en tus canales y grupos de forma "
                    "automática.\n\n🔒 <b>Esta red es privada.</b>\nSolo la administración puede añadir canales y "
                    "grupos.")
    assert button_rows(app, USER_ID) == [["📖 Guía"], ["⚙️ Ajustes"], ["🤖 Crea tu propio bot"]]
    assert callback_of(app, USER_ID, "Crea tu propio bot") == MenuCB(screen="clone").pack()
    # The owner's @username is the support contact once known.
    await app.send(SUPER_ID, "/start")
    await app.send(USER_ID, "/start")
    assert url_of(app, USER_ID, "Soporte") == "https://t.me/superadmin"
    assert ["📖 Guía", "🛟 Soporte ↗"] in button_rows(app, USER_ID)
    async with edit_bot(app) as rec:
        rec.support_username = "ayuda_bot"
    await app.send(USER_ID, "/start")
    assert url_of(app, USER_ID, "Soporte") == "https://t.me/ayuda_bot"


async def test_partner_home_when_the_network_accepts_external_chats(app: App) -> None:
    async with edit_bot(app) as rec:
        rec.join_open = True
        rec.min_members = 500
    await app.send(USER_ID, "/start")
    text = app.last_text(USER_ID)
    assert ("🤝 <b>Únete a la red de @emesh_test_bot</b>\n\nAñade este bot a tu canal o grupo y recibirá las "
            "publicaciones de la red.\n⏸ Puedes pausarlas cuando quieras desde 📣 Mis canales.\n\n"
            "👤 Mínimo para unirse: <b>500</b> miembros.\n\n"
            "⏳ La administración revisa cada canal antes de aceptarlo.") in text
    assert "privada" not in text
    assert button_rows(app, USER_ID)[0] == ["➕ Añadir a mi canal ↗", "➕ Añadir a mi grupo ↗"]
    assert url_of(app, USER_ID, "Añadir a mi canal") == add_to_channel_url(MAIN_BOT_USERNAME)
    assert url_of(app, USER_ID, "Añadir a mi grupo") == add_to_group_url(MAIN_BOT_USERNAME)
    async with edit_bot(app) as rec:
        rec.join_approval = False
        rec.min_members = 0
    await app.send(USER_ID, "/start")
    assert "Mínimo" not in app.last_text(USER_ID) and "revisa" not in app.last_text(USER_ID)


async def test_partner_home_with_a_custom_join_text(app: App) -> None:
    async with edit_bot(app) as rec:
        rec.join_open = True
        rec.join_approval = False
        rec.join_text = '<b>Únete</b> a <i>Cine</i> <tg-emoji emoji-id="5368324170671202286">🔥</tg-emoji>'
    await app.send(USER_ID, "/start")
    text = app.last_text(USER_ID)
    assert "<b>Únete</b> a <i>Cine</i> 🔥" in text  # custom emoji are sent as normal emoji
    assert "tg-emoji" not in text and "Únete a la red de" not in text


async def test_a_refused_custom_join_text_falls_back_to_the_default(app: App) -> None:
    async with edit_bot(app) as rec:
        rec.join_open = True
        rec.join_text = "<b>Texto roto</b>"
    app.fake.fail("sendMessage", description="Bad Request: can't parse entities",
                  when=lambda p: "Texto roto" in str(p.get("text")))
    await app.send(USER_ID, "/start")
    assert "Únete a la red de @emesh_test_bot" in app.last_text(USER_ID)


async def test_my_channels_counts_the_external_chats_of_the_user(app: App) -> None:
    for status in (ChatStatus.APPROVED, ChatStatus.PENDING, ChatStatus.REJECTED, ChatStatus.LEFT):
        await add_chat_row(app, origin=ChatOrigin.EXTERNAL, owner_user_id=USER_ID, status=status)
    await add_chat_row(app, origin=ChatOrigin.EXTERNAL, owner_user_id=OWNER2_ID)  # someone else's
    await add_chat_row(app, owner_user_id=USER_ID)  # own chats are not partners' chats
    await app.send(USER_ID, "/start")
    assert has_button(app, USER_ID, "📣 Mis canales (3)")
    assert callback_of(app, USER_ID, "Mis canales") == MenuCB(screen="my_chats").pack()
    await app.send(OWNER2_ID, "/start")
    assert has_button(app, OWNER2_ID, "📣 Mis canales (1)")


async def test_visitor_of_a_clone_gets_a_link_to_create_a_bot(app: App) -> None:
    await add_clone(app)
    await app.send(USER_ID, "/start", bot_id=CLONE_ID)
    assert "eMesh" not in app.last_text(USER_ID)  # clones don't introduce the platform
    assert "Esta red es privada" in app.last_text(USER_ID)
    assert url_of(app, USER_ID, "Crea tu propio bot") == f"https://t.me/{MAIN_BOT_USERNAME}?start=clone"
    assert not has_button(app, USER_ID, "Mis bots")


async def test_create_own_bot_is_hidden_when_the_platform_is_closed(app: App) -> None:
    await add_clone(app)
    async with app.db() as s:
        p = await limits.platform(s, app.settings)
        p.clone_policy = "closed"
        await limits.save_platform(s, p)
    await app.send(USER_ID, "/start", bot_id=CLONE_ID)
    assert not has_button(app, USER_ID, "Crea tu propio bot")
    await app.send(USER_ID, "/start")
    assert not has_button(app, USER_ID, "Crea tu propio bot")
    assert app.last_text(USER_ID).startswith("🔒 <b>Esta red es privada.</b>")  # no platform introduction


async def test_main_bot_user_with_clones_sees_my_bots(app: App) -> None:
    await add_clone(app)
    await app.send(OWNER2_ID, "/start")
    assert ["🤖 Crea tu propio bot", "🤖 Mis bots (1)"] in button_rows(app, OWNER2_ID)
    assert callback_of(app, OWNER2_ID, "Mis bots") == MenuCB(screen="mybots").pack()


async def test_home_follows_the_language_of_the_user(app: App) -> None:
    app.fake.add_user(777, "Eng", "eng", lang="en")
    await app.send(777, "/start")
    assert "🔒 <b>This network is private.</b>" in app.last_text(777)
    assert has_button(app, 777, "Create your own bot") and has_button(app, 777, "Settings")


# ------------------------------------------------------------------------------------------ hub mode
async def test_hub_home(app: App, monkeypatch: pytest.MonkeyPatch, stub_screens: list) -> None:  # noqa: F811
    hub(app, monkeypatch)
    await add_clone(app)
    await app.send(SUPER_ID, "/start")
    text = app.last_text(SUPER_ID)
    assert text.startswith("🕸 <b>eMesh · Tu propia red de distribución</b>") and "Crear mi bot" in text
    assert button_rows(app, SUPER_ID) == [["✨ Crear mi bot"], ["📖 Guía", "⚙️ Ajustes"], ["👑 Panel"]]
    assert button_of(app, SUPER_ID, "Crear mi bot")["style"] == "success"
    assert callback_of(app, SUPER_ID, "Crear mi bot") == MenuCB(screen="clone").pack()
    await app.send(OWNER2_ID, "/start")
    assert button_rows(app, OWNER2_ID) == [["✨ Crear mi bot"], ["🤖 Mis bots (1)"], ["📖 Guía", "⚙️ Ajustes"]]
    # Network screens and deep links open the home instead.
    await app.send(USER_ID, "/start join")
    await app.press(USER_ID, MenuCB(screen="stats").pack())
    assert stub_screens == []
    assert app.last_text(USER_ID).startswith("🕸 <b>eMesh · Tu propia red de distribución</b>")
    await app.press(SUPER_ID, StCB(action="pause").pack())
    assert denied(app) and not (await get_bot(app)).paused


# ----------------------------------------------------------------------------------------- workspace
async def test_workspace_home_and_exit(app: App) -> None:
    await add_clone(app)
    await add_chat_row(app, bot_id=CLONE_ID, members=777)
    await manage(app, SUPER_ID, CLONE_ID)
    await app.send(SUPER_ID, "/start")
    text = app.last_text(SUPER_ID)
    assert text.startswith(f"🛠 Gestionando <b>@{CLONE_USERNAME}</b>\n\n🕸 <b>Tu red de distribución</b>")
    assert "📣 Canales y grupos: <b>1</b> (👤 777)" in text  # the clone's network
    assert url_of(app, SUPER_ID, "Añadir canal") == add_to_channel_url(CLONE_USERNAME)
    assert not has_button(app, SUPER_ID, "Crear mi bot") and has_button(app, SUPER_ID, "Panel")
    exit_button = button_of(app, SUPER_ID, "Salir de")
    assert exit_button["text"] == f"🚪 Salir de @{CLONE_USERNAME}" and exit_button["style"] == "danger"
    assert button_rows(app, SUPER_ID)[-1] == [f"🚪 Salir de @{CLONE_USERNAME}"]
    await app.click(SUPER_ID, "Salir de")
    assert (await get_bu(app, SUPER_ID)).ws_bot_id is None
    assert last_answer(app)["text"] == f"🚪 Has dejado de gestionar @{CLONE_USERNAME}."
    text = app.last_text(SUPER_ID)
    assert text.startswith("🕸 <b>Tu red de distribución</b>") and "Gestionando" not in text
    assert "📣 Canales y grupos: <b>0</b>" in text and not has_button(app, SUPER_ID, "Salir de")
    assert url_of(app, SUPER_ID, "Añadir canal") == add_to_channel_url(MAIN_BOT_USERNAME)
    await app.send(SUPER_ID, "/start")
    assert "Gestionando" not in app.last_text(SUPER_ID)


async def test_workspace_in_hub_mode(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    hub(app, monkeypatch)
    await add_clone(app)
    await manage(app, SUPER_ID, CLONE_ID)
    await app.send(SUPER_ID, "/start")  # the hub runs no network, but the managed clone does
    assert "Gestionando" in app.last_text(SUPER_ID) and "Tu red de distribución" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Pausar todo")
    assert (await get_bot(app, CLONE_ID)).paused
    await app.click(SUPER_ID, "Salir de")
    assert app.last_text(SUPER_ID).startswith("🕸 <b>eMesh · Tu propia red de distribución</b>")


async def test_exit_without_a_workspace_just_shows_the_home(app: App) -> None:
    await app.send(USER_ID, "/start")
    await app.press(USER_ID, StCB(action="exit").pack())
    assert "Esta red es privada" in app.last_text(USER_ID)


# ---------------------------------------------------------------------------------------- pause all
async def test_pause_and_resume_the_whole_network(app: App) -> None:
    await make_admin(app, USER_ID)
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Pausar todo")
    assert (await get_bot(app)).paused
    assert last_answer(app)["text"] == "⏸ Distribución pausada: no se enviará nada hasta que la reanudes."
    text = app.last_text(SUPER_ID)
    assert text.endswith("\n\n⏸ <b>La distribución está pausada.</b> No se envía nada hasta que la reanudes.")
    assert "Próximo turno" not in text
    resume = button_of(app, SUPER_ID, "Reanudar todo")
    assert resume["style"] == "success" and resume["callback_data"] == StCB(action="resume").pack()
    assert not has_button(app, SUPER_ID, "Pausar todo")
    # The other admins are told (not who did it).
    assert dms_to(app, USER_ID)[-1] == "⏸ Distribución de toda la red pausada (@superadmin)."
    assert not any("pausada (@superadmin)" in m for m in dms_to(app, SUPER_ID))
    # A second press of an old button changes nothing.
    await app.press(SUPER_ID, StCB(action="pause").pack())
    await app.click(SUPER_ID, "Reanudar todo")
    assert not (await get_bot(app)).paused
    assert last_answer(app)["text"] == "▶️ Distribución reanudada."
    assert "Próximo turno" in app.last_text(SUPER_ID) and has_button(app, SUPER_ID, "Pausar todo")
    async with app.db() as s:
        rows = (await s.execute(select(Event).where(Event.bot_id == MAIN_BOT_ID).order_by(Event.id))).scalars().all()
    assert [(e.kind, e.actor_id) for e in rows] == [(EventKind.BOT_PAUSED, SUPER_ID), (EventKind.BOT_RESUMED, SUPER_ID)]


async def test_admins_can_pause_and_users_cannot(app: App) -> None:
    await app.send(USER_ID, "/start")
    await app.press(USER_ID, StCB(action="pause").pack())
    assert denied(app)
    assert not (await get_bot(app)).paused
    await make_admin(app, OWNER2_ID)
    await app.press(OWNER2_ID, StCB(action="pause").pack())
    assert (await get_bot(app)).paused


async def test_pause_while_managing_a_clone_pauses_the_clone(app: App) -> None:
    await add_clone(app)
    await manage(app, SUPER_ID, CLONE_ID)
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Pausar todo")
    assert (await get_bot(app, CLONE_ID)).paused and not (await get_bot(app)).paused
    assert "Gestionando" in app.last_text(SUPER_ID) and "está pausada" in app.last_text(SUPER_ID)
    async with app.db() as s:
        ev = (await s.execute(select(Event))).scalars().one()
    assert (ev.bot_id, ev.kind) == (CLONE_ID, EventKind.BOT_PAUSED)


# ------------------------------------------------------------------------------------------ commands
async def test_id_command(app: App) -> None:
    await app.send(USER_ID, "/id")
    assert app.last_text(USER_ID) == f"🆔 Tu ID: <code>{USER_ID}</code>"


async def test_cancel_clears_the_state_and_opens_the_home(app: App) -> None:
    await app.send(SUPER_ID, "/start")
    await force_state(app, SUPER_ID, "SettingsFSM:min_members")
    await app.send(SUPER_ID, "/cancel")
    assert await fsm_state(app, SUPER_ID) is None
    assert app.last_text(SUPER_ID).startswith("❌ Cancelado\n\n🕸 <b>Tu red de distribución</b>")
    await app.send(SUPER_ID, "/cancel")  # nothing to cancel: just the home
    assert app.last_text(SUPER_ID).startswith("🕸 <b>Tu red de distribución</b>")


async def test_start_clears_a_half_finished_input(app: App) -> None:
    await app.send(SUPER_ID, "/start")
    await force_state(app, SUPER_ID, "SettingsFSM:support")
    await app.send(SUPER_ID, "/start")
    assert await fsm_state(app, SUPER_ID) is None
    await app.send(SUPER_ID, "ayuda_bot")  # not taken as the support contact any more
    assert (await get_bot(app)).support_username is None


async def test_help_opens_the_guide(app: App) -> None:
    await app.send(USER_ID, "/help")
    assert app.last_text(USER_ID).startswith("🤝 <b>Cómo unirse a la red</b>")


# --------------------------------------------------------------------------------------------- guide
@pytest.mark.parametrize(
    "role,pages,first",
    [("admin", 5, "🕸 <b>Cómo funciona</b>"), ("partner", 2, "🤝 <b>Cómo unirse a la red</b>")],
)
async def test_guide_pages_per_role(app: App, role: str, pages: int, first: str) -> None:
    user_id = SUPER_ID if role == "admin" else USER_ID
    await app.send(user_id, "/start")
    await app.click(user_id, "Guía")
    seen = []
    for page in range(pages):
        text = app.last_text(user_id)
        assert text.endswith(f"\n\n📄 Página {page + 1} de {pages}"), text[-60:]
        seen.append(text.split("\n", 1)[0])
        nav = [t for t in button_texts(app, user_id) if "Anterior" in t or "Siguiente" in t]
        assert nav == (["Siguiente ➡️"] if page == 0 else ["⬅️ Anterior"] if page == pages - 1
                       else ["⬅️ Anterior", "Siguiente ➡️"])
        assert callback_of(app, user_id, "Regresar") == MenuCB(screen="home").pack()
        if page < pages - 1:
            await app.click(user_id, "Siguiente")
    assert seen[0] == first and len(set(seen)) == pages
    await app.click(user_id, "Anterior")
    assert f"📄 Página {pages - 1} de {pages}" in app.last_text(user_id)
    await app.press(user_id, MenuCB(screen="guide", arg=99).pack())  # out of range pages are clamped
    assert app.last_text(user_id).endswith(f"📄 Página {pages} de {pages}")


async def test_guide_in_hub_mode(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    hub(app, monkeypatch)
    await app.send(SUPER_ID, "/help")
    assert app.last_text(SUPER_ID).startswith("🕸 <b>¿Qué es eMesh?</b>")
    assert app.last_text(SUPER_ID).endswith("📄 Página 1 de 2")
    await app.click(SUPER_ID, "Siguiente")
    assert app.last_text(SUPER_ID).startswith("✨ <b>Crear tu bot</b>")


async def test_guide_describes_the_real_features(app: App) -> None:
    from app.i18n import t

    admin = " ".join(t(f"guide.admin.{i}", "es") for i in range(1, 6))
    for feature in ("Pausar todo", "Importar", "Canales externos", "&amp;&amp;", "copiar:", "rotación",
                    "horario propio", "Anti-spam", "uno a la vez", "/admin @usuario", "/deladmin", "Mis avisos",
                    "Zona horaria", "Estadísticas", "Crear mi bot", "48 h"):
        assert feature in admin, feature
    partner = " ".join(t(f"guide.partner.{i}", "es") for i in range(1, 3))
    for feature in ("Añadir a mi canal", "pendiente", "1 h, 6 h, 24 h, 3 días, 7 días", "Categorías", "Salir"):
        assert feature in partner, feature
    assert "Usar token" in t("guide.hub.2", "es") and "/newbot" in t("guide.hub.2", "es")
