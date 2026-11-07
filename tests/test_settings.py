"""Start module: ⚙️ settings (owner / admin / user / hub), 🔔 notifications, 🤝 external chats (toggles, minimum
members, welcome text), 🛟 support contact, 👮 admins screen and 🌍 language."""
from __future__ import annotations

import re

import pytest

from app.bot.routers.settings import AdCB, LgCB, SsCB, parse_int, parse_support
from app.bot.routers.setup import SuCB
from app.db.models import Role, User
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_start_helpers import (
    CLONE_ID,
    CLONE_USERNAME,
    add_clone,
    add_group,
    button_of,
    button_rows,
    button_texts,
    callback_of,
    denied,
    dms_to,
    edit_bot,
    fsm_state,
    get_bot,
    get_bu,
    has_button,
    last_answer,
    make_admin,
    manage,
    url_of,
)


async def open_settings(app: App, user_id: int, bot_id: int = MAIN_BOT_ID) -> None:
    await app.send(user_id, "/start", bot_id=bot_id)
    await app.click(user_id, "Ajustes", bot_id=bot_id)


async def open_externals(app: App) -> None:
    await open_settings(app, SUPER_ID)
    await app.click(SUPER_ID, "Canales externos")


# ------------------------------------------------------------------------------------------ settings
async def test_owner_settings(app: App) -> None:
    await open_settings(app, SUPER_ID)
    text = app.last_text(SUPER_ID)
    assert re.fullmatch(
        r"⚙️ <b>Ajustes</b>\n🗺 Zona horaria: Europe/Madrid \(UTC\+[12]\)\n🌍 Idioma: 🇪🇸 Español\n👮 Admins: 1\n"
        r"🔔 Mis avisos: alertas ✅ · resumen diario ✅ · informe de cada envío ✖️\n"
        r"🤝 Canales externos: ✖️ no admitidos \(red privada\)\n🛟 Soporte: @superadmin", text), text
    assert button_rows(app, SUPER_ID) == [["🗺 Zona horaria", "🌍 Idioma"], ["🔔 Mis avisos", "👮 Admins"],
                                          ["🤝 Canales externos", "🛟 Soporte"], ["🧭 Asistente de configuración"],
                                          ["🔙 Regresar"]]
    for label, name in {"Zona horaria": "timezone", "Idioma": "lang", "Mis avisos": "notifications",
                        "Admins": "admins", "Canales externos": "externals", "Soporte": "support",
                        "Regresar": "home"}.items():
        assert callback_of(app, SUPER_ID, label) == MenuCB(screen=name).pack(), label
    assert callback_of(app, SUPER_ID, "Asistente de configuración") == MenuCB(screen="setup", arg=1).pack()
    async with edit_bot(app) as rec:
        rec.join_open = True
    await open_settings(app, SUPER_ID)
    assert "🤝 Canales externos: ✅ admitidos (con aprobación)" in app.last_text(SUPER_ID)
    async with edit_bot(app) as rec:
        rec.join_approval = False
        rec.support_username = "ayuda_bot"
    await make_admin(app, USER_ID)
    await open_settings(app, SUPER_ID)
    text = app.last_text(SUPER_ID)
    assert "🤝 Canales externos: ✅ admitidos (entran solos)" in text and "🛟 Soporte: @ayuda_bot" in text
    assert "👮 Admins: 2" in text


async def test_admins_see_the_bot_settings_read_only(app: App) -> None:
    await make_admin(app, USER_ID)
    await open_settings(app, USER_ID)
    text = app.last_text(USER_ID)
    assert "🤝 Canales externos:" in text and "🛟 Soporte:" in text
    assert text.endswith("\n\n🔒 Los canales externos y el soporte solo los cambia el propietario.")
    assert button_rows(app, USER_ID) == [["🗺 Zona horaria", "🌍 Idioma"], ["🔔 Mis avisos", "👮 Admins"],
                                         ["🔙 Regresar"]]
    # Forged buttons of the owner's screens are refused.
    for data in (MenuCB(screen="externals").pack(), MenuCB(screen="support").pack(),
                 SsCB(action="tg", key="open").pack(), SsCB(action="tg", key="approval").pack(),
                 SsCB(action="min").pack(), SsCB(action="jt").pack(), SsCB(action="jt_reset").pack(),
                 SsCB(action="sup").pack(), SsCB(action="sup_reset").pack(), SsCB(action="tg", key="pause").pack(),
                 SsCB(action="pmax", key="72").pack(), MenuCB(screen="setup", arg=1).pack(),
                 SuCB(s=1, v=0).pack()):
        await app.press(USER_ID, data)
        assert denied(app), data
    assert await fsm_state(app, USER_ID) is None
    rec = await get_bot(app)
    assert (rec.join_open, rec.join_approval, rec.partners_can_pause, rec.pause_max_hours) == (False, True, True, 0)


