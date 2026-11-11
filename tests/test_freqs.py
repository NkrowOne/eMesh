"""⏰ Horarios dashboard, 🛡 anti-spam, permissions and workspaces."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.bot.routers.freqs import FqCB, slots_text, toggle_day
from app.db.base import utcnow
from app.db.models import DEFAULT_FREQ, BotUser, Post, PostStatus, Role, SchedMode
from app.db.models import Bot as BotRecord
from app.services import freq
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_groups_helpers import (
    NO_PERMISSION,
    NOT_FOUND,
    add_group,
    add_post,
    answers,
    button_data,
    button_texts,
    count_wakes,
    load,
    manage,
    open_menu,
    started,
)


@pytest.fixture
def wakes(app: App, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    return count_wakes(app, monkeypatch)


EVERY_4H = {"mode": "interval", "every": 240, "window": "08:00-22:00", "days": "0123456"}
ANTISPAM_OFF = "🛡 Anti-spam: sin máximo diario · sin separación mínima · 🧹 uno a la vez ✖️"


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=timezone.utc)


def test_slots_and_days_texts() -> None:
    slots = [utc(2026, 11, 6, 21, 0), utc(2026, 11, 6, 22, 0), utc(2026, 11, 7, 7, 0)]
    assert slots_text(slots, "Europe/Madrid") == "06/11 10:00 PM, 11:00 PM, 07/11 08:00 AM"
    assert slots_text([], "Europe/Madrid") == "—"
    assert toggle_day("01234", 4) == "0123" and toggle_day("0", 6) == "06"


async def test_dashboard_shows_the_default_schedule_and_the_scheduled_posts(app: App) -> None:
    clone = 7_000_000_202
    await app.add_clone(clone, "clon_horarios_bot", OWNER2_ID)
    await add_group(app, "Cine")  # groups of chats are only targets: not shown here
    await add_post(app, "Propio 1")
    await add_post(app, "Propio 2")
    await add_post(app, "Una vez", mode=SchedMode.ONCE)
    await add_post(app, "Propio pausado", status=PostStatus.PAUSED)  # not counted: not active
    await add_post(app, "Propio terminado", status=PostStatus.DONE)
    await add_post(app, "A mano", mode=SchedMode.MANUAL)  # only with 🚀 Enviar ahora
    await add_post(app, "Del clon", bot_id=clone)  # another network
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "freqs")
    assert app.last_text(SUPER_ID) == (
        "⏰ <b>Horarios</b>\nCada mensaje se envía a sus propias horas (📝 Mensajes › ⏰ Programación).\n\n"
        "🕐 Horario por defecto: <b>a las 12:00</b>\n"
        "   └ Cada mensaje nuevo empieza con este horario; luego se cambia en el suyo.\n"
        "⏰ Mensajes programados: <b>3</b>\n"
        f"{ANTISPAM_OFF}")
    assert button_texts(app) == ["🕐 Horario por defecto: a las 12:00", "🛡 Anti-spam", "🔙 Regresar"]
    assert button_data(app, "Horario por defecto") == MenuCB(screen="freq_edit").pack()
    assert button_data(app, "Anti-spam") == MenuCB(screen="antispam").pack()
    assert button_data(app, "Regresar") == MenuCB(screen="home").pack()


async def test_dashboard_of_a_paused_network(app: App) -> None:
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        rec.paused, rec.freq = True, EVERY_4H
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "freqs", 3)  # an old page number is ignored
    assert app.last_text(SUPER_ID) == (
        "⏰ <b>Horarios</b>\nCada mensaje se envía a sus propias horas (📝 Mensajes › ⏰ Programación).\n"
        "⏸ <b>La distribución está pausada.</b> No se envía nada hasta que se reanude.\n\n"
        "🕐 Horario por defecto: <b>cada 4 h · 08:00-22:00</b>\n"
        "   └ Cada mensaje nuevo empieza con este horario; luego se cambia en el suyo.\n"
        "⏰ Mensajes programados: <b>0</b>\n"
        f"{ANTISPAM_OFF}")
    assert button_texts(app)[0] == "🕐 Horario por defecto: cada 4 h · 08:00-22:00"


async def test_old_rotation_buttons_do_nothing(app: App) -> None:
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, FqCB(a="rot", t=0, v=1).pack())
    await app.press(SUPER_ID, "fq:rot:0:1:0")  # the old layout, with the dashboard flag
    assert answers(app) == ["⌛ Este botón ya no está activo. Pulsa /start."] * 2
    assert (await load(app, BotRecord, MAIN_BOT_ID)).freq == DEFAULT_FREQ


async def test_antispam_choices_and_custom_values(app: App) -> None:
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "freqs")
    await app.click(SUPER_ID, "🛡 Anti-spam")
    text = app.last_text(SUPER_ID)
    assert "🛡 <b>Anti-spam</b>" in text and "🚀 Enviar ahora" in text
    assert "📊 Máximo al día por chat: <b>sin límite</b>\n   └ Cuenta los mensajes recibidos desde las 00:00" in text
    assert "⏱ Separación mínima: <b>ninguna</b>\n   └ Tiempo mínimo entre dos mensajes" in text
    assert "🧹 Uno a la vez: ✖️\n   └ Antes de enviar uno nuevo, se borra el anterior" in text
    assert button_texts(app) == [
        "✅ Sin límite", "⚪ 2 al día", "⚪ 4 al día", "⚪ 6 al día", "⚪ 8 al día", "⚪ 12 al día", "✏️ Otro máximo",
        "✅ Ninguna", "⚪ 15 min", "⚪ 30 min", "⚪ 1 h", "⚪ 2 h", "✏️ Otra", "✖️ Uno a la vez",
        "🔙 Regresar",
    ]
    assert button_data(app, "Regresar") == MenuCB(screen="freqs").pack()

    await app.click(SUPER_ID, "6 al día")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).max_per_day == 6
    assert "✅ 6 al día" in button_texts(app) and "<b>6</b>" in app.last_text(SUPER_ID)

    await app.click(SUPER_ID, "Otro máximo")
    assert "📊 Ahora: <b>6</b>" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "muchos")
    assert "⚠️ Escribe un número del 0 al 100." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "101")
    assert "⚠️ Escribe un número del 0 al 100." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "5")
    assert app.last_text(SUPER_ID).startswith("✅ Guardado")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).max_per_day == 5
    assert "✅ Otro: 5 al día" in button_texts(app)
    await app.click(SUPER_ID, "Otro: 5 al día")
    await app.send(SUPER_ID, "0")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).max_per_day == 0

    await app.click(SUPER_ID, "30 min")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).min_gap == 30
    await app.click(SUPER_ID, "✏️ Otra")
    await app.send(SUPER_ID, "5 min")
    assert "⚠️ Elige entre 10 minutos y 24 horas." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "a ratos")
    assert "⚠️ No se entiende" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "45 min")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).min_gap == 45
    assert "✅ Otra: 45 min" in button_texts(app)
    await app.click(SUPER_ID, "Otra: 45 min")
    await app.click(SUPER_ID, "Cancelar")
    assert "🛡 <b>Anti-spam</b>" in app.last_text(SUPER_ID)
    assert (await load(app, BotRecord, MAIN_BOT_ID)).min_gap == 45
    await app.click(SUPER_ID, "Otra: 45 min")
    await app.send(SUPER_ID, "no")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).min_gap == 0

    await app.click(SUPER_ID, "Uno a la vez")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).one_at_a_time is True
    assert "✅ Uno a la vez" in answers(app)
    await app.press(SUPER_ID, FqCB(a="mx", v=7).pack())  # not one of the choices
    await app.press(SUPER_ID, FqCB(a="gp", v=1).pack())
    rec = await load(app, BotRecord, MAIN_BOT_ID)
    assert (rec.max_per_day, rec.min_gap) == (0, 0)

    await app.click(SUPER_ID, "15 min")
    await app.click(SUPER_ID, "4 al día")
    await app.click(SUPER_ID, "Regresar")
    assert "🛡 Anti-spam: máx. 4 al día · 15 min entre mensajes · 🧹 uno a la vez ✅" in app.last_text(SUPER_ID)


async def test_non_admins_cannot_change_schedules(app: App, wakes: list[int]) -> None:
    p = await add_post(app, "Promo")
    await started(app, USER_ID)
    forged = [FqCB(a="ev", t=0, v=60), FqCB(a="ev", t=-p, v=60), FqCB(a="mode", t=0, v=1), FqCB(a="day", t=0, v=0),
              FqCB(a="dp", t=0, v=1), FqCB(a="wq", t=0, v=1), FqCB(a="evx", t=0), FqCB(a="mx", v=6),
              FqCB(a="gp", v=30), FqCB(a="one"), FqCB(a="mxx")]
    for data in forged:
        await app.press(USER_ID, data.pack())
    for name, arg in (("freqs", 0), ("freq_edit", 0), ("freq_edit", -p), ("antispam", 0)):
        await open_menu(app, USER_ID, name, arg)
    assert answers(app) == [NO_PERMISSION] * (len(forged) + 4)
    await app.send(USER_ID, "2 h")
    rec = await load(app, BotRecord, MAIN_BOT_ID)
    assert (rec.freq, rec.max_per_day, rec.min_gap, rec.one_at_a_time) == (DEFAULT_FREQ, 0, 0, False)
    assert (await load(app, Post, p)).freq is None
    assert wakes == []


async def test_an_admin_demoted_during_an_input_cannot_finish_it(app: App) -> None:
    await started(app, OWNER2_ID)
    async with app.db() as s:
        (await s.get(BotUser, (MAIN_BOT_ID, OWNER2_ID))).role = Role.ADMIN
        (await s.get(BotRecord, MAIN_BOT_ID)).freq = EVERY_4H
    await app.press(OWNER2_ID, FqCB(a="ev", t=0, v=60).pack())  # admins can
    assert (await load(app, BotRecord, MAIN_BOT_ID)).freq["every"] == 60
    await app.press(OWNER2_ID, FqCB(a="evx", t=0).pack())
    async with app.db() as s:
        (await s.get(BotUser, (MAIN_BOT_ID, OWNER2_ID))).role = Role.USER
    await app.send(OWNER2_ID, "3 h")
    assert NO_PERMISSION in app.last_text(OWNER2_ID)
    assert (await load(app, BotRecord, MAIN_BOT_ID)).freq["every"] == 60


async def test_super_admin_edits_the_schedules_of_the_clone_he_manages(app: App, wakes: list[int]) -> None:
    clone = 7_000_000_201
    await app.add_clone(clone, "clon_cine_bot", OWNER2_ID)
    async with app.db() as s:
        rec = await s.get(BotRecord, clone)
        rec.timezone, rec.freq = "America/Mexico_City", EVERY_4H
    clone_post = await add_post(app, "Del clon", bot_id=clone)
    main_post = await add_post(app, "Principal")
    await manage(app, clone)

    await open_menu(app, SUPER_ID, "freqs")
    text = app.last_text(SUPER_ID)
    assert "Gestionando <b>@clon_cine_bot</b>" in text
    assert "🕐 Horario por defecto: <b>cada 4 h · 08:00-22:00</b>" in text and "Mensajes programados: <b>1</b>" in text

    await app.press(SUPER_ID, FqCB(a="ev", t=0, v=60).pack())
    rec, main = await load(app, BotRecord, clone), await load(app, BotRecord, MAIN_BOT_ID)
    assert rec.freq == {"mode": "interval", "every": 60, "window": "08:00-22:00", "days": "0123456"}
    assert main.freq == DEFAULT_FREQ
    assert "🗺 Zona horaria: America/Mexico_City" in app.last_text(SUPER_ID)
    assert wakes == []  # the default schedule sends nothing by itself

    before = utcnow()
    await app.press(SUPER_ID, FqCB(a="ev", t=-clone_post, v=120).pack())
    post = await load(app, Post, clone_post)
    assert post.freq["every"] == 120 and post.next_send_at in freq.upcoming(post.freq, "America/Mexico_City", before, 2)
    await app.press(SUPER_ID, FqCB(a="ev", t=-main_post, v=120).pack())
    assert answers(app)[-1] == NOT_FOUND
    assert (await load(app, Post, main_post)).freq is None

    await app.press(SUPER_ID, FqCB(a="mx", v=4).pack())
    rec, main = await load(app, BotRecord, clone), await load(app, BotRecord, MAIN_BOT_ID)
    assert (rec.max_per_day, main.max_per_day) == (4, 0)
    assert wakes == [1]


async def test_old_buttons_in_a_hub_main_bot_do_nothing(app: App, wakes: list[int]) -> None:
    await started(app, SUPER_ID)
    app.settings.MAIN_BOT_MODE = "hub"  # the main bot runs no network any more
    await app.press(SUPER_ID, FqCB(a="ev", t=0, v=60).pack())
    await open_menu(app, SUPER_ID, "freq_edit")  # a hub hides network screens: it opens the home
    assert answers(app) == ["⌛ Este botón ya no está activo. Pulsa /start.", ""]
    assert (await load(app, BotRecord, MAIN_BOT_ID)).freq == DEFAULT_FREQ and wakes == []
