"""Start module: the home by role (admins, partners, visitors, hub, workspace), ⏸ Pausar todo, deep links, the basic
commands and the guide."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.bot.routers.start import StCB, deep_link_target
from app.db.base import utcnow
from app.db.models import Chat, ChatOrigin, ChatStatus, Event, EventKind, Post, PostStatus, SchedMode
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

ADMIN_BUTTONS = ("Añadir canal o grupo", "Mensajes", "Canales", "Grupos de canales", "Frecuencias", "Estadísticas",
                 "Actividad", "Pausar todo", "Ajustes", "Guía")
NETWORK_SCREENS = {"📝 Mensajes": "posts", "📣 Canales": "chats", "🗂 Grupos de canales": "groups",
                   "⏰ Frecuencias": "freqs", "📊 Estadísticas": "stats", "📜 Actividad": "activity",
                   "⚙️ Ajustes": "settings", "📖 Guía": "guide"}
ADD_CHAT = ("➕ <b>Añadir canal o grupo</b>\n\n"
            "1. Pulsa ➕ <b>Añadir canal</b> o ➕ <b>Añadir grupo</b> y elige el tuyo.\n"
            "2. Deja marcados los permisos que se proponen: el bot los necesita para publicar.\n"
            "3. Listo: entra en la red al momento y se te avisa por aquí.")
WELCOME = ("👋 <b>¡Hola, Pepe!</b> Te damos la bienvenida a <b>eMesh</b>.\n\n"
           "🕸 eMesh publica mensajes en canales y grupos de Telegram de forma automática: escribes el mensaje, eliges "
           "cada cuánto se publica y el bot lo envía solo.\n\n"
           "🤖 <b>Para publicar en tus canales necesitas tu propio bot.</b> Créalo en un minuto con "
           "<b>🤖 Crear mi bot</b>: es tuyo, con tu nombre, tus canales y tus reglas.")
JOIN_STEPS = ("🤝 <b>Únete a la red de @{bot}</b>\n"
              "Tu canal o grupo recibirá sus publicaciones de forma automática. Unirse lleva un minuto:\n\n"
              "1. Pulsa ➕ <b>Añadir a mi canal</b> (o <b>a mi grupo</b>) y elige cuál.\n"
              "2. Conserva los permisos que se proponen: sirven para publicar los mensajes y borrarlos.\n"
              "3. Listo: se te avisará por aquí cuando ya esté dentro.")
JOIN_PAUSE = "⏸ Puedes pausar las publicaciones cuando quieras desde 📣 Mis canales."


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
    assert app.last_text(USER_ID).startswith("👋 <b>¡Hola, Pepe!</b>")


# ------------------------------------------------------------------------------------ admin view
async def test_owner_home_of_an_empty_network(app: App) -> None:
    await app.send(SUPER_ID, "/start")
    text = app.last_text(SUPER_ID)
    assert text.startswith("🕸 <b>Tu red de distribución</b>\n\n📣 Canales y grupos: <b>0</b>\n"
                           "   └ Añade el bot a tus canales y grupos con ➕ <b>Añadir canal o grupo</b>.\n"
                           "📝 Mensajes activos: <b>0</b>\n   └ Crea el primero en 📝 Mensajes.\n"
                           "⏰ Frecuencia global: a las 12:00\n📅 Próximo turno: <b>")
    for absent in ("Estado", "Pausados por su dueño", "Solicitudes pendientes", "Sin permisos", "está pausada"):
        assert absent not in text
    for label in (*ADMIN_BUTTONS, "Crear mi bot", "Panel"):
        assert has_button(app, SUPER_ID, label), f"{label!r} missing in {button_texts(app, SUPER_ID)}"
    for label in ("Solicitudes", "Pausados", "Mis bots", "Salir", "Reanudar", "Crea tu propio bot", "↗"):
        assert not has_button(app, SUPER_ID, label), label
    for label, name in NETWORK_SCREENS.items():
        assert callback_of(app, SUPER_ID, label) == MenuCB(screen=name).pack(), label
    assert callback_of(app, SUPER_ID, "Añadir canal o grupo") == MenuCB(screen="add_chat").pack()
    assert callback_of(app, SUPER_ID, "Crear mi bot") == MenuCB(screen="clone").pack()
    assert callback_of(app, SUPER_ID, "Panel") == MenuCB(screen="panel").pack()
    assert callback_of(app, SUPER_ID, "Pausar todo") == StCB(action="pause").pack()
    assert button_rows(app, SUPER_ID) == [
        ["➕ Añadir canal o grupo"], ["📝 Mensajes", "📣 Canales"], ["🗂 Grupos de canales", "⏰ Frecuencias"],
        ["📊 Estadísticas", "📜 Actividad"], ["⏸ Pausar todo"], ["⚙️ Ajustes", "📖 Guía"], ["🤖 Crear mi bot"],
        ["👑 Panel"],
    ]
    assert button_of(app, SUPER_ID, "Añadir canal o grupo")["style"] == "success"


async def test_add_a_channel_or_group_from_its_submenu(app: App, stub_screens: list) -> None:  # noqa: F811
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Añadir canal o grupo")
    assert app.last_text(SUPER_ID) == ADD_CHAT
    assert button_rows(app, SUPER_ID) == [["➕ Añadir canal ↗", "➕ Añadir grupo ↗"], ["📣 Ver canales y grupos"],
                                          ["🔙 Regresar"]]
    assert url_of(app, SUPER_ID, "Añadir canal") == add_to_channel_url(MAIN_BOT_USERNAME)
    assert url_of(app, SUPER_ID, "Añadir grupo") == add_to_group_url(MAIN_BOT_USERNAME)
    assert callback_of(app, SUPER_ID, "Regresar") == MenuCB(screen="home").pack()
    await app.click(SUPER_ID, "Ver canales y grupos")
    assert stub_screens == [("chats", 0)]
    await app.press(SUPER_ID, MenuCB(screen="add_chat").pack())
    await app.click(SUPER_ID, "Regresar")
    assert app.last_text(SUPER_ID).startswith("🕸 <b>Tu red de distribución</b>")
    # In English.
    app.fake.add_user(778, "Eng", "eng", lang="en")
    await make_admin(app, 778)
    await app.press(778, MenuCB(screen="add_chat").pack())
    assert app.last_text(778).startswith("➕ <b>Add a channel or group</b>\n\n1. Tap ➕ <b>Add channel</b>")
    assert button_rows(app, 778) == [["➕ Add channel ↗", "➕ Add group ↗"], ["📣 See channels and groups"], ["🔙 Back"]]


async def test_only_admins_add_channels_from_the_home(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    await app.send(USER_ID, "/start")
    assert not has_button(app, USER_ID, "Añadir canal o grupo")
    await app.press(USER_ID, MenuCB(screen="add_chat").pack())  # a forged button
    assert denied(app) and not has_button(app, USER_ID, "Añadir canal ↗")
    await make_admin(app, OWNER2_ID)
    await app.press(OWNER2_ID, MenuCB(screen="add_chat").pack())
    assert app.last_text(OWNER2_ID) == ADD_CHAT
    monkeypatch.setattr(app.settings, "MAIN_BOT_MODE", "hub")  # the hub runs no network: nothing to add
    await app.send(SUPER_ID, "/start")
    await app.press(SUPER_ID, MenuCB(screen="add_chat").pack())
    assert not has_button(app, SUPER_ID, "Añadir canal ↗")


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
            "📊 Estado: ✅ 2 reciben · ⏸ 1 pausado · ⚠️ 1 sin permisos · ⏳ 1 pendiente\n"
            "📝 Mensajes activos: <b>2</b>\n⏰ Frecuencia global: cada 3 h · 08:00-23:00\n"
            f"📅 Próximo turno: <b>{dt(slot, 'Europe/Madrid')}</b>\n"
            "⏸ Pausados por su dueño: <b>1</b>\n⏳ Solicitudes pendientes: <b>1</b>\n⚠️ Sin permisos: <b>1</b>") in text
    assert "Añade el bot" not in text and "Crea el primero" not in text
    assert ["⏳ Solicitudes (1)", "⏸ Pausados (1)"] in button_rows(app, SUPER_ID)
    assert callback_of(app, SUPER_ID, "Solicitudes (1)") == MenuCB(screen="requests").pack()
    assert callback_of(app, SUPER_ID, "Pausados (1)") == MenuCB(screen="paused").pack()


async def test_status_line_and_the_paused_button(app: App) -> None:
    """The status line counts every chat once; ⏸ Pausados counts admin pauses too and is always there when partners
    can join (even with 0)."""
    past = utcnow() - timedelta(hours=1)
    own = await add_chat_row(app, members=10)
    await add_chat_row(app, members=20)
    await app.send(SUPER_ID, "/start")
    assert "\n📊 Estado: ✅ 2 reciben · ⏸ 0 pausados · ⚠️ 0 sin permisos · ⏳ 0 pendientes\n" in app.last_text(SUPER_ID)
    assert not has_button(app, SUPER_ID, "Pausados")  # a private network with nothing paused
    async with app.db() as s:
        chat = await s.get(Chat, own)
        assert chat is not None
        chat.admin_paused = True
    await add_chat_row(app, owner_paused=True, admin_paused=True)  # paused twice: one chat
    await add_chat_row(app, owner_paused=True, owner_paused_until=past)  # a pause that is over
    await app.send(SUPER_ID, "/start")
    text = app.last_text(SUPER_ID)
    assert "📊 Estado: ✅ 2 reciben · ⏸ 2 pausados · ⚠️ 0 sin permisos · ⏳ 0 pendientes" in text
    assert "⏸ Pausados por su dueño: <b>1</b>" in text
    assert callback_of(app, SUPER_ID, "⏸ Pausados (2)") == MenuCB(screen="paused").pack()
    async with app.db() as s:
        await s.execute(update(Chat).values(admin_paused=False, owner_paused=False))
    async with edit_bot(app) as rec:
        rec.join_open = True
    await app.send(SUPER_ID, "/start")
    assert "📊 Estado: ✅ 4 reciben · ⏸ 0 pausados" in app.last_text(SUPER_ID)
    assert has_button(app, SUPER_ID, "⏸ Pausados (0)")  # partners may pause: always in sight
    async with edit_bot(app) as rec:
        rec.join_open = False
    await add_chat_row(app, origin=ChatOrigin.EXTERNAL, owner_user_id=USER_ID)
    await app.send(SUPER_ID, "/start")
    assert has_button(app, SUPER_ID, "⏸ Pausados (0)")  # the network still has partners


async def test_status_line_with_only_pending_chats(app: App) -> None:
    await add_chat_row(app, origin=ChatOrigin.EXTERNAL, status=ChatStatus.PENDING)
    await add_chat_row(app, origin=ChatOrigin.EXTERNAL, status=ChatStatus.PENDING)
    await app.send(SUPER_ID, "/start")
    text = app.last_text(SUPER_ID)
    assert "📣 Canales y grupos: <b>0</b>" in text
    assert "📊 Estado: ✅ 0 reciben · ⏸ 0 pausados · ⚠️ 0 sin permisos · ⏳ 2 pendientes" in text
    assert has_button(app, SUPER_ID, "⏳ Solicitudes (2)")
    app.fake.add_user(778, "Eng", "eng", lang="en")
    await make_admin(app, 778)
    await app.send(778, "/start")
    assert "📊 Status: ✅ 0 receiving · ⏸ 0 paused · ⚠️ 0 missing rights · ⏳ 2 pending" in app.last_text(778)


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


async def test_home_without_rotation_shows_the_next_send_of_the_posts(app: App) -> None:
    now = utcnow()
    soon, later = now + timedelta(hours=2), now + timedelta(days=1)
    paused = await add_post(app, name="Pausado", mode=SchedMode.OWN, status=PostStatus.PAUSED)
    sends = [(await add_post(app, name="Propio", mode=SchedMode.OWN), later),
             (await add_post(app, name="Puntual", mode=SchedMode.ONCE), soon),
             (paused, now + timedelta(hours=1)),  # not active
             (await add_post(app, name="Pasado", mode=SchedMode.OWN), now - timedelta(hours=1)),
             (await add_post(app, bot_id=await add_clone(app), mode=SchedMode.OWN), now + timedelta(minutes=30))]
    async with app.db() as s:
        for post_id, when in sends:
            (await s.get(Post, post_id)).next_send_at = when
    async with edit_bot(app) as rec:
        rec.rotation = "off"
    await app.send(SUPER_ID, "/start")
    text = app.last_text(SUPER_ID)
    assert ("📝 Mensajes activos: <b>3</b>\n🔁 Sin rotación: cada mensaje se envía con su propio horario\n"
            f"📅 Próximo envío: <b>{dt(soon, 'Europe/Madrid')}</b>") in text
    assert "Frecuencia global" not in text and "Próximo turno" not in text
    app.fake.add_user(778, "Eng", "eng", lang="en")
    await make_admin(app, 778)
    await app.send(778, "/start")
    assert ("🔁 No rotation: each post goes out on its own schedule\n"
            f"📅 Next send: <b>{dt(soon, 'Europe/Madrid')}</b>") in app.last_text(778)

    async with app.db() as s:
        await s.execute(update(Post).where(Post.bot_id == MAIN_BOT_ID).values(next_send_at=None))
    await app.send(SUPER_ID, "/start")
    assert "🔁 Sin rotación: cada mensaje se envía con su propio horario\n📅 Próximo envío: <b>—</b>" in (
        app.last_text(SUPER_ID))
    async with edit_bot(app) as rec:
        rec.paused = True
    await app.send(SUPER_ID, "/start")
    text = app.last_text(SUPER_ID)
    assert "🔁 Sin rotación" in text and "Próximo envío" not in text and "está pausada" in text

    async with edit_bot(app) as rec:
        rec.paused, rec.rotation, rec.rot_next_at = False, "seq", soon
    await app.send(SUPER_ID, "/start")
    text = app.last_text(SUPER_ID)
    assert f"⏰ Frecuencia global: a las 12:00\n📅 Próximo turno: <b>{dt(soon, 'Europe/Madrid')}</b>" in text
    assert "Sin rotación" not in text and "Próximo envío" not in text


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
    await app.click(OWNER2_ID, "Añadir canal o grupo", bot_id=CLONE_ID)
    assert url_of(app, OWNER2_ID, "Añadir canal") == add_to_channel_url(CLONE_USERNAME)
    assert url_of(app, OWNER2_ID, "Añadir grupo") == add_to_group_url(CLONE_USERNAME)
    # A super admin has owner rights in every bot, but the 👑 panel only exists in the main bot.
    await app.send(SUPER_ID, "/start", bot_id=CLONE_ID)
    assert has_button(app, SUPER_ID, "Pausar todo") and not has_button(app, SUPER_ID, "Panel")


# ---------------------------------------------------------------------------------- partners & visitors
async def test_visitors_of_the_main_bot_are_welcomed_to_emesh(app: App) -> None:
    await app.send(USER_ID, "/start")
    # They come to create their own bot: what eMesh is, and that publishing needs a bot of their own. The main
    # network is private, but that is not their business.
    assert app.last_text(USER_ID) == WELCOME
    assert button_rows(app, USER_ID) == [["🤖 Crear mi bot"], ["📖 Guía"], ["⚙️ Ajustes"]]
    create = button_of(app, USER_ID, "Crear mi bot")
    assert create["style"] == "success" and create["callback_data"] == MenuCB(screen="clone").pack()
    # The owner's @username is the support contact once known.
    await app.send(SUPER_ID, "/start")
    await app.send(USER_ID, "/start")
    assert url_of(app, USER_ID, "Soporte") == "https://t.me/superadmin"
    assert ["📖 Guía", "🛟 Soporte ↗"] in button_rows(app, USER_ID)
    async with edit_bot(app) as rec:
        rec.support_username = "ayuda_bot"
    await app.send(USER_ID, "/start")
    assert url_of(app, USER_ID, "Soporte") == "https://t.me/ayuda_bot"


async def test_the_main_bot_also_explains_how_to_join_its_network_when_it_is_open(app: App) -> None:
    async with edit_bot(app) as rec:
        rec.join_open = True
        rec.min_members = 500
    await app.send(USER_ID, "/start")
    assert app.last_text(USER_ID) == (
        f"{WELCOME}\n\n{JOIN_STEPS.format(bot=MAIN_BOT_USERNAME)}\n\n{JOIN_PAUSE}\n\n"
        "👤 Mínimo para unirse: <b>500</b> miembros.\n\n⏳ La administración revisa cada canal antes de aceptarlo.")
    assert button_rows(app, USER_ID)[:2] == [["🤖 Crear mi bot"], ["➕ Añadir a mi canal ↗", "➕ Añadir a mi grupo ↗"]]
    assert url_of(app, USER_ID, "Añadir a mi canal") == add_to_channel_url(MAIN_BOT_USERNAME)
    assert url_of(app, USER_ID, "Añadir a mi grupo") == add_to_group_url(MAIN_BOT_USERNAME)
    async with edit_bot(app) as rec:
        rec.join_approval = False
        rec.min_members = 0
    await app.send(USER_ID, "/start")
    assert "Mínimo" not in app.last_text(USER_ID) and "revisa" not in app.last_text(USER_ID)


async def test_visitors_of_a_clone_get_the_steps_to_join(app: App) -> None:
    await add_clone(app)
    async with edit_bot(app, CLONE_ID) as rec:
        rec.join_open = True
    await app.send(USER_ID, "/start", bot_id=CLONE_ID)
    assert app.last_text(USER_ID) == (f"{JOIN_STEPS.format(bot=CLONE_USERNAME)}\n\n{JOIN_PAUSE}\n\n"
                                      "⏳ La administración revisa cada canal antes de aceptarlo.")
    rows = button_rows(app, USER_ID)
    assert rows[0] == ["➕ Añadir a mi canal ↗", "➕ Añadir a mi grupo ↗"] and rows[-1] == ["🤖 Crea tu propio bot"]
    assert url_of(app, USER_ID, "Añadir a mi canal") == add_to_channel_url(CLONE_USERNAME)
    app.fake.add_user(779, "Eng", "eng", lang="en")
    await app.send(779, "/start", bot_id=CLONE_ID)
    assert app.last_text(779).startswith(f"🤝 <b>Join the network of @{CLONE_USERNAME}</b>\nYour channel or group "
                                         "will get its posts automatically. Joining takes a minute:\n\n1. Tap ➕ <b>Add "
                                         "to my channel</b> (or <b>to my group</b>) and pick which one.\n")


async def test_the_default_welcome_promises_pauses_only_when_partners_can_pause(app: App) -> None:
    async with edit_bot(app) as rec:
        rec.join_open = True
        rec.join_approval = False
        rec.partners_can_pause = False
    await app.send(USER_ID, "/start")
    text = app.last_text(USER_ID)
    assert text.endswith(JOIN_STEPS.format(bot=MAIN_BOT_USERNAME))
    assert "pausar" not in text.lower()


async def test_the_welcome_escapes_the_name(app: App) -> None:
    app.fake.add_user(556, "Ana <b>&", "ana")
    await app.send(556, "/start")
    assert app.last_text(556).startswith("👋 <b>¡Hola, Ana &lt;b&gt;&amp;!</b> Te damos la bienvenida")


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
    assert not has_button(app, USER_ID, "Crea tu propio bot") and not has_button(app, USER_ID, "Crear mi bot")
    assert app.last_text(USER_ID).startswith("🔒 <b>Esta red es privada.</b>")  # no platform introduction
    await add_clone(app, owner_id=OWNER2_ID)
    await app.send(OWNER2_ID, "/start")  # their bots stay in sight
    assert button_rows(app, OWNER2_ID)[-1] == ["🤖 Mis bots (1)"]


async def test_main_bot_user_with_clones_sees_my_bots(app: App) -> None:
    await add_clone(app)
    await app.send(OWNER2_ID, "/start")
    assert button_rows(app, OWNER2_ID)[:2] == [["🤖 Crear mi bot"], ["🤖 Mis bots (1)"]]
    assert callback_of(app, OWNER2_ID, "Mis bots") == MenuCB(screen="mybots").pack()


async def test_home_follows_the_language_of_the_user(app: App) -> None:
    app.fake.add_user(777, "Eng", "eng", lang="en")
    await app.send(777, "/start")
    text = app.last_text(777)
    assert text.startswith("👋 <b>Hi, Eng!</b> Welcome to <b>eMesh</b>.\n\n")
    assert "🤖 <b>To post to your channels you need your own bot.</b>" in text
    assert button_rows(app, 777) == [["🤖 Create my bot"], ["📖 Guide"], ["⚙️ Settings"]]
    await add_clone(app)
    await app.send(777, "/start", bot_id=CLONE_ID)
    assert "🔒 <b>This network is private.</b>" in app.last_text(777)
    assert has_button(app, 777, "Create your own bot")


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
    assert not has_button(app, SUPER_ID, "Crear mi bot") and has_button(app, SUPER_ID, "Panel")
    exit_button = button_of(app, SUPER_ID, "Salir de")
    assert exit_button["text"] == f"🚪 Salir de @{CLONE_USERNAME}" and exit_button["style"] == "danger"
    assert button_rows(app, SUPER_ID)[-1] == [f"🚪 Salir de @{CLONE_USERNAME}"]
    await app.click(SUPER_ID, "Añadir canal o grupo")  # the clone's bot is the one added
    assert app.last_text(SUPER_ID) == f"🛠 Gestionando <b>@{CLONE_USERNAME}</b>\n\n{ADD_CHAT}"
    assert url_of(app, SUPER_ID, "Añadir canal") == add_to_channel_url(CLONE_USERNAME)
    assert url_of(app, SUPER_ID, "Añadir grupo") == add_to_group_url(CLONE_USERNAME)
    await app.click(SUPER_ID, "Regresar")
    await app.click(SUPER_ID, "Salir de")
    assert (await get_bu(app, SUPER_ID)).ws_bot_id is None
    assert last_answer(app)["text"] == f"🚪 Has dejado de gestionar @{CLONE_USERNAME}."
    text = app.last_text(SUPER_ID)
    assert text.startswith("🕸 <b>Tu red de distribución</b>") and "Gestionando" not in text
    assert "📣 Canales y grupos: <b>0</b>" in text and not has_button(app, SUPER_ID, "Salir de")
    await app.click(SUPER_ID, "Añadir canal o grupo")
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
    assert app.last_text(USER_ID) == WELCOME


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
    for feature in ("Pausar todo", "Añadir canal o grupo", "Canales externos", "&amp;&amp;", "copiar:", "rotación",
                    "Sin rotación", "horario propio", "Anti-spam", "uno a la vez", "/admin @usuario", "/deladmin",
                    "Mis avisos", "Zona horaria", "Estadísticas", "Crear mi bot", "48 h", "Asistente de configuración",
                    "las pausas de los socios"):
        assert feature in admin, feature
    admin_en = " ".join(t(f"guide.admin.{i}", "en") for i in range(1, 6))
    assert "Importar" not in admin and "Import" not in admin_en  # there is no import any more
    assert "Add channel or group" in admin_en
    # The partners pause within the admins' rules, and the admins can resume any pause.
    pauses = t("guide.admin.2", "es")
    assert "según las reglas de la red" in pauses and "por defecto, hasta que lo reanude" in pauses
    assert "Los admins pueden reanudar cualquier pausa" in pauses and "Solo su dueño puede reanudarlo" not in pauses
    partner = " ".join(t(f"guide.partner.{i}", "es") for i in range(1, 3))
    for feature in ("Añadir a mi canal", "pendiente", "dentro de las reglas de la red",
                    "la administración también puede reanudarlo", "Categorías", "Salir"):
        assert feature in partner, feature
    assert "3 días, 7 días" not in partner  # not every network allows them
    hub_2 = t("guide.hub.2", "es")
    assert "Usar token" in hub_2 and "/newbot" in hub_2 and "preguntas rápidas" in hub_2