async def test_user_settings(app: App) -> None:
    await open_settings(app, USER_ID)
    text = app.last_text(USER_ID)
    assert re.fullmatch(r"⚙️ <b>Ajustes</b>\n🗺 Zona horaria: Europe/Madrid \(UTC\+[12]\)\n"
                        r"   └ Las fechas se muestran en esta hora.\n🌍 Idioma: 🇪🇸 Español\n🔔 Mis avisos: alertas ✅",
                        text), text
    assert button_rows(app, USER_ID) == [["🗺 Zona horaria", "🌍 Idioma"], ["🔔 Mis avisos"], ["🔙 Regresar"]]
    for data in (MenuCB(screen="admins").pack(), AdCB(user_id=SUPER_ID).pack(), SsCB(action="tg", key="open").pack()):
        await app.press(USER_ID, data)
        assert denied(app), data


async def test_hub_settings(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.settings, "MAIN_BOT_MODE", "hub")
    await open_settings(app, SUPER_ID)
    assert button_rows(app, SUPER_ID) == [["🗺 Zona horaria", "🌍 Idioma"], ["🔙 Regresar"]]
    assert "Canales externos" not in app.last_text(SUPER_ID)
    await app.press(SUPER_ID, SsCB(action="tg", key="open").pack())
    assert denied(app) and not (await get_bot(app)).join_open


# ------------------------------------------------------------------------------------- notifications
async def test_notifications_of_an_admin(app: App) -> None:
    await open_settings(app, SUPER_ID)
    await app.click(SUPER_ID, "Mis avisos")
    text = app.last_text(SUPER_ID)
    assert text == ("🔔 <b>Mis avisos</b>\n\n🔔 Alertas de la red: ✅\n"
                    "   └ Canales que se pausan, se unen, salen o pierden permisos.\n📋 Resumen diario: ✅\n"
                    "   └ Cada mañana, los envíos del día anterior y lo que necesita atención.\n"
                    "📤 Informe de cada envío: ✖️\n"
                    "   └ Un mensaje al terminar cada envío: entregados, fallos y omitidos.")
    assert button_texts(app, SUPER_ID) == ["✅ Alertas de la red", "✅ Resumen diario", "✖️ Informe de cada envío",
                                           "🔙 Regresar"]
    assert callback_of(app, SUPER_ID, "Regresar") == MenuCB(screen="settings").pack()
    await app.click(SUPER_ID, "Alertas de la red")
    await app.click(SUPER_ID, "Resumen diario")
    await app.click(SUPER_ID, "Informe de cada envío")
    bu = await get_bu(app, SUPER_ID)
    assert (bu.notify, bu.summary, bu.run_reports) == (False, False, True)
    assert "🔔 Alertas de la red: ✖️" in app.last_text(SUPER_ID)
    assert button_texts(app, SUPER_ID)[:3] == ["✖️ Alertas de la red", "✖️ Resumen diario", "✅ Informe de cada envío"]
    await app.click(SUPER_ID, "Alertas de la red")
    assert (await get_bu(app, SUPER_ID)).notify
    await app.click(SUPER_ID, "Regresar")
    assert "🔔 Mis avisos: alertas ✅ · resumen diario ✖️ · informe de cada envío ✅" in app.last_text(SUPER_ID)


async def test_notifications_of_a_user(app: App) -> None:
    await open_settings(app, USER_ID)
    await app.click(USER_ID, "Mis avisos")
    assert app.last_text(USER_ID) == ("🔔 <b>Mis avisos</b>\n\n🔔 Alertas de la red: ✅\n"
                                      "   └ Los avisos sobre tus propios canales llegan siempre.")
    assert button_texts(app, USER_ID) == ["✅ Alertas de la red", "🔙 Regresar"]
    await app.click(USER_ID, "Alertas de la red")
    assert not (await get_bu(app, USER_ID)).notify
    for key in ("summary", "reports", "nope"):  # admins only / unknown
        await app.press(USER_ID, SsCB(action="tg", key=key).pack())
        assert denied(app), key
    bu = await get_bu(app, USER_ID)
    assert (bu.summary, bu.run_reports) == (True, False)


