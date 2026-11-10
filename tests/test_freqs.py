"""⏰ Frecuencias dashboard, rotation order, 🛡 anti-spam, permissions and workspaces."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.bot.routers.freqs import FqCB, slots_text, toggle_day, when_text
from app.db.base import utcnow
from app.db.models import DEFAULT_FREQ, BotUser, ChatGroup, ChatStatus, Post, PostStatus, Role, SchedMode
from app.db.models import Bot as BotRecord
from app.services import freq
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_groups_helpers import (
    NO_PERMISSION,
    NOT_FOUND,
    add_chat,
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


TWO_HOURS = {"mode": "interval", "every": 120, "window": "", "days": "0123456"}
EVERY_4H = {"mode": "interval", "every": 240, "window": "08:00-22:00", "days": "0123456"}
TIMES = {"mode": "times", "times": "10:00,22:00", "days": "01234"}


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=timezone.utc)


def test_when_and_slots_texts() -> None:
    now = utc(2026, 11, 6, 9, 0)  # 10:00 in Madrid
    assert when_text(utc(2026, 11, 6, 10, 0), "Europe/Madrid", now) == "11:00 AM"
    assert when_text(utc(2026, 11, 7, 7, 0), "Europe/Madrid", now) == "07/11 08:00 AM"
    assert when_text(None, "Europe/Madrid", now) == "—"
    slots = [utc(2026, 11, 6, 21, 0), utc(2026, 11, 6, 22, 0), utc(2026, 11, 7, 7, 0)]
    assert slots_text(slots, "Europe/Madrid") == "06/11 10:00 PM, 11:00 PM, 07/11 08:00 AM"
    assert slots_text([], "Europe/Madrid") == "—"
    assert toggle_day("01234", 4) == "0123" and toggle_day("0", 6) == "06"


async def test_dashboard_shows_every_frequency_and_its_chats(app: App) -> None:
    cine = await add_group(app, "Cine", freq=TWO_HOURS)
    news = await add_group(app, "Noticias")
    late = await add_group(app, "Estrenos", freq=TIMES)
    await add_chat(app, -1001, "Sin grupo")  # global
    await add_chat(app, -1002, "Noticias 1", groups=[news])  # its only group follows the global one
    await add_chat(app, -1003, "Cine 1", groups=[cine])
    await add_chat(app, -1004, "Cine y Estrenos", groups=[cine, late])  # the first group with its own one
    await add_chat(app, -1005, "Estrenos 1", groups=[late])
    await add_chat(app, -1006, "Pausado", groups=[cine], admin_paused=True)  # doesn't receive: not counted
    await add_chat(app, -1007, "Pendiente", groups=[cine], status=ChatStatus.PENDING)
    await add_post(app, "Propio 1", mode=SchedMode.OWN)
    await add_post(app, "Propio 2", mode=SchedMode.OWN)
    await add_post(app, "Propio pausado", mode=SchedMode.OWN, status=PostStatus.PAUSED)
    await add_post(app, "En rotación")
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "freqs")
    text = app.last_text(SUPER_ID)
    assert text.startswith("⏰ <b>Frecuencias</b>\nCada canal recibe un mensaje en cada turno de su frecuencia")
    assert "🌐 <b>Global</b>: a las 12:00\n   └ 2 chats · ≈ 1 al día · próximo: " in text
    assert "🗂 <b>Cine</b>: cada 2 h\n   └ 2 chats · ≈ 12 al día · próximo: " in text
    assert "🗂 <b>Noticias</b>: 🌐 la global\n" in text
    assert "🗂 <b>Estrenos</b>: a las 10:00 y 22:00 · de lunes a viernes\n   └ 1 chat · ≈ 2 al día · próximo: " in text
    assert "💡 Un canal sigue la frecuencia del primero de sus grupos de canales (en este orden)" in text
    assert "⏰ Mensajes con su propio horario: <b>2</b>" in text
    assert "🔁 Rotación: <b>en orden</b>" in text
    assert "🛡 Anti-spam: sin máximo diario · sin separación mínima · 🧹 uno a la vez ✖️" in text
    assert "pausada" not in text
    assert button_texts(app) == [
        "🌐 Global: a las 12:00", "🗂 Cine: cada 2 h", "🗂 Noticias: 🌐 la global",
        "🗂 Estrenos: a las 10:00 y 22:00 · de lunes a viernes", "✅ En orden", "⚪ Al azar", "⚪ Sin rotación",
        "🛡 Anti-spam", "🔙 Regresar",
    ]
    assert button_data(app, "Global") == MenuCB(screen="freq_edit").pack()
    assert button_data(app, "Regresar") == MenuCB(screen="home").pack()


async def test_dashboard_next_slot_and_pause(app: App) -> None:
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        rec.paused = True
    await started(app, SUPER_ID)
    before = utcnow()
    await open_menu(app, SUPER_ID, "freqs")
    text = app.last_text(SUPER_ID)
    assert "⏸ <b>La distribución está pausada.</b>" in text
    assert "💡 Para dar a unos chats su propia frecuencia, crea un 🗂 grupo de canales." in text
    expected = [when_text(s, "Europe/Madrid", before) for s in freq.upcoming(DEFAULT_FREQ, "Europe/Madrid", before, 2)]
    assert any(f"· próximo: {e}\n" in text for e in expected)


async def test_dashboard_pages(app: App) -> None:
    for i in range(1, 13):
        await add_group(app, f"Grupo {i:02d}")
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "freqs")
    text = app.last_text(SUPER_ID)
    assert "<b>Grupo 10</b>" in text and "Grupo 11" not in text and "📄 Página 1 de 2" in text
    await app.click(SUPER_ID, "Siguiente")
    text = app.last_text(SUPER_ID)
    assert "<b>Grupo 12</b>" in text and "Grupo 10" not in text and "🌐 <b>Global</b>" in text
    await app.click(SUPER_ID, "Al azar")  # stays on the same page
    assert "📄 Página 2 de 2" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Sin rotación")  # no groups' frequencies, no pages
    assert "Grupo" not in app.last_text(SUPER_ID) and "Página" not in app.last_text(SUPER_ID)
    assert not any("Anterior" in b or "Siguiente" in b for b in button_texts(app))
    await app.click(SUPER_ID, "Al azar")  # the page is kept
    assert "<b>Grupo 12</b>" in app.last_text(SUPER_ID) and "📄 Página 2 de 2" in app.last_text(SUPER_ID)


async def test_rotation_order(app: App) -> None:
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "freqs")
    await app.click(SUPER_ID, "Al azar")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).rotation == "random"
    text = app.last_text(SUPER_ID)
    assert "🔁 Rotación: <b>al azar</b>\n   └ Cada canal recibe uno al azar" in text
    assert "✅ Al azar" in button_texts(app) and "✅ Al azar" in answers(app)
    await app.click(SUPER_ID, "En orden")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).rotation == "seq"
    assert "del más antiguo al más nuevo" in app.last_text(SUPER_ID)
    for forged in (3, 5):
        await app.press(SUPER_ID, FqCB(a="rot", v=forged).pack())
    assert (await load(app, BotRecord, MAIN_BOT_ID)).rotation == "seq"
    async with app.db() as s:
        (await s.get(BotRecord, MAIN_BOT_ID)).rotation = "bogus"  # an unknown value shows as in order
    await open_menu(app, SUPER_ID, "freqs")
    assert "🔁 Rotación: <b>en orden</b>" in app.last_text(SUPER_ID) and "✅ En orden" in button_texts(app)


async def test_no_rotation_hides_the_global_and_groups_frequencies(app: App) -> None:
    clone = 7_000_000_202
    await app.add_clone(clone, "clon_off_bot", OWNER2_ID)
    await add_group(app, "Cine", freq=TWO_HOURS)
    await add_group(app, "Noticias")
    await add_chat(app, -1001, "Sin grupo")
    await add_post(app, "Propio", mode=SchedMode.OWN)
    await add_post(app, "Rotación 1")
    await add_post(app, "Rotación 2")
    await add_post(app, "Rotación pausada", status=PostStatus.PAUSED)  # not counted: not active
    await add_post(app, "Rotación del clon", bot_id=clone)  # another network
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "freqs")
    await app.click(SUPER_ID, "Sin rotación")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).rotation == "off"
    assert answers(app)[-1] == "✅ Sin rotación"
    text = app.last_text(SUPER_ID)
    assert text == (
        "⏰ <b>Frecuencias</b>\nSin rotación: cada mensaje se envía con su propio horario.\n\n"
        "⏰ Mensajes con su propio horario: <b>1</b>\n"
        "   └ Van a todo su destino en cada turno de su horario, fuera de la rotación (📝 Mensajes › ⏰ Programación)."
        "\n\n🔁 Rotación: <b>desactivada</b>\n"
        "   └ No hay turnos: cada mensaje se envía a sus propias horas (📝 Mensajes › ⏰ Programación).\n"
        "⚠️ 2 mensajes 🔁 en rotación no se envían mientras esté desactivada.\n"
        "🛡 Anti-spam: sin máximo diario · sin separación mínima · 🧹 uno a la vez ✖️")
    assert button_texts(app) == ["⚪ En orden", "⚪ Al azar", "✅ Sin rotación", "🛡 Anti-spam", "🔙 Regresar"]

    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        rec.paused = True
        for post in (await s.execute(select(Post).where(Post.bot_id == MAIN_BOT_ID))).scalars():
            if post.mode == SchedMode.ROTATION:
                post.status = PostStatus.PAUSED
    await open_menu(app, SUPER_ID, "freqs")
    text = app.last_text(SUPER_ID)
    assert "⏸ <b>La distribución está pausada.</b>" in text and "🔁 Rotación: <b>desactivada</b>" in text
    assert "no se envían mientras" not in text and "🌐 <b>Global</b>" not in text

    await app.click(SUPER_ID, "En orden")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).rotation == "seq"
    text = app.last_text(SUPER_ID)
    assert text.startswith("⏰ <b>Frecuencias</b>\nCada canal recibe un mensaje en cada turno de su frecuencia")
    assert "🌐 <b>Global</b>: a las 12:00" in text and "🗂 <b>Cine</b>: cada 2 h" in text
    assert "🌐 Global: a las 12:00" in button_texts(app) and "✅ En orden" in button_texts(app)


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
        "✅ Sin separación", "⚪ 15 min", "⚪ 30 min", "⚪ 1 h", "⚪ 2 h", "✏️ Otra separación", "✖️ Uno a la vez",
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
    await app.click(SUPER_ID, "Otra separación")
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


async def test_non_admins_cannot_change_frequencies(app: App, wakes: list[int]) -> None:
    g = await add_group(app, "Cine")
    p = await add_post(app, "Promo", mode=SchedMode.OWN)
    await started(app, USER_ID)
    forged = [FqCB(a="ev", t=0, v=60), FqCB(a="ev", t=g, v=60), FqCB(a="ev", t=-p, v=60), FqCB(a="glob", t=g),
              FqCB(a="mode", t=0, v=1), FqCB(a="day", t=0, v=0), FqCB(a="dp", t=0, v=1), FqCB(a="wq", t=0, v=1),
              FqCB(a="evx", t=0), FqCB(a="rot", v=1), FqCB(a="mx", v=6), FqCB(a="gp", v=30), FqCB(a="one"),
              FqCB(a="mxx")]
    for data in forged:
        await app.press(USER_ID, data.pack())
    for name, arg in (("freqs", 0), ("freq_edit", 0), ("freq_edit", g), ("freq_edit", -p), ("antispam", 0)):
        await open_menu(app, USER_ID, name, arg)
    assert answers(app) == [NO_PERMISSION] * (len(forged) + 5)
    await app.send(USER_ID, "2 h")
    rec = await load(app, BotRecord, MAIN_BOT_ID)
    assert (rec.freq, rec.rotation, rec.max_per_day, rec.min_gap, rec.one_at_a_time) == (DEFAULT_FREQ, "seq", 0, 0,
                                                                                         False)
    assert (await load(app, ChatGroup, g)).freq is None
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


async def test_super_admin_edits_the_frequencies_of_the_clone_he_manages(app: App, wakes: list[int]) -> None:
    clone = 7_000_000_201
    await app.add_clone(clone, "clon_cine_bot", OWNER2_ID)
    async with app.db() as s:
        rec = await s.get(BotRecord, clone)
        rec.timezone, rec.freq = "America/Mexico_City", EVERY_4H
    clone_group = await add_group(app, "Grupo del clon", bot_id=clone)
    main_group = await add_group(app, "Principal")
    await add_chat(app, -5001, "Canal del clon", bot_id=clone)
    await manage(app, clone)

    await open_menu(app, SUPER_ID, "freqs")
    text = app.last_text(SUPER_ID)
    assert "Gestionando <b>@clon_cine_bot</b>" in text
    assert "Grupo del clon" in text and "Principal" not in text
    assert "🌐 <b>Global</b>: cada 4 h · 08:00-22:00\n   └ 1 chat ·" in text

    before = utcnow()
    await app.press(SUPER_ID, FqCB(a="ev", t=0, v=60).pack())
    rec, main = await load(app, BotRecord, clone), await load(app, BotRecord, MAIN_BOT_ID)
    assert rec.freq == {"mode": "interval", "every": 60, "window": "08:00-22:00", "days": "0123456"}
    assert main.freq == DEFAULT_FREQ
    assert rec.rot_next_at in freq.upcoming(rec.freq, "America/Mexico_City", before, 2)
    assert "🗺 Zona horaria: America/Mexico_City" in app.last_text(SUPER_ID)

    await app.press(SUPER_ID, FqCB(a="glob", t=clone_group).pack())
    assert (await load(app, ChatGroup, clone_group)).freq == rec.freq
    await app.press(SUPER_ID, FqCB(a="glob", t=main_group).pack())
    assert answers(app)[-1] == NOT_FOUND
    assert (await load(app, ChatGroup, main_group)).freq is None

    await app.press(SUPER_ID, FqCB(a="mx", v=4).pack())
    await app.press(SUPER_ID, FqCB(a="rot", v=1).pack())
    rec, main = await load(app, BotRecord, clone), await load(app, BotRecord, MAIN_BOT_ID)
    assert (rec.max_per_day, rec.rotation) == (4, "random")
    assert (main.max_per_day, main.rotation) == (0, "seq")
    assert wakes == [1, 1]


async def test_old_buttons_in_a_hub_main_bot_do_nothing(app: App, wakes: list[int]) -> None:
    g = await add_group(app, "Cine")
    await started(app, SUPER_ID)
    app.settings.MAIN_BOT_MODE = "hub"  # the main bot runs no network any more
    await app.press(SUPER_ID, FqCB(a="ev", t=0, v=60).pack())
    await app.press(SUPER_ID, FqCB(a="rot", v=1).pack())
    await open_menu(app, SUPER_ID, "freq_edit_dash", g)  # a hub hides network screens: it opens the home
    assert answers(app) == ["⌛ Este botón ya no está activo. Pulsa /start."] * 2 + [""]
    rec = await load(app, BotRecord, MAIN_BOT_ID)
    assert (rec.freq, rec.rotation) == (DEFAULT_FREQ, "seq") and wakes == []
