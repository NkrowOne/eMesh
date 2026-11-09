"""Start module: timezone picker (continent -> America's regions -> country -> zone), typed zone, onboarding of a new
clone's owner, the first-visit question of users, the refresh of every next time of the network, and the data behind
the picker."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, available_timezones

import pytest

from app.bot.routers.timezone import ASK_HOME, ASK_JOIN, COUNTRIES_PER_PAGE, TzCB
from app.data.timezones import (
    CONTINENTS,
    COUNTRIES,
    ZONE_LABELS,
    countries_of,
    resolve_zone,
    utc_offset_label,
    zone_label,
)
from app.db.base import utcnow
from app.db.models import ChatGroup, Post, PostStatus, SchedMode
from app.ui.callbacks import InputCancelCB, MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_start_helpers import (
    CLONE_ID,
    add_clone,
    add_group,
    add_post,
    button_texts,
    callback_of,
    dms_to,
    edit_bot,
    fsm_state,
    get_bot,
    get_bu,
    has_button,
    last_answer,
    last_buttons,
    make_admin,
    manage,
)

CONTINENT_BUTTONS = ["🌎 América", "🌍 Europa", "🌏 Asia", "🌍 África", "🌏 Oceanía"]
REGION_BUTTONS = ["🌎 América del Norte", "🌎 Centroamérica y Caribe", "🌎 América del Sur"]
PICK = "👇 Elige tu <b>continente</b> y luego tu <b>país</b>."
ONBOARDING = "👋 <b>¡Te damos la bienvenida a tu bot!</b>\nYa funciona; déjalo listo en un minuto:\n"
WELCOME_QUESTION = ("👋 <b>¡Hola!</b> Antes de empezar, elige tu <b>zona horaria</b>: así verás las fechas y las horas "
                    "en tu hora local.\n   └ Solo se pregunta una vez.")
TEN = {"mode": "times", "times": "10:00", "days": "0123456"}


async def open_timezone(app: App, user_id: int, bot_id: int = MAIN_BOT_ID) -> None:
    await app.send(user_id, "/start", bot_id=bot_id)
    await app.click(user_id, "Ajustes", bot_id=bot_id)
    await app.click(user_id, "Zona horaria", bot_id=bot_id)


async def pick_country(app: App, user_id: int, name: str, bot_id: int = MAIN_BOT_ID,
                       next_label: str = "Siguiente") -> None:
    """Taps the country, paging through the list until it shows up."""
    for _ in range(5):
        if has_button(app, user_id, name):
            await app.click(user_id, name, bot_id=bot_id)
            return
        await app.click(user_id, next_label, bot_id=bot_id)
    raise AssertionError(f"{name!r} not found in {button_texts(app, user_id)}")


async def pick_bogota(app: App, user_id: int, bot_id: int = MAIN_BOT_ID) -> None:
    await app.click(user_id, "🌎 América", bot_id=bot_id)
    await app.click(user_id, "América del Sur", bot_id=bot_id)
    await app.click(user_id, "Colombia", bot_id=bot_id)


def assert_buttons_valid(app: App, user_id: int) -> None:
    for b in last_buttons(app, user_id):
        assert len(b["text"]) <= 64, b["text"]
        assert len(str(b.get("callback_data", "")).encode()) <= 64, b


def local(when: datetime | None, zone: str) -> str:
    assert when is not None
    return when.astimezone(ZoneInfo(zone)).strftime("%H:%M")


async def schedules(app: App) -> dict[str, int]:
    """A global frequency at 10:00 and, at 12:00, 15:00 and 18:00, a group, an own-schedule post and a one-time post
    (plus a rotation post, which has no next time)."""
    send_at = datetime(2031, 3, 3, 18, 0, tzinfo=timezone.utc)
    async with edit_bot(app) as rec:
        rec.freq = TEN
        rec.rot_next_at = utcnow() - timedelta(days=2)
    return {
        "group": await add_group(app, freq={"mode": "times", "times": "12:00", "days": "0123456"}),
        "global_group": await add_group(app, name="Sin frecuencia"),
        "own": await add_post(app, mode=SchedMode.OWN, freq={"mode": "times", "times": "15:00", "days": "0123456"}),
        "once": await add_post(app, mode=SchedMode.ONCE, send_at=send_at),
        "paused": await add_post(app, mode=SchedMode.OWN, freq=TEN, status=PostStatus.PAUSED),
        "rotation": await add_post(app),
    }


# ------------------------------------------------------------------------------------------ the flows
async def test_timezone_root_for_admins(app: App) -> None:
    await open_timezone(app, SUPER_ID)
    text = app.last_text(SUPER_ID)
    assert text.startswith("🗺 <b>Zona horaria</b>\n\nCon ella se calculan las frecuencias y las fechas de envío de "
                           "la red.")
    assert re.search(r"🕐 Actual: <b>Europe/Madrid</b> \(UTC\+[12]\) · \d{2}:\d{2}", text)
    assert "Es la zona de la red" not in text  # admins always see the network's timezone
    assert text.endswith(PICK)
    # A super admin also chooses the photo of this menu (the same in every bot).
    assert button_texts(app, SUPER_ID) == [*CONTINENT_BUTTONS, "✍️ Escribir zona", "🖼 Poner imagen", "🔙 Regresar"]
    assert callback_of(app, SUPER_ID, "Regresar") == MenuCB(screen="settings").pack()
    assert callback_of(app, SUPER_ID, "Escribir") == TzCB(a="w").pack()
    assert callback_of(app, SUPER_ID, "🌎 América") == TzCB(a="r").pack()
    assert callback_of(app, SUPER_ID, "Europa") == TzCB(a="c", c="eur").pack()
    assert_buttons_valid(app, SUPER_ID)


async def test_timezone_root_for_users(app: App) -> None:
    await open_timezone(app, USER_ID)
    text = app.last_text(USER_ID)
    assert "Las fechas y las horas se muestran en tu zona horaria." in text
    assert "🕐 Actual: <b>Europe/Madrid</b>" in text and "   └ Es la zona de la red." in text
    assert button_texts(app, USER_ID) == [*CONTINENT_BUTTONS, "✍️ Escribir zona", "🔙 Regresar"]  # no photo buttons


async def test_admin_change_recalculates_every_next_time(app: App) -> None:
    ids = await schedules(app)
    await open_timezone(app, SUPER_ID)
    await app.click(SUPER_ID, "Asia")
    assert "<b>🌏 Asia</b>" in app.last_text(SUPER_ID) and "👇 Elige tu país:" in app.last_text(SUPER_ID)
    await pick_country(app, SUPER_ID, "Japón")
    rec = await get_bot(app)
    assert (rec.timezone, rec.timezone_set) == ("Asia/Tokyo", True)
    assert (await get_bu(app, SUPER_ID)).timezone is None  # the personal setting is untouched
    text = app.last_text(SUPER_ID)
    assert text.startswith("✅ Zona horaria de la red: <b>Asia/Tokyo</b>. Los próximos envíos se han recalculado.")
    assert "🗺 Zona horaria: Asia/Tokyo (UTC+9)" in text  # back on the settings screen
    now = utcnow()
    assert rec.rot_next_at is not None and rec.rot_next_at > now and local(rec.rot_next_at, "Asia/Tokyo") == "10:00"
    async with app.db() as s:
        group = await s.get(ChatGroup, ids["group"])
        no_freq = await s.get(ChatGroup, ids["global_group"])
        posts = {key: await s.get(Post, ids[key]) for key in ("own", "once", "paused", "rotation")}
    assert group is not None and local(group.rot_next_at, "Asia/Tokyo") == "12:00"
    assert no_freq is not None and no_freq.rot_next_at is None  # it follows the global frequency
    assert local(posts["own"].next_send_at, "Asia/Tokyo") == "15:00"
    assert posts["once"].next_send_at == posts["once"].send_at  # a fixed moment doesn't move
    assert posts["paused"].next_send_at is None and posts["rotation"].next_send_at is None
    # Another zone moves them again.
    await app.click(SUPER_ID, "Zona horaria")
    await app.click(SUPER_ID, "Europa")
    await pick_country(app, SUPER_ID, "Francia")
    rec = await get_bot(app)
    assert rec.timezone == "Europe/Paris" and local(rec.rot_next_at, "Europe/Paris") == "10:00"
    async with app.db() as s:
        own = await s.get(Post, ids["own"])
    assert own is not None and local(own.next_send_at, "Europe/Paris") == "15:00"


async def test_countries_with_several_zones_list_them(app: App) -> None:
    await open_timezone(app, SUPER_ID)
    await app.click(SUPER_ID, "Europa")
    await app.click(SUPER_ID, "España")
    text = app.last_text(SUPER_ID)
    assert text.startswith("🇪🇸 <b>España</b>") and "👇 Elige tu zona horaria:" in text
    texts = button_texts(app, SUPER_ID)
    assert len(texts) == 3 and texts[2] == "🔙 Regresar"
    assert re.fullmatch(r"✅ Península y Baleares \(UTC\+[12]\)", texts[0])  # the current zone is ticked
    assert re.fullmatch(r"🕐 Islas Canarias \(UTC\+[01]\)", texts[1])
    assert callback_of(app, SUPER_ID, "Regresar") == TzCB(a="c", c="eur", p=0).pack()
    await app.click(SUPER_ID, "Islas Canarias")
    assert (await get_bot(app)).timezone == "Atlantic/Canary"
    await app.click(SUPER_ID, "Zona horaria")
    await app.click(SUPER_ID, "🌎 América")
    await app.click(SUPER_ID, "América del Norte")
    await app.click(SUPER_ID, "Estados Unidos")
    assert len(last_buttons(app, SUPER_ID)) == 8
    await app.click(SUPER_ID, "Los Ángeles")
    assert (await get_bot(app)).timezone == "America/Los_Angeles"
    assert_buttons_valid(app, SUPER_ID)


async def test_back_from_a_zone_list_returns_to_the_right_country_page(app: App) -> None:
    index = [c.code for c in countries_of("eur", "es")].index("RU")
    page = index // COUNTRIES_PER_PAGE
    assert page > 0  # the interesting case: not the first page
    await open_timezone(app, SUPER_ID)
    await app.click(SUPER_ID, "Europa")
    for _ in range(page):
        await app.click(SUPER_ID, "Siguiente")
    await app.click(SUPER_ID, "Rusia")
    assert len(last_buttons(app, SUPER_ID)) == len(COUNTRIES["RU"].zones) + 1
    assert callback_of(app, SUPER_ID, "Regresar") == TzCB(a="c", c="eur", p=page).pack()
    await app.click(SUPER_ID, "Regresar")
    assert has_button(app, SUPER_ID, "Rusia") and f"Página {page + 1} de" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Rusia")
    await app.click(SUPER_ID, "Vladivostok")
    assert (await get_bot(app)).timezone == "Asia/Vladivostok"


async def test_users_set_their_own_timezone_through_the_regions_of_america(app: App) -> None:
    ids = await schedules(app)
    await open_timezone(app, USER_ID)
    before = (await get_bot(app)).rot_next_at
    await app.click(USER_ID, "🌎 América")
    assert app.last_text(USER_ID) == "<b>🌎 América</b>\n\n👇 Elige tu región:"
    assert button_texts(app, USER_ID) == [*REGION_BUTTONS, "🔙 Regresar"]
    assert callback_of(app, USER_ID, "Regresar") == MenuCB(screen="timezone").pack()
    await app.click(USER_ID, "América del Norte")
    assert callback_of(app, USER_ID, "Regresar") == TzCB(a="r").pack()  # back to the regions
    await app.click(USER_ID, "Regresar")
    assert button_texts(app, USER_ID) == [*REGION_BUTTONS, "🔙 Regresar"]
    await app.click(USER_ID, "América del Norte")
    await app.click(USER_ID, "México")
    assert len(last_buttons(app, USER_ID)) == len(COUNTRIES["MX"].zones) + 1
    await app.click(USER_ID, "Ciudad de México")
    assert (await get_bu(app, USER_ID)).timezone == "America/Mexico_City"
    rec = await get_bot(app)
    assert rec.timezone == "Europe/Madrid" and rec.rot_next_at == before  # users never move the network
    async with app.db() as s:
        own = await s.get(Post, ids["own"])
    assert own is not None and own.next_send_at is None  # nothing was recalculated
    text = app.last_text(USER_ID)
    assert text.startswith("✅ Tu zona horaria es ahora <b>America/Mexico_City</b>.")
    assert "🗺 Zona horaria: America/Mexico_City" in text
    await app.click(USER_ID, "Zona horaria")
    assert "Actual: <b>America/Mexico_City</b>" in app.last_text(USER_ID)
    assert "Es la zona de la red" not in app.last_text(USER_ID)


async def test_admins_of_a_clone_set_the_clone_timezone(app: App) -> None:
    await add_clone(app)
    await make_admin(app, USER_ID, CLONE_ID)
    await app.click(USER_ID, "Ajustes", bot_id=CLONE_ID)
    await app.click(USER_ID, "Zona horaria", bot_id=CLONE_ID)
    assert not has_button(app, USER_ID, "imagen")  # only super admins choose the photo of the menu
    await app.click(USER_ID, "Europa", bot_id=CLONE_ID)
    await pick_country(app, USER_ID, "Francia", bot_id=CLONE_ID)
    assert (await get_bot(app, CLONE_ID)).timezone == "Europe/Paris"
    assert (await get_bu(app, USER_ID, CLONE_ID)).timezone is None
    assert (await get_bot(app)).timezone == "Europe/Madrid"


async def test_a_super_admin_managing_a_clone_changes_the_clone_timezone(app: App) -> None:
    await add_clone(app)
    await manage(app, SUPER_ID, CLONE_ID)
    await open_timezone(app, SUPER_ID)
    assert "Gestionando" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Asia")
    await pick_country(app, SUPER_ID, "Japón")
    assert (await get_bot(app, CLONE_ID)).timezone == "Asia/Tokyo"
    assert (await get_bot(app)).timezone == "Europe/Madrid"


# ---------------------------------------------------------------------------------------- onboarding
async def test_new_clone_asks_its_owner_for_the_timezone_first(app: App) -> None:
    await add_clone(app, timezone_set=False)
    await app.send(USER_ID, "/start", bot_id=CLONE_ID)
    assert "Te damos la bienvenida a tu bot" not in app.last_text(USER_ID)  # only its owner is asked
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    text = app.last_text(OWNER2_ID)
    # A welcome with what comes next, then why the zone is asked (only once).
    assert text.startswith(f"{ONBOARDING}1. 🗺 Elige la zona horaria.\n2. 🧭 Responde unas preguntas rápidas.\n"
                           "3. ➕ Añade tus canales y 📝 crea tu primer mensaje.\n\n🗺 <b>Zona horaria</b>\n")
    assert "Telegram no la comparte con los bots, así que se pregunta solo una vez" in text and text.endswith(PICK)
    assert "Actual" not in text and "Europe/Madrid" not in text  # nothing chosen yet
    assert button_texts(app, OWNER2_ID) == [*CONTINENT_BUTTONS, "✍️ Escribir zona"]  # no way back
    # Going back from a list returns to the onboarding, not to the settings.
    await app.click(OWNER2_ID, "Europa", bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "Regresar", bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID).startswith(ONBOARDING)
    await app.click(OWNER2_ID, "🌎 América", bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "Regresar", bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID).startswith(ONBOARDING)
    await app.click(OWNER2_ID, "Europa", bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "España", bot_id=CLONE_ID)
    assert not any(b.startswith("✅") for b in button_texts(app, OWNER2_ID))
    await app.click(OWNER2_ID, "Islas Canarias", bot_id=CLONE_ID)
    rec = await get_bot(app, CLONE_ID)
    assert rec.timezone == "Atlantic/Canary" and rec.timezone_set
    assert rec.rot_next_at is not None and rec.rot_next_at > utcnow()
    # It is the owner's own zone too: reused in every bot of the platform.
    assert (await get_bu(app, OWNER2_ID, CLONE_ID)).timezone == "Atlantic/Canary"
    text = app.last_text(OWNER2_ID)
    assert text.startswith("✅ Zona horaria de la red: <b>Atlantic/Canary</b>.\n\n"
                           "🕸 <b>Tu red de distribución</b>")  # then the home (this clone's wizard was done)
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID).startswith("🕸 <b>Tu red de distribución</b>")


async def test_onboarding_continues_with_the_setup_wizard(app: App) -> None:
    await add_clone(app, timezone_set=False, setup_done=False)  # a brand new clone
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID).startswith(ONBOARDING)  # the timezone comes first
    await app.click(OWNER2_ID, "Asia", bot_id=CLONE_ID)
    await pick_country(app, OWNER2_ID, "Japón", bot_id=CLONE_ID)
    rec = await get_bot(app, CLONE_ID)
    assert rec.timezone == "Asia/Tokyo" and rec.timezone_set and not rec.setup_done
    text = app.last_text(OWNER2_ID)
    assert text.startswith("✅ Zona horaria de la red: <b>Asia/Tokyo</b>.\n\n🧭 <b>Asistente de configuración</b>\n")
    assert "🤝 <b>¿Aceptas canales de otras personas?</b>" in text
    assert has_button(app, OWNER2_ID, "Saltar el asistente")
    # Until the wizard is finished or skipped, /start opens it again; then the home.
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID).startswith("🧭 <b>Asistente de configuración</b>")
    await app.click(OWNER2_ID, "Saltar el asistente", bot_id=CLONE_ID)
    assert (await get_bot(app, CLONE_ID)).setup_done
    assert app.last_text(OWNER2_ID).startswith("🕸 <b>Tu red de distribución</b>")
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID).startswith("🕸 <b>Tu red de distribución</b>")


async def test_onboarding_with_a_typed_zone(app: App) -> None:
    await add_clone(app, timezone_set=False)
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "Escribir zona", bot_id=CLONE_ID)
    await app.send(OWNER2_ID, "America/Bogota", bot_id=CLONE_ID)
    rec = await get_bot(app, CLONE_ID)
    assert rec.timezone == "America/Bogota" and rec.timezone_set
    assert (await get_bu(app, OWNER2_ID, CLONE_ID)).timezone == "America/Bogota"
    assert "Tu red de distribución" in app.last_text(OWNER2_ID)


async def test_new_clone_asks_the_timezone_first_whatever_the_link(app: App) -> None:
    await add_clone(app, timezone_set=False)
    await app.send(USER_ID, "/start join", bot_id=CLONE_ID)
    assert not app.last_text(USER_ID).startswith(ONBOARDING)
    for link in ("/start join", "/start c12", "/start p5"):
        await app.send(OWNER2_ID, link, bot_id=CLONE_ID)
        assert app.last_text(OWNER2_ID).startswith(ONBOARDING), link


async def test_onboarding_is_not_asked_in_a_workspace_nor_in_the_main_bot(app: App) -> None:
    await add_clone(app, timezone_set=False)
    await manage(app, SUPER_ID, CLONE_ID)  # a super admin managing someone else's new clone
    await app.send(SUPER_ID, "/start")
    assert "Tu red de distribución" in app.last_text(SUPER_ID) and ONBOARDING not in app.last_text(SUPER_ID)
    async with edit_bot(app) as rec:
        rec.timezone_set = False
    await app.send(SUPER_ID, "/start", bot_id=CLONE_ID)  # not its owner
    assert ONBOARDING not in app.last_text(SUPER_ID)


# ------------------------------------------------------------------------------------ first visit
@pytest.mark.ask_timezone
async def test_users_choose_their_timezone_before_the_home(app: App) -> None:
    await app.send(USER_ID, "/start")
    text = app.last_text(USER_ID)
    assert text == f"{WELCOME_QUESTION}\n\n{PICK}"  # no current zone: the network's is never offered as theirs
    assert button_texts(app, USER_ID) == [*CONTINENT_BUTTONS, "✍️ Escribir zona"]  # required: no way back
    assert callback_of(app, USER_ID, "🌎 América") == TzCB(a="r", o=ASK_HOME).pack()
    await app.click(USER_ID, "🌎 América")
    assert callback_of(app, USER_ID, "Regresar") == MenuCB(screen="timezone", arg=ASK_HOME).pack()
    await app.click(USER_ID, "Regresar")  # back to the question, still without a way out
    assert app.last_text(USER_ID) == f"{WELCOME_QUESTION}\n\n{PICK}"
    await app.click(USER_ID, "Europa")
    await app.click(USER_ID, "España")
    assert not any(b.startswith("✅") for b in button_texts(app, USER_ID))  # nothing chosen yet
    assert callback_of(app, USER_ID, "Regresar") == TzCB(a="c", c="eur", p=0, o=ASK_HOME).pack()
    await app.click(USER_ID, "Regresar")
    await app.click(USER_ID, "Regresar")
    await pick_bogota(app, USER_ID)
    assert (await get_bu(app, USER_ID)).timezone == "America/Bogota"
    text = app.last_text(USER_ID)
    assert text.startswith("✅ Tu zona horaria: <b>America/Bogota</b>. Puedes cambiarla en ⚙️ Ajustes.\n\n"
                           "👋 <b>¡Hola, Pepe!</b> Te damos la bienvenida a <b>eMesh</b>.")  # then the home, once
    await app.send(USER_ID, "/start")
    assert app.last_text(USER_ID).startswith("👋 <b>¡Hola, Pepe!</b>")
    assert (await get_bot(app)).timezone == "Europe/Madrid"  # users never move the network


@pytest.mark.ask_timezone
async def test_a_typed_zone_on_the_first_visit(app: App) -> None:
    await app.send(USER_ID, "/start")
    await app.click(USER_ID, "Escribir zona")
    assert await fsm_state(app, USER_ID) == "StartTimezoneFSM:zone"
    assert callback_of(app, USER_ID, "Cancelar") == InputCancelCB(screen="timezone", arg=ASK_HOME).pack()
    await app.click(USER_ID, "Cancelar")
    assert app.last_text(USER_ID).startswith(WELCOME_QUESTION)  # back to the question
    await app.click(USER_ID, "Escribir zona")
    await app.send(USER_ID, "nope")
    assert "Esa zona horaria no es válida" in app.last_text(USER_ID)
    await app.send(USER_ID, "america/lima")
    assert (await get_bu(app, USER_ID)).timezone == "America/Lima"
    assert await fsm_state(app, USER_ID) is None
    text = app.last_text(USER_ID)
    assert text.startswith("✅ Tu zona horaria: <b>America/Lima</b>.")
    assert "Te damos la bienvenida a <b>eMesh</b>" in text


@pytest.mark.ask_timezone
async def test_users_of_a_clone_are_asked_too_but_never_admins_owners_or_the_hub(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    await app.send(SUPER_ID, "/start")
    assert app.last_text(SUPER_ID).startswith("🕸 <b>Tu red de distribución</b>")
    await add_clone(app)
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID).startswith("🕸 <b>Tu red de distribución</b>")
    await app.send(USER_ID, "/start", bot_id=CLONE_ID)
    assert app.last_text(USER_ID).startswith(WELCOME_QUESTION)
    async with app.db() as s:
        from app.db.models import BotUser, Role

        bu = await s.get(BotUser, (CLONE_ID, USER_ID))
        assert bu is not None
        bu.role = Role.ADMIN  # promoted before answering: admins see the network's zone
    await app.send(USER_ID, "/start", bot_id=CLONE_ID)
    assert app.last_text(USER_ID).startswith("🕸 <b>Tu red de distribución</b>")
    assert (await get_bu(app, USER_ID, CLONE_ID)).timezone is None
    monkeypatch.setattr(app.settings, "MAIN_BOT_MODE", "hub")  # the hub runs no network: nothing to show in a zone
    await app.send(444, "/start")
    assert app.last_text(444).startswith("🕸 <b>eMesh · Tu propia red de distribución</b>")


@pytest.mark.ask_timezone
async def test_join_link_asks_the_timezone_then_opens_the_join_screen(app: App) -> None:
    async with edit_bot(app) as rec:
        rec.join_open = True
    await app.send(USER_ID, "/start join")
    assert app.last_text(USER_ID).startswith(WELCOME_QUESTION)
    assert callback_of(app, USER_ID, "Escribir zona") == TzCB(a="w", o=ASK_JOIN).pack()
    await pick_bogota(app, USER_ID)
    assert (await get_bu(app, USER_ID)).timezone == "America/Bogota"
    assert "1️⃣ Añade el bot como administrador" in app.last_text(USER_ID)  # the join screen
    assert last_answer(app)["text"] == "✅ Tu zona horaria: America/Bogota. Puedes cambiarla en ⚙️ Ajustes."
    await app.send(USER_ID, "/start join")
    assert "1️⃣ Añade el bot como administrador" in app.last_text(USER_ID)
    # A typed zone: the confirmation is a message before the join screen, which stays at the bottom.
    await app.send(444, "/start join")
    await app.click(444, "Escribir zona")
    await app.send(444, "Asia/Tokyo")
    assert (await get_bu(app, 444)).timezone == "Asia/Tokyo"
    texts = dms_to(app, 444)
    assert texts[-2] == "✅ Tu zona horaria: <b>Asia/Tokyo</b>. Puedes cambiarla en ⚙️ Ajustes."
    assert "1️⃣ Añade el bot como administrador" in texts[-1]


# ---------------------------------------------------------------------------------------- pagination
async def test_country_lists_are_sorted_paginated_and_in_two_columns(app: App) -> None:
    await open_timezone(app, SUPER_ID)
    await app.click(SUPER_ID, "Europa")
    pages = -(-len(CONTINENTS["eur"]) // COUNTRIES_PER_PAGE)
    assert pages == 3
    seen: list[str] = []
    for page in range(pages):
        assert f"📄 Página {page + 1} de {pages}" in app.last_text(SUPER_ID)
        markup = app.last_panel(SUPER_ID).params["reply_markup"]["inline_keyboard"]
        country_rows = [row for row in markup if all(b["callback_data"].startswith("tz:k:") for b in row)]
        assert all(len(row) <= 2 for row in country_rows) and len(country_rows[0]) == 2
        seen += [b["callback_data"].split(":")[3] for row in country_rows for b in row]
        nav = [b["text"] for b in last_buttons(app, SUPER_ID) if b["callback_data"].startswith("tz:c:")]
        assert nav == (["Siguiente ➡️"] if page == 0 else ["⬅️ Anterior", "Siguiente ➡️"] if page < pages - 1
                       else ["⬅️ Anterior"])
        assert callback_of(app, SUPER_ID, "Regresar") == MenuCB(screen="timezone").pack()
        assert_buttons_valid(app, SUPER_ID)
        if page < pages - 1:
            await app.click(SUPER_ID, "Siguiente")
    assert seen == [c.code for c in countries_of("eur", "es")]  # every country exactly once, in order


async def test_small_regions_have_a_single_page(app: App) -> None:
    await open_timezone(app, SUPER_ID)
    await app.click(SUPER_ID, "🌎 América")
    await app.click(SUPER_ID, "América del Norte")
    assert "Página" not in app.last_text(SUPER_ID)
    assert not has_button(app, SUPER_ID, "Siguiente") and not has_button(app, SUPER_ID, "Anterior")
    assert button_texts(app, SUPER_ID)[:3] == ["🇧🇲 Bermudas", "🇨🇦 Canadá", "🇺🇸 Estados Unidos"]


async def test_names_follow_the_language(app: App) -> None:
    app.fake.add_user(700, "Eng", "eng", lang="en")
    await app.send(700, "/start")
    await app.click(700, "Settings")
    await app.click(700, "Timezone")
    assert "🗺 <b>Timezone</b>" in app.last_text(700)
    assert button_texts(app, 700)[:6] == ["🌎 America", "🌍 Europe", "🌏 Asia", "🌍 Africa", "🌏 Oceania",
                                         "✍️ Type zone"]
    await app.click(700, "America")
    assert button_texts(app, 700) == ["🌎 North America", "🌎 Central America & Caribbean", "🌎 South America",
                                      "🔙 Back"]
    assert "👇 Choose your region:" in app.last_text(700)
    await app.click(700, "Back")
    await app.click(700, "Europe")
    assert button_texts(app, 700)[:3] == ["🇦🇱 Albania", "🇦🇩 Andorra", "🇦🇹 Austria"]
    await pick_country(app, 700, "Spain", next_label="Next")
    await app.click(700, "Canary Islands")
    assert (await get_bu(app, 700)).timezone == "Atlantic/Canary"
    assert "✅ Your timezone is now <b>Atlantic/Canary</b>." in app.last_text(700)


async def test_every_screen_of_the_picker_renders(app: App) -> None:
    """Walks all continent pages and all multi-zone countries: valid buttons, nothing raises."""
    presses = 0

    async def walk(data: str) -> int:
        nonlocal presses
        user_id = 9000 + presses // 15  # the flood control allows 30 updates per 10 s and user
        presses += 1
        await app.press(user_id, data)
        return user_id

    user_id = await walk(TzCB(a="r").pack())
    assert len(last_buttons(app, user_id)) == len(REGION_BUTTONS) + 1
    for continent, codes in CONTINENTS.items():
        pages = -(-len(codes) // COUNTRIES_PER_PAGE)
        for page in range(pages):
            user_id = await walk(TzCB(a="c", c=continent, p=page).pack())
            assert_buttons_valid(app, user_id)
            assert len(last_buttons(app, user_id)) >= 2
        for code in codes:
            country = COUNTRIES[code]
            if len(country.zones) > 1:
                user_id = await walk(TzCB(a="k", c=continent, k=code, p=0).pack())
                assert len(last_buttons(app, user_id)) == len(country.zones) + 1, code
                assert_buttons_valid(app, user_id)


async def test_forged_timezone_callbacks_fall_back_to_the_root(app: App) -> None:
    await open_timezone(app, USER_ID)
    forged = [TzCB(a="z", k="XX", i=0), TzCB(a="z", k="US", i=99), TzCB(a="z", k="US", i=-1),
              TzCB(a="c", c="zzz"), TzCB(a="c", c="ame"), TzCB(a="k", c="eur", k="ZZ"), TzCB(a="k", c="nope", k="ES")]
    for cb in forged:
        await app.press(USER_ID, cb.pack())
        assert app.last_text(USER_ID).startswith("🗺 <b>Zona horaria</b>"), cb
    assert (await get_bu(app, USER_ID)).timezone is None
    assert (await get_bot(app)).timezone == "Europe/Madrid"
    await app.press(USER_ID, TzCB(a="c", c="eur", p=99).pack())  # out of range pages are clamped
    assert "Página 3 de 3" in app.last_text(USER_ID)
    await app.press(USER_ID, TzCB(a="c", c="eur", o=77).pack())  # an unknown origin is the normal picker
    assert callback_of(app, USER_ID, "Regresar") == MenuCB(screen="timezone").pack()
    await app.press(USER_ID, MenuCB(screen="timezone", arg=77).pack())
    assert app.last_text(USER_ID).startswith("🗺 <b>Zona horaria</b>") and has_button(app, USER_ID, "Regresar")


# ---------------------------------------------------------------------------------------- typed zone
async def test_typed_zone_for_admins(app: App) -> None:
    async with edit_bot(app) as rec:
        rec.freq = TEN
    await open_timezone(app, SUPER_ID)
    await app.click(SUPER_ID, "Escribir zona")
    assert await fsm_state(app, SUPER_ID) == "StartTimezoneFSM:zone"
    assert "<code>Europe/Madrid</code>" in app.last_text(SUPER_ID)
    for bad in ("Mars/Olympus", "madrid", "../etc/passwd", "America", "localtime", "🙂"):
        await app.send(SUPER_ID, bad)
        assert "Esa zona horaria no es válida" in app.last_text(SUPER_ID), repr(bad)
        assert "<code>Europe/Madrid</code>" in app.last_text(SUPER_ID)  # the prompt is repeated
        assert await fsm_state(app, SUPER_ID) == "StartTimezoneFSM:zone"
    assert (await get_bot(app)).timezone == "Europe/Madrid"
    await app.send(SUPER_ID, "  asia/kolkata ")
    rec = await get_bot(app)
    assert rec.timezone == "Asia/Kolkata" and local(rec.rot_next_at, "Asia/Kolkata") == "10:00"
    assert await fsm_state(app, SUPER_ID) is None
    assert app.last_text(SUPER_ID).startswith("✅ Zona horaria de la red: <b>Asia/Kolkata</b>")
    await app.click(SUPER_ID, "Zona horaria")
    await app.click(SUPER_ID, "Escribir zona")
    await app.send(SUPER_ID, "America/New York")  # spaces stand for underscores
    assert (await get_bot(app)).timezone == "America/New_York"


async def test_typed_zone_for_users_cancel_and_commands(app: App) -> None:
    await open_timezone(app, USER_ID)
    await app.click(USER_ID, "Escribir zona")
    await app.send(USER_ID, "UTC")
    assert (await get_bu(app, USER_ID)).timezone == "UTC"
    assert (await get_bot(app)).timezone == "Europe/Madrid"
    await app.click(USER_ID, "Zona horaria")
    await app.click(USER_ID, "Escribir zona")
    await app.send(USER_ID, "nonsense")
    await app.click(USER_ID, "Cancelar")  # the re-prompt keeps the cancel button
    assert await fsm_state(app, USER_ID) is None
    assert app.last_text(USER_ID).startswith("🗺 <b>Zona horaria</b>")  # back to the picker
    await app.click(USER_ID, "Escribir zona")
    await app.send(USER_ID, "/cancel")
    assert await fsm_state(app, USER_ID) is None
    assert (await get_bu(app, USER_ID)).timezone == "UTC"


# ---------------------------------------------------------------------------------------------- data
SPANISH_SPEAKING = {"ES", "MX", "GT", "HN", "SV", "NI", "CR", "PA", "CU", "DO", "PR", "CO", "VE", "EC", "PE", "BO",
                    "CL", "AR", "PY", "UY", "GQ"}


def test_every_zone_of_the_data_exists() -> None:
    known = available_timezones()
    for country in COUNTRIES.values():
        assert country.zones, country.code
        for zone in country.zones:
            assert zone in known, f"{country.code}: {zone}"
        assert len(set(country.zones)) == len(country.zones), country.code
        assert len(country.zones) <= 12, f"{country.code} would need zone pagination"


def test_data_is_consistent() -> None:
    assert list(CONTINENTS) == ["nam", "cam", "sam", "eur", "asi", "afr", "oce"]
    listed: set[str] = set()
    for key, codes in CONTINENTS.items():
        assert len(set(codes)) == len(codes), key
        assert set(codes) <= set(COUNTRIES), key
        listed |= set(codes)
    assert listed == set(COUNTRIES)  # no orphan country
    for code, country in COUNTRIES.items():
        assert code == country.code and re.fullmatch(r"[A-Z]{2}", code)
        assert country.es.strip() and country.en.strip()
        assert len(country.flag) == 2 and all(0x1F1E6 <= ord(ch) <= 0x1F1FF for ch in country.flag)
    assert set(ZONE_LABELS) <= {z for c in COUNTRIES.values() for z in c.zones}
    assert SPANISH_SPEAKING <= set(COUNTRIES)


def test_countries_are_sorted_by_name_ignoring_accents() -> None:
    assert [c.es for c in countries_of("sam", "es")][:3] == ["Argentina", "Bolivia", "Brasil"]
    assert [c.es for c in countries_of("eur", "es")][:3] == ["Albania", "Alemania", "Andorra"]
    assert [c.en for c in countries_of("eur", "en")][:3] == ["Albania", "Andorra", "Austria"]
    assert countries_of("unknown", "es") == []


def test_resolve_zone() -> None:
    assert resolve_zone("Europe/Madrid") == "Europe/Madrid"
    assert resolve_zone("  europe/madrid  ") == "Europe/Madrid"
    assert resolve_zone("AMERICA/NEW YORK") == "America/New_York"
    assert resolve_zone("utc") == "UTC"
    for bad in ("", "   ", "Madrid", "America", "Mars/Olympus", "../etc/passwd", "localtime", "posixrules",
                "Factory", "Europe/Madrid\x00", "A" * 200):
        assert resolve_zone(bad) is None, repr(bad)


def test_utc_offset_label_and_zone_labels() -> None:
    winter = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
    assert utc_offset_label("Europe/Madrid", winter) == "UTC+1"
    assert utc_offset_label("Europe/Madrid", summer) == "UTC+2"
    assert utc_offset_label("Asia/Kolkata", winter) == "UTC+5:30"
    assert utc_offset_label("America/St_Johns", winter) == "UTC-3:30"
    assert utc_offset_label("Not/AZone", winter) == "UTC+0"  # an invalid stored zone never breaks the screen
    assert zone_label("Atlantic/Canary", "es") == "Islas Canarias"
    assert zone_label("Atlantic/Canary", "en") == "Canary Islands"
    assert zone_label("America/Argentina/Buenos_Aires", "en") == "Buenos Aires"


def test_callback_data_of_the_picker_fits_telegram_limits() -> None:
    for cb in (TzCB(a="k", c="cam", k="VC", p=99, o=ASK_JOIN), TzCB(a="z", k="CD", i=11, o=ASK_JOIN),
               TzCB(a="c", c="eur", p=3, o=ASK_HOME), TzCB(a="w", o=ASK_JOIN), TzCB(a="r", o=ASK_HOME),
               TzCB(a="m"), TzCB(a="x")):
        assert len(cb.pack().encode()) <= 64