# ---------------------------------------------------------------------------------- external chats
async def test_external_chats_toggles(app: App) -> None:
    await open_externals(app)
    text = app.last_text(SUPER_ID)
    assert text.startswith("🤝 <b>Canales externos</b>\nOtras personas pueden añadir el bot")
    assert text.endswith("🤝 Admitir canales externos: ✖️\n"
                         "   └ Ahora la red es privada: solo los admins añaden canales.")
    assert button_texts(app, SUPER_ID) == ["✖️ Admitir canales externos", "🔙 Regresar"]
    assert callback_of(app, SUPER_ID, "Regresar") == MenuCB(screen="settings").pack()
    await app.click(SUPER_ID, "Admitir canales externos")
    assert (await get_bot(app)).join_open
    text = app.last_text(SUPER_ID)
    assert ("🤝 Admitir canales externos: ✅\n✋ Aprobación manual: ✅\n"
            "   └ Las solicitudes llegan a los admins, que las aceptan o rechazan.\n🔢 Mínimo de miembros: <b>0</b>\n"
            "   └ Los canales con menos miembros no pueden unirse (0 = sin mínimo).\n"
            "💬 Texto de bienvenida: el predeterminado\n") in text
    assert ("🗂 Grupos abiertos: <b>0</b>\n"
            "   └ Los canales externos entran solos en ellos y pueden salir desde su panel.\n"
            "⏸ Los socios pueden pausar: ✅\n⏸ Pausa máxima: <b>Sin límite</b>\n"
            "   └ Tú siempre puedes reanudar una pausa.\n\n"
            "🔗 Enlace para invitar: https://t.me/emesh_test_bot?start=join\n"
            "   └ Compártelo con los dueños de canales: les explica cómo unirse.") in text
    assert button_texts(app, SUPER_ID) == ["✅ Admitir canales externos", "✅ Aprobación manual",
                                           "🔢 Mínimo de miembros: 0", "💬 Texto de bienvenida", "🗂 Grupos abiertos",
                                           "✅ Los socios pueden pausar", "⚪ 1 día", "⚪ 3 días", "⚪ 7 días",
                                           "✅ Sin límite", "🔙 Regresar"]
    await app.click(SUPER_ID, "Aprobación manual")
    assert not (await get_bot(app)).join_approval
    assert "✋ Aprobación manual: ✖️\n   └ Entran solos, sin revisión." in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Admitir canales externos")
    rec = await get_bot(app)
    assert not rec.join_open and not rec.join_approval


