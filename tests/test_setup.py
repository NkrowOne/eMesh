"""Start module: 🧭 the setup wizard of a new bot (one question per screen, the current value ticked, each answer saved
at once), its place in the onboarding of a new clone's owner, running it again from ⚙️ Ajustes and who gets it."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.bot.routers.setup import DELETE_OPTIONS, SuCB, SuFqCB
from app.data.timezones import utc_offset_label
from app.db.base import utcnow
from app.db.models import DEFAULT_FREQ, DEFAULT_PAUSE_MAX_HOURS, BotUser
from app.services import freq
from app.services.chatinfo import add_to_channel_url, add_to_group_url
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_start_helpers import (
    CLONE_ID,
    CLONE_USERNAME,
    add_clone,
    add_post,
    button_of,
    button_rows,
    button_texts,
    callback_of,
    denied,
    edit_bot,
    get_bot,
    has_button,
    last_answer,
    last_buttons,
    make_admin,
    manage,
    url_of,
)

INTRO = ("🧭 <b>Asistente de configuración</b>\nUnas preguntas rápidas para dejar la red lista. Cada respuesta se "
         "guarda al momento y todo se puede cambiar luego en ⚙️ Ajustes.")
STEP_1 = "🤝 <b>¿Aceptas canales de otras personas?</b>"
STEP_2 = "⏸ <b>¿Pueden pausar la distribución en sus canales?</b>"
STEP_ROT = "🔁 <b>¿Quieres que los mensajes se turnen?</b>"
ROT_TEXT = (
    f"{STEP_ROT}\n\n🔁 <b>Con rotación</b>: los mensajes forman una cola. A cada hora que elijas, cada canal recibe "
    "<b>uno</b>: el siguiente de la cola, en orden o al azar.\n"
    "   └ Ej.: mensajes A, B y C a las 10:00 y 18:00 → hoy A y B, mañana C y A…\n\n"
    "🕐 <b>Sin rotación</b>: no hay cola. Cada mensaje tiene su propio horario y se envía a todas sus horas.\n"
    "   └ Ej.: A a las 10:00 y B a las 18:00, todos los días.\n\n"
    "Se puede cambiar luego en ⏰ Frecuencias.")
ROT_LABELS = ["Sí, en orden", "Sí, al azar", "No, cada mensaje con su horario"]
STEP_HOURS = "⏰ <b>¿A qué horas recibe un mensaje cada canal?</b>"
HOURS_INTRO = (f"{STEP_HOURS}\nToca una hora para marcarla o quitarla, o elige una opción rápida. En cada hora marcada, "
               "cada canal recibe el siguiente mensaje de la rotación.")
HOURS_TZ = "   └ Hora de Europe/Madrid. Luego se puede afinar en ⏰ Frecuencias."
PRESETS = ["1 al día", "2 al día", "3 al día", "4 al día", "Cada 2 h", "Cada hora"]
ALL_DAYS = "0123456"
STEP_DELETE = "🗑 <b>¿Cuánto tiempo siguen publicados los mensajes?</b>"
DONE = "✅ <b>Todo listo</b>\nAsí queda la red:"
HOME = "🕸 <b>Tu red de distribución</b>"
CUSTOM_FREQ = {"mode": "interval", "every": 180, "window": "08:00-23:00", "days": "01234"}


async def new_clone(app: App) -> None:
    """A brand new clone whose owner already chose the timezone: the wizard comes next."""
    await add_clone(app, setup_done=False)


async def start(app: App, user_id: int = OWNER2_ID) -> None:
    await app.send(user_id, "/start", bot_id=CLONE_ID)


async def click(app: App, label: str, user_id: int = OWNER2_ID) -> None:
    await app.click(user_id, label, bot_id=CLONE_ID)


async def answer(app: App, step: int, index: int) -> None:
    await app.press(OWNER2_ID, SuCB(s=step, v=index).pack(), bot_id=CLONE_ID)


def rot_rows(ticked: int, back: bool = True) -> list[list[str]]:
    """The keyboard of the rotation step."""
    rows = [[f"{'✅' if i == ticked else '⚪'} {label}"] for i, label in enumerate(ROT_LABELS)]
    return rows + ([["🔙 Regresar"]] if back else [])


async def tap(app: App, action: str, v: int = 0, user_id: int = OWNER2_ID) -> None:
    """A button of step 3 (the global frequency)."""
    await app.press(user_id, SuFqCB(a=action, v=v).pack(), bot_id=CLONE_ID)


def hour_rows(*ticked: int) -> list[list[str]]:
    """The 24 hours of step 3, 6 per row, ``ticked`` ones with ✅."""
    labels = [f"✅ {h:02d}" if h in ticked else f"{h:02d}" for h in range(24)]
    return [labels[i:i + 6] for i in range(0, 24, 6)]


def hours_rows(preset: int | None, hours: tuple[int, ...], days: int | None = 0) -> list[list[str]]:
    """The keyboard of step 3: the quick options, the hours, the days, typing, continue and back."""
    presets = [f"{'✅' if i == preset else '⚪'} {label}" for i, label in enumerate(PRESETS)]
    days_row = [f"{'✅' if i == days else '⚪'} {label}" for i, label in enumerate(("Todos", "L-V", "S-D"))]
    return [presets[:3], presets[3:], *hour_rows(*hours), days_row, ["✏️ Escribir otras horas (9:30…)"],
            ["Continuar ➡️"], ["🔙 Regresar"]]


def hours_text(n: int, times: str, days: str = "todos los días") -> str:
    return f"{HOURS_INTRO}\n\n🕐 <b>{n} al día</b>: {times}\n📅 Días: {days}\n{HOURS_TZ}"


async def ticked(app: App, step: int) -> list[str]:
    """Opens ``step`` and returns its ticked options."""
    await app.press(OWNER2_ID, MenuCB(screen="setup", arg=step).pack(), bot_id=CLONE_ID)
    return [text for text in button_texts(app, OWNER2_ID) if text.startswith("✅")]


def assert_buttons_valid(app: App, user_id: int = OWNER2_ID) -> None:
    for b in last_buttons(app, user_id):
        assert len(b["text"]) <= 64, b["text"]
        assert len(str(b.get("callback_data", "")).encode()) <= 64, b


def assert_next_slot(rec_next: datetime | None, f: dict, before: datetime, after: datetime) -> None:
    """The stored next global slot was refreshed when the answer was saved (between ``before`` and ``after``)."""
    assert rec_next is not None and rec_next > before
    assert rec_next in (freq.next_slot(f, "Europe/Madrid", before), freq.next_slot(f, "Europe/Madrid", after))


# ------------------------------------------------------------------------------------------ the flow
async def test_the_whole_wizard(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    woken: list[bool] = []
    monkeypatch.setattr(app.scheduler, "wake", lambda: woken.append(True))
    await new_clone(app)
    await start(app)
    # 1. External chats: a new network is private, so «No» is ticked.
    assert app.last_text(OWNER2_ID) == (
        f"{INTRO}\n\n{STEP_1}\nPodrán añadir el bot a sus canales y grupos para recibir los mensajes de la red.\n"
        "   └ Con aprobación, cada canal nuevo llega como solicitud a los admins.")
    assert button_rows(app, OWNER2_ID) == [["⚪ Sí, con mi aprobación"], ["⚪ Sí, entran solos"],
                                           ["✅ No, solo los míos"], ["⏭ Saltar el asistente"]]
    assert callback_of(app, OWNER2_ID, "Saltar el asistente") == SuCB(s=0).pack()
    assert_buttons_valid(app)
    await click(app, "Sí, con mi aprobación")
    rec = await get_bot(app, CLONE_ID)
    assert (rec.join_open, rec.join_approval, rec.setup_done) == (True, True, False)
    # 2. The partners' pauses: no limit by default.
    assert app.last_text(OWNER2_ID) == (
        f"{STEP_2}\nCada socio la pausa desde su panel, como mucho el tiempo que elijas.\n"
        "   └ Tú siempre ves quién pausa y puedes reanudarlo.")
    assert button_rows(app, OWNER2_ID) == [["⚪ Hasta 1 día"], ["⚪ Hasta 3 días"], ["⚪ Hasta 7 días"],
                                           ["✅ Sin límite"], ["⚪ No pueden pausar"], ["🔙 Regresar"]]
    assert callback_of(app, OWNER2_ID, "Regresar") == MenuCB(screen="setup", arg=1).pack()
    assert_buttons_valid(app)
    await click(app, "Hasta 3 días")
    rec = await get_bot(app, CLONE_ID)
    assert (rec.partners_can_pause, rec.pause_max_hours) == (True, 72)
    # 3. The rotation, explained with examples: in order by default.
    assert app.last_text(OWNER2_ID) == ROT_TEXT
    assert button_rows(app, OWNER2_ID) == rot_rows(0)
    assert callback_of(app, OWNER2_ID, "Regresar") == MenuCB(screen="setup", arg=2).pack()
    assert_buttons_valid(app)
    await click(app, "Sí, en orden")
    assert (await get_bot(app, CLONE_ID)).rotation == "seq"
    # 4. The hours of the rotation: shown and ticked; once a day at 12:00 by default.
    assert app.last_text(OWNER2_ID) == hours_text(1, "12:00")
    assert button_rows(app, OWNER2_ID) == hours_rows(0, (12,))
    assert callback_of(app, OWNER2_ID, "Regresar") == MenuCB(screen="setup", arg=3).pack()
    nxt = button_of(app, OWNER2_ID, "Continuar")
    assert nxt["callback_data"] == MenuCB(screen="setup", arg=5).pack() and nxt["style"] == "success"
    assert_buttons_valid(app)
    # A quick option ticks its hours and stays on the step, saved at once.
    before = utcnow()
    await click(app, "3 al día")
    after = utcnow()
    rec = await get_bot(app, CLONE_ID)
    assert rec.freq == {"mode": "times", "times": "09:00,14:00,20:00", "days": ALL_DAYS}
    assert_next_slot(rec.rot_next_at, rec.freq, before, after)
    assert woken == [True]  # the scheduler looks at the new slot at once
    assert app.last_text(OWNER2_ID) == hours_text(3, "09:00, 14:00 y 20:00")
    assert button_rows(app, OWNER2_ID) == hours_rows(2, (9, 14, 20))
    # Then the hours are fine-tuned by touching them.
    await click(app, "22")
    await click(app, "✅ 09")
    rec = await get_bot(app, CLONE_ID)
    assert rec.freq == {"mode": "times", "times": "14:00,20:00,22:00", "days": ALL_DAYS}
    assert woken == [True, True, True]
    assert app.last_text(OWNER2_ID) == hours_text(3, "14:00, 20:00 y 22:00")
    assert button_rows(app, OWNER2_ID) == hours_rows(None, (14, 20, 22))
    await click(app, "Continuar")
    # 5. How long posts stay published: never deleted by default.
    assert app.last_text(OWNER2_ID).startswith(f"{STEP_DELETE}\nPasado ese tiempo se borran solos de los canales.")
    assert button_rows(app, OWNER2_ID) == [["⚪ 1 h", "⚪ 6 h", "⚪ 12 h"], ["⚪ 1 día", "⚪ 2 días"],
                                           ["✅ No se borran"], ["🔙 Regresar"]]
    assert callback_of(app, OWNER2_ID, "Regresar") == MenuCB(screen="setup", arg=4).pack()
    await click(app, "2 días")
    rec = await get_bot(app, CLONE_ID)
    assert rec.post_defaults == {"delete_after": 2880}
    # 6. All set: the answers, what comes next, and the wizard is done.
    assert rec.setup_done
    assert app.last_text(OWNER2_ID) == (
        f"{DONE}\n\n🤝 Canales externos: ✅ admitidos (con aprobación)\n⏸ Pausas de los socios: hasta 3 días\n"
        "🔁 Rotación: sí, en orden\n⏰ Frecuencia global: a las 14:00, 20:00 y 22:00\n🗑 Borrado automático: al cabo de 2 días\n"
        f"🗺 Zona horaria: Europe/Madrid ({utc_offset_label('Europe/Madrid')})\n\n"
        "👇 Ahora añade el bot a tus canales y grupos y crea un mensaje.\n"
        "   └ Todo se puede cambiar en ⚙️ Ajustes, ⏰ Frecuencias y 📝 Mensajes.")
    assert button_rows(app, OWNER2_ID) == [["➕ Añadir canal ↗", "➕ Añadir grupo ↗"], ["📝 Crear el primer mensaje"],
                                           ["🏠 Ir al inicio"], ["🔙 Regresar"]]
    assert url_of(app, OWNER2_ID, "Añadir canal") == add_to_channel_url(CLONE_USERNAME)
    assert url_of(app, OWNER2_ID, "Añadir grupo") == add_to_group_url(CLONE_USERNAME)
    first = button_of(app, OWNER2_ID, "Crear el primer mensaje")
    assert first["callback_data"] == MenuCB(screen="post_new").pack() and first["style"] == "success"
    assert callback_of(app, OWNER2_ID, "Regresar") == MenuCB(screen="setup", arg=5).pack()
    assert_buttons_valid(app)
    await click(app, "Ir al inicio")
    assert app.last_text(OWNER2_ID).startswith(HOME)
    await start(app)
    assert app.last_text(OWNER2_ID).startswith(HOME)  # never again on its own


async def test_every_choice_is_saved_and_then_ticked(app: App) -> None:
    await new_clone(app)
    await start(app)
    # 1. (join_open, join_approval): «No» leaves the approval as it was.
    for index, expected in ((1, (True, False)), (2, (False, False)), (0, (True, True)), (2, (False, True))):
        await answer(app, 1, index)
        rec = await get_bot(app, CLONE_ID)
        assert (rec.join_open, rec.join_approval) == expected, index
        assert app.last_text(OWNER2_ID).startswith(STEP_2 if expected[0] else STEP_ROT)
        assert len(await ticked(app, 1)) == 1
    labels_1 = ["✅ Sí, con mi aprobación", "✅ Sí, entran solos", "✅ No, solo los míos"]
    await answer(app, 1, 1)
    assert await ticked(app, 1) == [labels_1[1]]
    # 2. (partners_can_pause, pause_max_hours): «No pueden pausar» keeps the longest pause for later.
    labels_2 = ["✅ Hasta 1 día", "✅ Hasta 3 días", "✅ Hasta 7 días", "✅ Sin límite",
                "✅ No pueden pausar"]
    for index, expected in enumerate(((True, 24), (True, 72), (True, 168), (True, 0), (False, 0))):
        await answer(app, 2, index)
        rec = await get_bot(app, CLONE_ID)
        assert (rec.partners_can_pause, rec.pause_max_hours) == expected, index
        assert app.last_text(OWNER2_ID).startswith(STEP_ROT)
        assert await ticked(app, 2) == [labels_2[index]]
    # 3. The rotation: without it the hours are not asked.
    for index, (order, after) in enumerate((("seq", STEP_HOURS), ("random", STEP_HOURS), ("off", STEP_DELETE))):
        await answer(app, 3, index)
        assert (await get_bot(app, CLONE_ID)).rotation == order, index
        assert app.last_text(OWNER2_ID).startswith(after), index
        assert await ticked(app, 3) == [f"✅ {ROT_LABELS[index]}"]
    await answer(app, 3, 0)
    # 4. The hours of the rotation: each quick option, with its next slot refreshed and its hours ticked.
    expected_freqs = [
        ({"mode": "times", "times": "12:00", "days": ALL_DAYS}, (12,)),
        ({"mode": "times", "times": "10:00,20:00", "days": ALL_DAYS}, (10, 20)),
        ({"mode": "times", "times": "09:00,14:00,20:00", "days": ALL_DAYS}, (9, 14, 20)),
        ({"mode": "times", "times": "09:00,13:00,17:00,21:00", "days": ALL_DAYS}, (9, 13, 17, 21)),
        ({"mode": "interval", "every": 120, "window": "08:00-22:00", "days": ALL_DAYS}, tuple(range(8, 23, 2))),
        ({"mode": "interval", "every": 60, "window": "08:00-22:00", "days": ALL_DAYS}, tuple(range(8, 23))),
    ]
    for index, (expected_freq, hours) in enumerate(expected_freqs):
        async with edit_bot(app, CLONE_ID) as rec:
            rec.rot_next_at = None
        before = utcnow()
        await tap(app, "p", index)
        after = utcnow()
        rec = await get_bot(app, CLONE_ID)
        assert rec.freq == expected_freq, index
        assert_next_slot(rec.rot_next_at, expected_freq, before, after)
        assert button_rows(app, OWNER2_ID) == hours_rows(index, hours), index
        assert app.last_text(OWNER2_ID).startswith(STEP_HOURS)
    assert app.last_text(OWNER2_ID) == hours_text(15, ", ".join(f"{h:02d}:00" for h in range(8, 22)) + " y 22:00")
    # The days: a preset keeps the hours, and a quick option keeps the days.
    for index, days, text in ((1, "01234", "de lunes a viernes"), (2, "56", "fines de semana"), (0, ALL_DAYS, None)):
        await tap(app, "d", index)
        rec = await get_bot(app, CLONE_ID)
        assert rec.freq == {**expected_freqs[-1][0], "days": days}, index
        assert button_rows(app, OWNER2_ID) == hours_rows(5, tuple(range(8, 23)), index)
        if text:
            assert f"📅 Días: {text}\n" in app.last_text(OWNER2_ID)
    await tap(app, "d", 1)
    await tap(app, "p", 1)
    assert (await get_bot(app, CLONE_ID)).freq == {"mode": "times", "times": "10:00,20:00", "days": "01234"}
    assert button_rows(app, OWNER2_ID) == hours_rows(1, (10, 20), 1)
    # 5. How long new posts stay published: the other defaults of new posts stay.
    async with edit_bot(app, CLONE_ID) as rec:
        rec.post_defaults = {"pin": True, "silent": True}
    labels_4 = ["✅ 1 h", "✅ 6 h", "✅ 12 h", "✅ 1 día", "✅ 2 días", "✅ No se borran"]
    for index, minutes in enumerate(DELETE_OPTIONS):
        await answer(app, 5, index)
        rec = await get_bot(app, CLONE_ID)
        assert rec.post_defaults == {"pin": True, "silent": True, "delete_after": minutes}, index
        assert app.last_text(OWNER2_ID).startswith(DONE)
        assert await ticked(app, 5) == [labels_4[index]]
    assert DELETE_OPTIONS == (60, 360, 720, 1440, 2880, 0)


async def test_skip_keeps_the_defaults(app: App) -> None:
    await new_clone(app)
    await start(app)
    await click(app, "Saltar el asistente")
    rec = await get_bot(app, CLONE_ID)
    assert rec.setup_done
    assert (rec.join_open, rec.join_approval, rec.partners_can_pause, rec.pause_max_hours) == (
        False, True, True, DEFAULT_PAUSE_MAX_HOURS)
    assert rec.freq == DEFAULT_FREQ and rec.post_defaults == {} and rec.rotation == "seq"
    assert app.last_text(OWNER2_ID).startswith(HOME)
    await start(app)
    assert app.last_text(OWNER2_ID).startswith(HOME)


async def test_back_goes_to_the_previous_step_with_the_answers_given(app: App) -> None:
    await new_clone(app)
    await start(app)
    await click(app, "Sí, entran solos")
    await click(app, "Sin límite")
    await click(app, "Sí, al azar")
    await click(app, "Cada 2 h")
    assert app.last_text(OWNER2_ID).startswith(STEP_HOURS)  # the hours stay on screen until «Continuar»
    await click(app, "Continuar")
    assert app.last_text(OWNER2_ID).startswith(STEP_DELETE)
    await click(app, "Regresar")
    assert app.last_text(OWNER2_ID).startswith(STEP_HOURS) and has_button(app, OWNER2_ID, "✅ Cada 2 h")
    await click(app, "Regresar")
    assert app.last_text(OWNER2_ID).startswith(STEP_ROT) and has_button(app, OWNER2_ID, "✅ Sí, al azar")
    await click(app, "Regresar")
    assert app.last_text(OWNER2_ID).startswith(STEP_2) and has_button(app, OWNER2_ID, "✅ Sin límite")
    await click(app, "Regresar")
    assert STEP_1 in app.last_text(OWNER2_ID) and has_button(app, OWNER2_ID, "✅ Sí, entran solos")
    assert not has_button(app, OWNER2_ID, "Regresar")  # the first step can only be skipped
    rec = await get_bot(app, CLONE_ID)
    assert (rec.join_open, rec.join_approval, rec.pause_max_hours, rec.freq["every"]) == (True, False, 0, 120)
    assert not rec.setup_done
    # From the summary, back to the last question.
    await app.press(OWNER2_ID, MenuCB(screen="setup", arg=6).pack(), bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID).startswith(DONE)
    await click(app, "Regresar")
    assert app.last_text(OWNER2_ID).startswith(STEP_DELETE)


async def test_the_partners_step_is_skipped_when_external_chats_are_refused(app: App) -> None:
    await new_clone(app)
    await start(app)
    await click(app, "No, solo los míos")
    assert app.last_text(OWNER2_ID).startswith(STEP_ROT)
    assert callback_of(app, OWNER2_ID, "Regresar") == MenuCB(screen="setup", arg=1).pack()
    await app.press(OWNER2_ID, MenuCB(screen="setup", arg=2).pack(), bot_id=CLONE_ID)  # an old button of step 2
    assert app.last_text(OWNER2_ID).startswith(STEP_ROT)
    await click(app, "Sí, en orden")
    await click(app, "Cada 2 h")
    await click(app, "Continuar")
    await click(app, "1 día")
    text = app.last_text(OWNER2_ID)
    assert text.startswith(DONE)
    assert ("🤝 Canales externos: ✖️ no admitidos (red privada)\n🔁 Rotación: sí, en orden\n"
            "⏰ Frecuencia global: cada 2 h · 08:00-22:00\n") in text
    assert "Pausas de los socios" not in text and "🗑 Borrado automático: al cabo de 1 día" in text
    rec = await get_bot(app, CLONE_ID)
    assert not rec.join_open and rec.partners_can_pause and rec.post_defaults == {"delete_after": 1440}


async def test_without_rotation_the_hours_are_not_asked(app: App) -> None:
    await new_clone(app)
    await start(app)
    await click(app, "No, solo los míos")
    assert app.last_text(OWNER2_ID) == ROT_TEXT
    assert button_rows(app, OWNER2_ID) == rot_rows(0)
    await click(app, "No, cada mensaje con su horario")
    rec = await get_bot(app, CLONE_ID)
    assert rec.rotation == "off" and rec.freq == DEFAULT_FREQ
    # Straight to how long posts stay published; back goes to the rotation.
    assert app.last_text(OWNER2_ID).startswith(STEP_DELETE)
    assert callback_of(app, OWNER2_ID, "Regresar") == MenuCB(screen="setup", arg=3).pack()
    await app.press(OWNER2_ID, MenuCB(screen="setup", arg=4).pack(), bot_id=CLONE_ID)  # an old button of the hours
    assert app.last_text(OWNER2_ID).startswith(STEP_DELETE)
    await click(app, "1 día")
    text = app.last_text(OWNER2_ID)
    assert ("🤝 Canales externos: ✖️ no admitidos (red privada)\n🔁 Rotación: no, cada mensaje con su horario\n"
            "🗑 Borrado automático: al cabo de 1 día\n") in text
    assert "Frecuencia global" not in text
    assert callback_of(app, OWNER2_ID, "Regresar") == MenuCB(screen="setup", arg=5).pack()
    await click(app, "Regresar")
    await click(app, "Regresar")
    assert app.last_text(OWNER2_ID) == ROT_TEXT and button_rows(app, OWNER2_ID) == rot_rows(2)
    # With rotation again, the hours come back.
    await click(app, "Sí, al azar")
    assert app.last_text(OWNER2_ID).startswith(STEP_HOURS)
    assert (await get_bot(app, CLONE_ID)).rotation == "random"


async def test_forged_answers_change_nothing(app: App) -> None:
    await new_clone(app)
    await start(app)
    for step, index in ((1, 3), (1, -1), (2, 5), (3, 3), (3, -1), (4, 0), (5, 6), (6, 0), (9, 0), (-1, 0)):
        await answer(app, step, index)
        assert app.last_text(OWNER2_ID).startswith(INTRO), (step, index)  # back to the first question
    rec = await get_bot(app, CLONE_ID)
    assert (rec.join_open, rec.partners_can_pause, rec.rotation, rec.freq, rec.post_defaults, rec.setup_done) == (
        False, True, "seq", DEFAULT_FREQ, {}, False)
    await app.press(OWNER2_ID, MenuCB(screen="setup", arg=0).pack(), bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID).startswith(INTRO)


# ------------------------------------------------------------------------------------------ step 4: the hours
async def open_hours(app: App, f: dict | None = None) -> None:
    await new_clone(app)
    if f is not None:
        async with edit_bot(app, CLONE_ID) as rec:
            rec.freq = f
    await start(app)
    await app.press(OWNER2_ID, MenuCB(screen="setup", arg=4).pack(), bot_id=CLONE_ID)


async def test_touching_the_hours(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    woken: list[bool] = []
    monkeypatch.setattr(app.scheduler, "wake", lambda: woken.append(True))
    await open_hours(app, {"mode": "interval", "every": 240, "window": "08:00-20:00", "days": "01234"})
    assert button_rows(app, OWNER2_ID) == hours_rows(None, (8, 12, 16, 20), 1)
    # An interval becomes those times with one more (or one less); the days stay.
    before = utcnow()
    await tap(app, "h", 22)
    after = utcnow()
    rec = await get_bot(app, CLONE_ID)
    assert rec.freq == {"mode": "times", "times": "08:00,12:00,16:00,20:00,22:00", "days": "01234"}
    assert_next_slot(rec.rot_next_at, rec.freq, before, after)
    assert woken == [True]
    assert app.last_text(OWNER2_ID) == hours_text(5, "08:00, 12:00, 16:00, 20:00 y 22:00", "de lunes a viernes")
    await tap(app, "h", 8)
    assert (await get_bot(app, CLONE_ID)).freq["times"] == "12:00,16:00,20:00,22:00"
    # An hour with minutes is ticked too, and touching it removes all its times.
    async with edit_bot(app, CLONE_ID) as rec:
        rec.freq = {"mode": "times", "times": "09:00,09:30,21:15", "days": ALL_DAYS}
    await app.press(OWNER2_ID, MenuCB(screen="setup", arg=4).pack(), bot_id=CLONE_ID)
    assert button_rows(app, OWNER2_ID) == hours_rows(None, (9, 21))
    assert "🕐 <b>3 al día</b>: 09:00, 09:30 y 21:15\n" in app.last_text(OWNER2_ID)
    await tap(app, "h", 9)
    assert (await get_bot(app, CLONE_ID)).freq["times"] == "21:15"
    # The last hour can't be removed.
    await tap(app, "h", 21)
    answer_ = last_answer(app)
    assert answer_["text"] == "⚠️ Deja al menos una hora marcada." and str(answer_["show_alert"]).lower() == "true"
    assert (await get_bot(app, CLONE_ID)).freq["times"] == "21:15"


async def test_long_intervals_and_too_many_times(app: App) -> None:
    await open_hours(app, {"mode": "interval", "every": 30, "window": "", "days": ALL_DAYS})
    # 48 a day: described instead of listed; every hour is ticked, and touching one keeps the o'clock times.
    assert app.last_text(OWNER2_ID) == hours_text(48, "cada 30 min")
    assert button_rows(app, OWNER2_ID) == hours_rows(None, tuple(range(24)))
    await tap(app, "h", 3)
    rec = await get_bot(app, CLONE_ID)
    assert rec.freq["times"] == ",".join(f"{h:02d}:00" for h in range(24) if h != 3)
    # 24 times at most.
    full = [f"{h:02d}:00" for h in range(23)] + ["22:30"]
    async with edit_bot(app, CLONE_ID) as rec:
        rec.freq = {"mode": "times", "times": ",".join(full), "days": ALL_DAYS}
    await tap(app, "h", 23)
    assert last_answer(app)["text"] == "⚠️ Como máximo 24 horas distintas."
    assert (await get_bot(app, CLONE_ID)).freq["times"] == ",".join(full)


async def test_typing_the_times(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    woken: list[bool] = []
    monkeypatch.setattr(app.scheduler, "wake", lambda: woken.append(True))
    await open_hours(app, {"mode": "interval", "every": 120, "window": "08:00-22:00", "days": "56"})
    await click(app, "Escribir otras horas")
    prompt_text = ("✏️ <b>Escribe las horas</b>\n\nSeparadas por comas, hasta 24 y con los minutos que quieras. Por "
                   "ejemplo: <code>9:30, 14, 21:15</code>.\n\n🕐 Ahora: <b>08:00, 10:00, 12:00, 14:00, 16:00, 18:00, "
                   "20:00 y 22:00</b>")
    assert app.last_text(OWNER2_ID) == prompt_text
    assert button_texts(app, OWNER2_ID) == ["❌ Cancelar"]
    await app.send(OWNER2_ID, "a las tantas", bot_id=CLONE_ID)  # not understood: asked again
    assert app.last_text(OWNER2_ID) == (
        f"⚠️ No se entiende la hora. Escríbelas así: <code>10:00, 14:30, 22:00</code>.\n\n{prompt_text}")
    assert (await get_bot(app, CLONE_ID)).freq["mode"] == "interval" and not woken
    before = utcnow()
    await app.send(OWNER2_ID, "9:30, 14 y 21:15", bot_id=CLONE_ID)
    after = utcnow()
    rec = await get_bot(app, CLONE_ID)
    assert rec.freq == {"mode": "times", "times": "09:30,14:00,21:15", "days": "56"}  # the days stay
    assert_next_slot(rec.rot_next_at, rec.freq, before, after)
    assert woken == [True]
    assert app.last_text(OWNER2_ID) == (
        "✅ Guardado: a las 09:30, 14:00 y 21:15 · fines de semana\n\n"
        + hours_text(3, "09:30, 14:00 y 21:15", "fines de semana"))
    assert button_rows(app, OWNER2_ID) == hours_rows(None, (9, 14, 21), 2)
    # Cancel goes back to the step as it was.
    await click(app, "Escribir otras horas")
    await click(app, "Cancelar")
    assert app.last_text(OWNER2_ID) == hours_text(3, "09:30, 14:00 y 21:15", "fines de semana")
    await app.send(OWNER2_ID, "10:00", bot_id=CLONE_ID)  # no longer waiting for the times
    assert (await get_bot(app, CLONE_ID)).freq["times"] == "09:30,14:00,21:15"


async def test_forged_buttons_of_the_hours_change_nothing(app: App) -> None:
    await open_hours(app)
    for action, v in (("h", 24), ("h", -1), ("p", 6), ("p", -1), ("d", 3), ("d", -1), ("x", 0)):
        await tap(app, action, v)
        assert app.last_text(OWNER2_ID) == hours_text(1, "12:00"), (action, v)
    rec = await get_bot(app, CLONE_ID)
    assert rec.freq == DEFAULT_FREQ and not rec.setup_done


# ------------------------------------------------------------------------------------------ run again
async def test_running_it_again_from_the_settings_keeps_custom_values(app: App) -> None:
    await add_clone(app)  # its owner went through the wizard already
    async with edit_bot(app, CLONE_ID) as rec:
        rec.join_open = True
        rec.join_approval = False
        rec.partners_can_pause = False
        rec.rotation = "random"
        rec.freq = dict(CUSTOM_FREQ)  # made in ⏰ Frecuencias
        rec.post_defaults = {"delete_after": 180, "pin": True}  # made in ⚙️ Opciones por defecto
    await add_post(app, bot_id=CLONE_ID)
    await start(app)
    assert app.last_text(OWNER2_ID).startswith(HOME)
    await click(app, "Ajustes")
    await click(app, "Asistente de configuración")
    assert app.last_text(OWNER2_ID).startswith(f"{INTRO}\n\n{STEP_1}")
    assert has_button(app, OWNER2_ID, "✅ Sí, entran solos")
    await click(app, "Sí, entran solos")
    assert has_button(app, OWNER2_ID, "✅ No pueden pausar")
    await click(app, "No pueden pausar")
    assert button_rows(app, OWNER2_ID) == rot_rows(1)  # chosen in ⏰ Frecuencias
    await click(app, "Sí, al azar")
    # A frequency made elsewhere is shown with its hours ticked and kept with «Continuar».
    assert app.last_text(OWNER2_ID) == hours_text(6, "08:00, 11:00, 14:00, 17:00, 20:00 y 23:00",
                                                   "de lunes a viernes")
    assert button_rows(app, OWNER2_ID) == hours_rows(None, (8, 11, 14, 17, 20, 23), 1)
    await click(app, "Continuar")
    assert app.last_text(OWNER2_ID).startswith(STEP_DELETE)
    assert button_rows(app, OWNER2_ID)[0] == ["✅ Mantener: 3 h"]
    assert_buttons_valid(app)
    await click(app, "Mantener")
    text = app.last_text(OWNER2_ID)
    assert text.startswith(DONE)
    assert ("🤝 Canales externos: ✅ admitidos (entran solos)\n⏸ Pausas de los socios: no pueden pausar\n"
            "🔁 Rotación: sí, al azar\n⏰ Frecuencia global: cada 3 h · 08:00-23:00 · de lunes a viernes\n"
            "🗑 Borrado automático: al cabo de 3 h\n") in text
    assert has_button(app, OWNER2_ID, "📝 Crear un mensaje")  # the network has posts already
    rec = await get_bot(app, CLONE_ID)
    assert rec.freq == CUSTOM_FREQ and rec.post_defaults == {"delete_after": 180, "pin": True}
    assert (rec.join_open, rec.join_approval, rec.partners_can_pause) == (True, False, False)
    # Skipping a run again goes home and changes nothing.
    await app.press(OWNER2_ID, MenuCB(screen="setup", arg=1).pack(), bot_id=CLONE_ID)
    await click(app, "Saltar el asistente")
    assert app.last_text(OWNER2_ID).startswith(HOME)
    assert (await get_bot(app, CLONE_ID)).freq == CUSTOM_FREQ


async def test_a_longest_pause_set_elsewhere_can_be_kept(app: App) -> None:
    await add_clone(app)
    async with edit_bot(app, CLONE_ID) as rec:
        rec.join_open = True
        rec.pause_max_hours = 12
    await app.press(OWNER2_ID, MenuCB(screen="setup", arg=2).pack(), bot_id=CLONE_ID)
    assert button_rows(app, OWNER2_ID)[0] == ["✅ Mantener: hasta 12 h"]
    assert len([t for t in button_texts(app, OWNER2_ID) if t.startswith("✅")]) == 1
    await click(app, "Mantener")
    assert app.last_text(OWNER2_ID).startswith(STEP_ROT)
    assert (await get_bot(app, CLONE_ID)).pause_max_hours == 12


async def test_the_main_bot_owner_can_run_it_from_the_settings(app: App) -> None:
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Ajustes")
    await app.click(SUPER_ID, "Asistente de configuración")
    assert STEP_1 in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Sí, con mi aprobación")
    assert (await get_bot(app)).join_open
    await app.click(SUPER_ID, "Hasta 7 días")
    await app.click(SUPER_ID, "Sí, en orden")
    await app.click(SUPER_ID, "4 al día")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "No se borran")
    rec = await get_bot(app)
    assert (rec.pause_max_hours, rec.freq["times"], rec.post_defaults) == (
        168, "09:00,13:00,17:00,21:00", {"delete_after": 0})
    assert "🗑 Borrado automático: no se borran" in app.last_text(SUPER_ID)
    assert url_of(app, SUPER_ID, "Añadir canal") == add_to_channel_url("emesh_test_bot")


# ------------------------------------------------------------------------------------------ who gets it
async def test_only_the_owner_gets_and_runs_the_wizard(app: App) -> None:
    await new_clone(app)
    await make_admin(app, USER_ID, CLONE_ID)
    await start(app, USER_ID)
    assert app.last_text(USER_ID).startswith(HOME)  # admins never get it
    await click(app, "Ajustes", USER_ID)
    assert not has_button(app, USER_ID, "Asistente")
    await app.send(444, "/start", bot_id=CLONE_ID)  # a visitor
    assert "Esta red es privada" in app.last_text(444)
    for user_id in (USER_ID, 444):
        for data in (MenuCB(screen="setup", arg=1).pack(), MenuCB(screen="setup", arg=6).pack(),
                     SuCB(s=1, v=0).pack(), SuCB(s=3, v=2).pack(), SuCB(s=0).pack(),
                     SuFqCB(a="p", v=4).pack(), SuFqCB(a="h", v=9).pack(), SuFqCB(a="d", v=1).pack(),
                     SuFqCB(a="w").pack()):
            await app.press(user_id, data, bot_id=CLONE_ID)
            assert denied(app), (user_id, data)
    rec = await get_bot(app, CLONE_ID)
    assert (rec.join_open, rec.rotation, rec.freq, rec.setup_done) == (False, "seq", DEFAULT_FREQ, False)
    # A super admin in the clone itself has owner rights: no wizard by itself, but they may run it.
    await start(app, SUPER_ID)
    assert app.last_text(SUPER_ID).startswith(HOME)
    await click(app, "Ajustes", SUPER_ID)
    assert has_button(app, SUPER_ID, "Asistente de configuración")
    # Its owner still gets it.
    await start(app)
    assert app.last_text(OWNER2_ID).startswith(INTRO)


async def test_not_shown_to_a_super_admin_managing_a_clone_nor_in_main_bots(app: App) -> None:
    await new_clone(app)
    await manage(app, SUPER_ID, CLONE_ID)
    await app.send(SUPER_ID, "/start")
    text = app.last_text(SUPER_ID)
    assert "Gestionando" in text and HOME in text and "Asistente" not in text
    await app.click(SUPER_ID, "Ajustes")
    assert has_button(app, SUPER_ID, "Canales externos") and not has_button(app, SUPER_ID, "Asistente")
    for data in (MenuCB(screen="setup", arg=1).pack(), SuCB(s=1, v=0).pack(), SuCB(s=0).pack(),
                 SuFqCB(a="h", v=9).pack()):
        await app.press(SUPER_ID, data)
        assert denied(app), data
    rec = await get_bot(app, CLONE_ID)
    assert not rec.join_open and not rec.setup_done and rec.freq == DEFAULT_FREQ  # still waiting for its owner
    # Main bots never open it by themselves (they are marked done at startup).
    async with app.db() as s:
        bu = await s.get(BotUser, (MAIN_BOT_ID, SUPER_ID))
        assert bu is not None
        bu.ws_bot_id = None
    async with edit_bot(app) as main:
        main.setup_done = False
    await app.send(SUPER_ID, "/start")
    assert app.last_text(SUPER_ID).startswith(HOME)
    await start(app)
    assert app.last_text(OWNER2_ID).startswith(INTRO)


async def test_hub_mode_has_no_wizard(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.settings, "MAIN_BOT_MODE", "hub")
    await app.send(SUPER_ID, "/start")
    await app.press(SUPER_ID, MenuCB(screen="setup", arg=1).pack())
    assert app.last_text(SUPER_ID).startswith("🕸 <b>eMesh · Tu propia red de distribución</b>")
    await app.press(SUPER_ID, SuCB(s=1, v=0).pack())
    assert denied(app) and not (await get_bot(app)).join_open


async def test_the_wizard_in_english(app: App) -> None:
    app.fake.users[OWNER2_ID]["language_code"] = "en"  # before the first /start: the clone speaks English
    await new_clone(app)
    await start(app)
    assert "🤝 <b>Do you accept other people's channels?</b>" in app.last_text(OWNER2_ID)
    assert button_rows(app, OWNER2_ID) == [["⚪ Yes, with my approval"],
                                           ["⚪ Yes, they join on their own"], ["✅ No, only mine"],
                                           ["⏭ Skip the wizard"]]
    await click(app, "Yes, they join")
    assert button_texts(app, OWNER2_ID) == ["⚪ Up to 1 day", "⚪ Up to 3 days", "⚪ Up to 7 days",
                                            "✅ No limit", "⚪ They can't pause", "🔙 Back"]
    await click(app, "Up to 1 day")
    assert app.last_text(OWNER2_ID).startswith("🔁 <b>Do you want the posts to take turns?</b>")
    assert button_texts(app, OWNER2_ID) == ["✅ Yes, in order", "⚪ Yes, at random", "⚪ No, each post on its own schedule",
                                            "🔙 Back"]
    await click(app, "Yes, in order")
    text = app.last_text(OWNER2_ID)
    assert text.startswith("⏰ <b>At what times does each channel get a post?</b>\nTap an hour to tick or untick it")
    assert text.endswith("🕐 <b>1 a day</b>: 12:00\n📅 Days: every day\n"
                         "   └ Europe/Madrid time. It can be fine-tuned later in ⏰ Frequencies.")
    assert button_rows(app, OWNER2_ID)[:2] == [["✅ 1 a day", "⚪ 2 a day", "⚪ 3 a day"],
                                               ["⚪ 4 a day", "⚪ Every 2 h", "⚪ Every hour"]]
    assert button_rows(app, OWNER2_ID)[6:] == [["✅ All", "⚪ Mo-Fr", "⚪ Sa-Su"], ["✏️ Type other times (9:30…)"],
                                               ["Continue ➡️"], ["🔙 Back"]]
    await click(app, "Every 2 h")
    assert "🕐 <b>8 a day</b>: 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00 and 22:00\n" in app.last_text(OWNER2_ID)
    await click(app, "Continue")
    assert button_rows(app, OWNER2_ID)[:3] == [["⚪ 1 h", "⚪ 6 h", "⚪ 12 h"], ["⚪ 1 day", "⚪ 2 days"],
                                               ["✅ Never deleted"]]
    await click(app, "Never deleted")
    text = app.last_text(OWNER2_ID)
    assert text.startswith("✅ <b>All set</b>")
    assert "⏸ Partners' pauses: up to 1 day" in text and "🗑 Auto delete: never" in text
    assert button_rows(app, OWNER2_ID)[1:] == [["📝 Create the first post"], ["🏠 Go to the home screen"], ["🔙 Back"]]


def test_callback_data_fits_telegram_limits() -> None:
    for cb in (SuCB(s=0), SuCB(s=4, v=5), SuCB(s=-1, v=-1), SuFqCB(a="h", v=23), SuFqCB(a="w")):
        assert len(cb.pack().encode()) <= 64
    assert SuCB.unpack(SuCB(s=4, v=5).pack()) == SuCB(s=4, v=5)
    assert SuFqCB.unpack(SuFqCB(a="h", v=23).pack()) == SuFqCB(a="h", v=23)