async def test_partners_pause_rules(app: App) -> None:
    async with edit_bot(app) as rec:
        rec.join_open = True
    await open_externals(app)
    assert button_rows(app, SUPER_ID)[-4:] == [["✅ Los socios pueden pausar"], ["⚪ 1 día", "⚪ 3 días"],
                                               ["⚪ 7 días", "✅ Sin límite"], ["🔙 Regresar"]]
    assert callback_of(app, SUPER_ID, "Los socios pueden pausar") == SsCB(action="tg", key="pause").pack()
    assert callback_of(app, SUPER_ID, "3 días") == SsCB(action="pmax", key="72").pack()
    await app.click(SUPER_ID, "7 días")
    assert (await get_bot(app)).pause_max_hours == 168
    assert "⏸ Pausa máxima: <b>7 días</b>" in app.last_text(SUPER_ID)
    assert button_rows(app, SUPER_ID)[-3:-1] == [["⚪ 1 día", "⚪ 3 días"], ["✅ 7 días", "⚪ Sin límite"]]
    await app.click(SUPER_ID, "Sin límite")
    assert button_rows(app, SUPER_ID)[-3:-1] == [["⚪ 1 día", "⚪ 3 días"], ["⚪ 7 días", "✅ Sin límite"]]
    assert (await get_bot(app)).pause_max_hours == 0
    assert "⏸ Pausa máxima: <b>Sin límite</b>" in app.last_text(SUPER_ID)
    for key in ("5", "-1", "abc", "1000", ""):  # forged values change nothing
        await app.press(SUPER_ID, SsCB(action="pmax", key=key).pack())
    assert (await get_bot(app)).pause_max_hours == 0
    # Partners that can't pause: there is no longest pause to choose, and nobody promises them pauses.
    await app.click(SUPER_ID, "Los socios pueden pausar")
    rec = await get_bot(app)
    assert not rec.partners_can_pause and rec.pause_max_hours == 0
    text = app.last_text(SUPER_ID)
    assert "⏸ Los socios pueden pausar: ✖️\n   └ Solo los admins pueden pausar sus canales." in text
    assert "Pausa máxima" not in text and not has_button(app, SUPER_ID, "Sin límite")
    assert button_rows(app, SUPER_ID)[-2:] == [["✖️ Los socios pueden pausar"], ["🔙 Regresar"]]
    await app.send(USER_ID, "/start")
    assert "Únete a la red de @emesh_test_bot" in app.last_text(USER_ID)
    assert "Puedes pausarlas" not in app.last_text(USER_ID)
    await app.click(SUPER_ID, "Los socios pueden pausar")
    assert (await get_bot(app)).partners_can_pause
    # A longest pause set some other way is shown as it is, with no choice ticked.
    async with edit_bot(app) as rec:
        rec.pause_max_hours = 12
    await open_externals(app)
    assert "⏸ Pausa máxima: <b>12 h</b>" in app.last_text(SUPER_ID)
    assert button_rows(app, SUPER_ID)[-3:-1] == [["⚪ 1 día", "⚪ 3 días"], ["⚪ 7 días", "⚪ Sin límite"]]


async def test_pause_rules_in_english(app: App) -> None:
    app.fake.users[SUPER_ID]["language_code"] = "en"  # before the first /start: the bot speaks English
    async with edit_bot(app) as rec:
        rec.join_open = True
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Settings")
    await app.click(SUPER_ID, "External channels")
    text = app.last_text(SUPER_ID)
    assert "⏸ Partners can pause: ✅\n⏸ Longest pause: <b>No limit</b>\n   └ You can always resume a pause." in text
    assert button_rows(app, SUPER_ID)[-3:-1] == [["⚪ 1 day", "⚪ 3 days"], ["⚪ 7 days", "✅ No limit"]]


async def test_open_groups_are_counted_and_linked(app: App) -> None:
    await add_group(app, name="Cine", open=True)
    await add_group(app, name="Series", open=True)
    await add_group(app, name="Privado")
    await add_clone(app)
    await add_group(app, bot_id=CLONE_ID, name="De otra red", open=True)
    async with edit_bot(app) as rec:
        rec.join_open = True
    await open_externals(app)
    assert "🗂 Grupos abiertos: <b>2</b>" in app.last_text(SUPER_ID)
    assert callback_of(app, SUPER_ID, "Grupos abiertos") == MenuCB(screen="groups").pack()


async def test_minimum_members_input(app: App) -> None:
    async with edit_bot(app) as rec:
        rec.join_open = True
    await open_externals(app)
    await app.click(SUPER_ID, "Mínimo de miembros")
    assert await fsm_state(app, SUPER_ID) == "SettingsFSM:min_members"
    assert app.last_text(SUPER_ID).startswith("🔢 <b>Mínimo de miembros</b>\n\nActual: <b>0</b>")
    assert has_button(app, SUPER_ID, "Cancelar")
    for bad in ("abc", "-5", "1.5", "999999999999"):
        await app.send(SUPER_ID, bad)
        assert app.last_text(SUPER_ID).startswith("⚠️ Envía un número entero, por ejemplo <code>500</code>."), bad
        assert await fsm_state(app, SUPER_ID) == "SettingsFSM:min_members"
    await app.send(SUPER_ID, "1.500")
    assert (await get_bot(app)).min_members == 1500
    assert await fsm_state(app, SUPER_ID) is None
    text = app.last_text(SUPER_ID)
    assert text.startswith("✅ Guardado\n\n🤝 <b>Canales externos</b>") and "🔢 Mínimo de miembros: <b>1,500</b>" in text
    assert has_button(app, SUPER_ID, "🔢 Mínimo de miembros: 1,500")
    await app.click(SUPER_ID, "Mínimo de miembros")
    await app.click(SUPER_ID, "Cancelar")
    assert await fsm_state(app, SUPER_ID) is None and (await get_bot(app)).min_members == 1500
    assert app.last_text(SUPER_ID).startswith("🤝 <b>Canales externos</b>")


async def test_welcome_text_input_and_reset(app: App) -> None:
    async with edit_bot(app) as rec:
        rec.join_open = True
        rec.join_approval = False
    await open_externals(app)
    await app.click(SUPER_ID, "Texto de bienvenida")
    assert await fsm_state(app, SUPER_ID) == "SettingsFSM:join_text"
    prompt = app.last_text(SUPER_ID)
    assert prompt.startswith("💬 <b>Texto de bienvenida</b>") and "Máximo 1000 caracteres." in prompt
    assert "📋 Texto actual:\n<blockquote>🤝 <b>Únete a la red de @emesh_test_bot</b>" in prompt  # the default
    assert not has_button(app, SUPER_ID, "Texto predeterminado")
    await app.send(SUPER_ID, None, photo="ph1", caption="Hola")
    assert app.last_text(SUPER_ID).startswith("⚠️ Envía solo texto, sin fotos ni archivos.")
    await app.send(SUPER_ID, "x" * 1001)
    assert app.last_text(SUPER_ID).startswith("⚠️ Es demasiado largo (máximo 1000 caracteres).")
    assert (await get_bot(app)).join_text is None
    await app.send(SUPER_ID, "Únete a Cine <total>",
                   entities=[{"type": "bold", "offset": 0, "length": 5}])
    assert (await get_bot(app)).join_text == "<b>Únete</b> a Cine &lt;total&gt;"
    assert app.last_text(SUPER_ID).startswith("✅ Guardado\n\n🤝 <b>Canales externos</b>")
    assert "💬 Texto de bienvenida: personalizado" in app.last_text(SUPER_ID)
    # Partners see it on the home.
    await app.send(USER_ID, "/start")
    assert "<b>Únete</b> a Cine &lt;total&gt;" in app.last_text(USER_ID)
    assert "Únete a la red de" not in app.last_text(USER_ID)
    # The prompt shows the current text (as plain text) and offers the default one back.
    await app.click(SUPER_ID, "Texto de bienvenida")
    assert "<blockquote>Únete a Cine &lt;total&gt;</blockquote>" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Texto predeterminado")
    assert (await get_bot(app)).join_text is None
    assert await fsm_state(app, SUPER_ID) is None
    assert app.last_text(SUPER_ID).startswith("↩️ Se usa el texto predeterminado.\n\n🤝 <b>Canales externos</b>")
    await app.send(USER_ID, "/start")
    assert "Únete a la red de @emesh_test_bot" in app.last_text(USER_ID)


async def test_commands_are_not_taken_as_input(app: App) -> None:
    async with edit_bot(app) as rec:
        rec.join_open = True
    await open_externals(app)
    await app.click(SUPER_ID, "Texto de bienvenida")
    await app.send(SUPER_ID, "/id")
    assert app.last_text(SUPER_ID) == f"🆔 Tu ID: <code>{SUPER_ID}</code>"
    await app.send(SUPER_ID, "/unknown")  # unknown commands leave the input
    assert await fsm_state(app, SUPER_ID) is None
    assert (await get_bot(app)).join_text is None


# ------------------------------------------------------------------------------------------- support
async def test_support_contact(app: App) -> None:
    await open_settings(app, SUPER_ID)
    await app.click(SUPER_ID, "Soporte")
    text = app.last_text(SUPER_ID)
    assert text.startswith("🛟 <b>Soporte</b>\n\nEl botón «🛟 Soporte» del inicio abre este contacto")
    assert text.endswith("📌 Actual: @superadmin (la cuenta del propietario)")
    assert button_texts(app, SUPER_ID) == ["✏️ Cambiar contacto", "🔙 Regresar"]
    await app.click(SUPER_ID, "Cambiar contacto")
    assert await fsm_state(app, SUPER_ID) == "SettingsFSM:support"
    for bad in ("not valid!", "@ab", "https://example.com/x", "t.me/+AbCdEf123456"):
        await app.send(SUPER_ID, bad)
        assert app.last_text(SUPER_ID).startswith("⚠️ No es un @usuario válido."), bad
    await app.send(SUPER_ID, "https://t.me/ayuda_bot")
    assert (await get_bot(app)).support_username == "ayuda_bot"
    assert app.last_text(SUPER_ID).startswith("✅ Guardado\n\n🛟 <b>Soporte</b>")
    assert app.last_text(SUPER_ID).endswith("📌 Actual: @ayuda_bot")
    await app.send(USER_ID, "/start")
    assert url_of(app, USER_ID, "Soporte") == "https://t.me/ayuda_bot"
    await app.click(SUPER_ID, "Usar mi cuenta")
    assert (await get_bot(app)).support_username is None
    await app.send(USER_ID, "/start")
    assert url_of(app, USER_ID, "Soporte") == "https://t.me/superadmin"


async def test_support_without_any_username(app: App) -> None:
    app.fake.users[SUPER_ID].pop("username")  # Telegram tells the username in every update
    await open_settings(app, SUPER_ID)
    async with app.db() as s:
        owner = await s.get(User, SUPER_ID)
        assert owner is not None and owner.username is None
    assert "🛟 Soporte: —" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Soporte")
    assert "📌 Actual: ninguno" in app.last_text(SUPER_ID)
    await app.send(USER_ID, "/start")
    assert not has_button(app, USER_ID, "Soporte")


@pytest.mark.parametrize(
    "text,expected",
    [("@ayuda_bot", "ayuda_bot"), ("ayuda_bot", "ayuda_bot"), ("t.me/Ayuda", "Ayuda"),
     ("https://t.me/ayuda_bot/", "ayuda_bot"), ("https://telegram.me/ayuda", "ayuda"), ("  @pepe  ", "pepe"),
     ("@ab", None), ("@1abc", None), ("hola mundo", None), ("https://t.me/+AbCdEf123", None), ("", None),
     (None, None), ("@" + "a" * 33, None)],
)
def test_parse_support(text: str | None, expected: str | None) -> None:
    assert parse_support(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [("0", 0), ("500", 500), ("1.500", 1500), ("1,500", 1500), ("1 500", 1500), (" 42 ", 42), ("-1", None),
     ("1.5", None), ("abc", None), ("", None), (None, None), ("100000001", None)],
)
def test_parse_int(text: str | None, expected: int | None) -> None:
    assert parse_int(text, 100_000_000) == expected


# -------------------------------------------------------------------------------------------- admins
async def test_admins_screen_and_removal(app: App) -> None:
    await make_admin(app, USER_ID)
    await open_settings(app, SUPER_ID)
    await app.click(SUPER_ID, "Admins")
    assert app.last_text(SUPER_ID) == (
        "👮 <b>Administradores</b>\n\n#1 ⚜️ @superadmin (111)\n#2 🔰 @pepe (333)\n\n"
        "ℹ️ Para añadir un admin envía <code>/admin @usuario</code>; para quitarlo, <code>/deladmin @usuario</code> "
        "o pulsa 🗑.\n   └ Antes debe haber abierto @emesh_test_bot y pulsado /start.")
    remove = button_of(app, SUPER_ID, "#2")
    assert remove["text"] == "🗑 #2 @pepe" and remove["style"] == "danger"
    assert remove["callback_data"] == AdCB(user_id=USER_ID).pack()
    await app.click(SUPER_ID, "#2")
    assert (await get_bu(app, USER_ID)).role == Role.USER
    assert app.last_text(SUPER_ID).startswith("✅ @pepe ya no es admin.\n\n👮 <b>Administradores</b>")
    assert not has_button(app, SUPER_ID, "#2")
    assert dms_to(app, USER_ID)[-1] == "ℹ️ Ya no eres admin de @emesh_test_bot."
    await app.press(SUPER_ID, AdCB(user_id=USER_ID).pack())  # an old button: nothing to remove
    assert (await get_bu(app, USER_ID)).role == Role.USER and "#2" not in app.last_text(SUPER_ID)


async def test_admins_see_the_list_read_only(app: App) -> None:
    await make_admin(app, USER_ID)
    await make_admin(app, OWNER2_ID)
    await open_settings(app, USER_ID)
    await app.click(USER_ID, "Admins")
    text = app.last_text(USER_ID)
    assert "#2 🔰 @pepe (333)" in text and "#3 🔰 @owner2 (222)" in text and "/admin" not in text
    assert button_texts(app, USER_ID) == ["🔙 Regresar"]
    await app.press(USER_ID, AdCB(user_id=OWNER2_ID).pack())
    assert denied(app) and (await get_bu(app, OWNER2_ID)).role == Role.ADMIN


async def test_admin_names_are_escaped(app: App) -> None:
    app.fake.add_user(444, "<b>Mal</b>")  # no @username: the name is shown
    await make_admin(app, 444)
    await open_settings(app, SUPER_ID)
    await app.click(SUPER_ID, "Admins")
    assert '<a href="tg://user?id=444">&lt;b&gt;Mal&lt;/b&gt;</a>' in app.last_text(SUPER_ID)
    assert has_button(app, SUPER_ID, "🗑 #2 <b>Mal</b>")  # button texts are plain text


# ------------------------------------------------------------------------------------------ language
async def test_language_switch(app: App) -> None:
    await open_settings(app, USER_ID)
    await app.click(USER_ID, "Idioma")
    assert app.last_text(USER_ID) == ("🌍 <b>Idioma / Language</b>\n\nElige el idioma del bot.\n"
                                      "Choose the bot language.")
    assert button_texts(app, USER_ID) == ["✅ 🇪🇸 Español", "🇬🇧 English", "🔙 Regresar"]
    await app.click(USER_ID, "English")
    assert (await get_bu(app, USER_ID)).lang == "en"
    assert last_answer(app)["text"] == "✅ Language updated."
    assert app.last_text(USER_ID).startswith("⚙️ <b>Settings</b>\n🗺 Timezone: Europe/Madrid")
    await app.click(USER_ID, "Language")
    assert button_texts(app, USER_ID) == ["🇪🇸 Español", "✅ 🇬🇧 English", "🔙 Back"]
    await app.press(USER_ID, LgCB(lang="fr").pack())  # forged: unknown language
    assert (await get_bu(app, USER_ID)).lang == "en"
    await app.click(USER_ID, "Español")
    assert (await get_bu(app, USER_ID)).lang == "es" and "⚙️ <b>Ajustes</b>" in app.last_text(USER_ID)


# ----------------------------------------------------------------------------------------- workspace
async def test_settings_while_managing_a_clone_change_the_clone(app: App) -> None:
    await add_clone(app)
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    async with edit_bot(app, CLONE_ID) as rec:
        rec.timezone = "America/Mexico_City"
    await manage(app, SUPER_ID, CLONE_ID)
    await open_settings(app, SUPER_ID)
    text = app.last_text(SUPER_ID)
    assert text.startswith(f"🛠 Gestionando <b>@{CLONE_USERNAME}</b>\n\n⚙️ <b>Ajustes</b>")
    assert "🗺 Zona horaria: America/Mexico_City" in text and "🛟 Soporte: @owner2" in text
    assert has_button(app, SUPER_ID, "Canales externos") and not has_button(app, SUPER_ID, "Asistente")
    await app.click(SUPER_ID, "Canales externos")
    assert f"https://t.me/{CLONE_USERNAME}?start=join" not in app.last_text(SUPER_ID)  # closed: no link
    await app.click(SUPER_ID, "Admitir canales externos")
    assert (await get_bot(app, CLONE_ID)).join_open and not (await get_bot(app)).join_open
    assert f"🔗 Enlace para invitar: https://t.me/{CLONE_USERNAME}?start=join" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Regresar")
    await app.click(SUPER_ID, "Soporte")
    assert app.last_text(SUPER_ID).endswith("📌 Actual: @owner2 (la cuenta del propietario)")
    await app.click(SUPER_ID, "Cambiar contacto")
    await app.send(SUPER_ID, "@soporte_cine")
    assert (await get_bot(app, CLONE_ID)).support_username == "soporte_cine"
    assert (await get_bot(app)).support_username is None
    assert has_button(app, SUPER_ID, "↩️ Usar la del propietario")  # the super admin is not its owner
    await app.click(SUPER_ID, "Regresar")
    await app.click(SUPER_ID, "Admins")
    assert "#1 ⚜️ @owner2 (222)" in app.last_text(SUPER_ID)
    assert "Antes debe haber abierto @clone_test_bot" in app.last_text(SUPER_ID)
