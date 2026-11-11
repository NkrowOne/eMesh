"""⏰ freq_edit: the default schedule (every new post starts with it) and a post's own one."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.bot.routers.freqs import FqCB
from app.bot.routers.groups import GrCB
from app.db.base import utcnow
from app.db.models import DEFAULT_FREQ, Post, SchedMode
from app.db.models import Bot as BotRecord
from app.services import freq
from app.ui import fmt
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, App
from tests.test_groups_helpers import (
    NOT_FOUND,
    TZ,
    add_group,
    add_post,
    answers,
    button_data,
    button_texts,
    count_wakes,
    load,
    open_menu,
    started,
)


@pytest.fixture
def wakes(app: App, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    return count_wakes(app, monkeypatch)


EVERY_BUTTONS = ["30 min", "1 h", "2 h", "3 h", "4 h", "6 h", "8 h", "12 h", "24 h"]
DAY_BUTTONS = ["L", "M", "X", "J", "V", "S", "D", "Todos", "L-V", "S-D"]
EVERY_4H = {"mode": "interval", "every": 240, "window": "08:00-22:00", "days": "0123456"}
OWN_2H = {"mode": "interval", "every": 120, "window": "08:00-22:00", "days": "0123456"}
DEFAULT_TITLE = "🕐 <b>Horario por defecto</b>\n   └ Cada mensaje nuevo empieza con este horario.\n"


async def bot_rec(app: App, bot_id: int = MAIN_BOT_ID) -> BotRecord:
    return await load(app, BotRecord, bot_id)


async def default_every_4h(app: App, bot_id: int = MAIN_BOT_ID) -> None:
    """The editors start from an interval schedule (the default one is once a day at 12:00)."""
    async with app.db() as s:
        (await s.get(BotRecord, bot_id)).freq = EVERY_4H


def local(value, fmt_: str = "%H:%M") -> str:  # noqa: ANN001
    return fmt.to_local(value, TZ).strftime(fmt_)


async def test_default_schedule_editor_and_quick_interval(app: App, wakes: list[int]) -> None:
    await started(app, SUPER_ID)
    await default_every_4h(app)
    await open_menu(app, SUPER_ID, "freqs")
    await app.click(SUPER_ID, "Horario por defecto")
    text = app.last_text(SUPER_ID)
    assert text.startswith(DEFAULT_TITLE + "🔁 Cada: <b>4 h</b>\n🕐 Horario: 08:00-22:00\n🔄 Días: todos los días\n"
                                           "📅 Próximos: ")
    assert text.endswith("≈ <b>4</b> envíos al día por chat\n🗺 Zona horaria: Europe/Madrid")
    assert "La siguen" not in text and "rotación" not in text
    expected = ["✅ Cada cierto tiempo", "⚪ A horas fijas",
                *[("✅ " if b == "4 h" else "⚪ ") + b for b in EVERY_BUTTONS],
                "✏️ Otro intervalo", "🕐 Horario activo: 08:00-22:00",
                *[f"✅ {d}" for d in DAY_BUTTONS[:8]], "L-V", "S-D", "🔙 Regresar"]
    assert button_texts(app) == expected
    assert button_data(app, "Regresar") == MenuCB(screen="freqs").pack()

    before = utcnow()
    await app.click(SUPER_ID, "2 h")
    assert (await bot_rec(app)).freq == OWN_2H
    assert answers(app)[-1] == "✅ Guardado: cada 2 h · 08:00-22:00"
    assert wakes == []  # the default schedule sends nothing by itself: only stored
    text = app.last_text(SUPER_ID)
    assert "🔁 Cada: <b>2 h</b>" in text and "≈ <b>8</b> envíos al día por chat" in text
    assert any(f"📅 Próximos: {local(s, '%d/%m %I:%M %p')}" in text for s in freq.upcoming(OWN_2H, TZ, before, 2))
    assert "✅ 2 h" in button_texts(app)

    await app.press(SUPER_ID, FqCB(a="ev", t=0, v=7).pack())  # not a quick choice: forged
    assert (await bot_rec(app)).freq == OWN_2H
    await app.click(SUPER_ID, "Regresar")
    assert "🕐 Horario por defecto: <b>cada 2 h · 08:00-22:00</b>" in app.last_text(SUPER_ID)


async def test_custom_interval(app: App, wakes: list[int]) -> None:
    await started(app, SUPER_ID)
    await default_every_4h(app)
    await open_menu(app, SUPER_ID, "freq_edit")
    await app.click(SUPER_ID, "Otro intervalo")
    text = app.last_text(SUPER_ID)
    assert "✏️ <b>Otro intervalo</b>" in text and "🔁 Ahora: <b>4 h</b>" in text
    await app.send(SUPER_ID, "a menudo")
    assert app.last_text(SUPER_ID).startswith("⚠️ No se entiende. Escribe cada cuánto")
    await app.send(SUPER_ID, "5 min")
    assert app.last_text(SUPER_ID).startswith("⚠️ Elige entre 10 minutos y 24 horas.")
    await app.send(SUPER_ID, "25 h")
    assert app.last_text(SUPER_ID).startswith("⚠️ Elige entre 10 minutos y 24 horas.")

    await app.send(SUPER_ID, "1 h 30 min")
    assert (await bot_rec(app)).freq == {"mode": "interval", "every": 90, "window": "08:00-22:00", "days": "0123456"}
    text = app.last_text(SUPER_ID)
    assert text.startswith("✅ Guardado: cada 1 h 30 min · 08:00-22:00\n\n") and "🔁 Cada: <b>1 h 30 min</b>" in text
    assert "✅ Otro: 1 h 30 min" in button_texts(app)
    assert not any(t.startswith("✅ ") and t[2:] in EVERY_BUTTONS for t in button_texts(app))

    await app.click(SUPER_ID, "Otro: 1 h 30 min")
    await app.click(SUPER_ID, "Cancelar")
    assert "❌ Cancelado" in answers(app)
    assert app.last_text(SUPER_ID).startswith(DEFAULT_TITLE)
    await app.send(SUPER_ID, "2 h")  # the input was cancelled
    assert (await bot_rec(app)).freq["every"] == 90 and wakes == []


async def test_active_hours_of_a_post(app: App, wakes: list[int]) -> None:
    p = await add_post(app, "Promo")
    await started(app, SUPER_ID)
    await default_every_4h(app)
    await app.press(SUPER_ID, FqCB(a="win", t=-p).pack())  # a post without a schedule shows a copy of the default
    text = app.last_text(SUPER_ID)
    assert "🕐 <b>Horario activo</b>" in text and "🕐 Ahora: <b>08:00-22:00</b>" in text
    assert button_texts(app) == ["⚪ Todo el día", "✅ 08:00-22:00", "⚪ 08:00-23:00", "⚪ 09:00-22:00", "❌ Cancelar"]
    await app.send(SUPER_ID, "de 8 a 8")
    assert app.last_text(SUPER_ID).startswith("⚠️ Escribe el horario así")
    await app.send(SUPER_ID, "de 8 a 23")
    post = await load(app, Post, p)
    assert post.freq == {"mode": "interval", "every": 240, "window": "08:00-23:00", "days": "0123456"}
    assert local(post.next_send_at) in {"08:00", "12:00", "16:00", "20:00"}
    text = app.last_text(SUPER_ID)
    assert "🕐 Horario: 08:00-23:00" in text and "≈ <b>4</b> envíos al día por chat" in text
    assert "🕐 Horario activo: 08:00-23:00" in button_texts(app)

    await app.press(SUPER_ID, FqCB(a="win", t=-p).pack())
    await app.click(SUPER_ID, "09:00-22:00")
    post = await load(app, Post, p)
    assert post.freq["window"] == "09:00-22:00" and local(post.next_send_at) in {"09:00", "13:00", "17:00", "21:00"}
    await app.press(SUPER_ID, FqCB(a="win", t=-p).pack())
    await app.send(SUPER_ID, "0")
    assert (await load(app, Post, p)).freq["window"] == ""
    assert (await bot_rec(app)).freq == EVERY_4H  # the default schedule didn't change
    assert wakes == [1, 1, 1]
    await app.press(SUPER_ID, FqCB(a="wq", t=-p, v=9).pack())
    assert "⌛ Este botón ya no está activo. Pulsa /start." in answers(app)


async def test_fixed_times(app: App, wakes: list[int]) -> None:
    await started(app, SUPER_ID)
    await default_every_4h(app)
    await open_menu(app, SUPER_ID, "freq_edit")
    await app.click(SUPER_ID, "A horas fijas")  # the times are asked first
    text = app.last_text(SUPER_ID)
    assert "🕐 <b>Horas fijas</b>" in text and "🕐 Ahora: <b>—</b>" in text
    assert (await bot_rec(app)).freq == EVERY_4H
    await app.send(SUPER_ID, "25:00")
    assert app.last_text(SUPER_ID).startswith("⚠️ No se entiende la hora")
    await app.send(SUPER_ID, ", ".join(f"{h}:00" for h in range(24)) + ", 9:30")
    assert app.last_text(SUPER_ID).startswith("⚠️ Como máximo 24 horas distintas.")

    await app.send(SUPER_ID, "22 y 10:30")
    assert app.last_text(SUPER_ID).startswith("✅ Guardado: a las 10:30 y 22:00\n\n")
    assert (await bot_rec(app)).freq == {"mode": "times", "times": "10:30,22:00", "days": "0123456"}
    text = app.last_text(SUPER_ID)
    assert "🕐 A las: <b>10:30 y 22:00</b>\n🔄 Días: todos los días" in text and "≈ <b>2</b>" in text
    assert "Cada:" not in text and "Horario:" not in text
    texts = button_texts(app)
    assert texts[:3] == ["⚪ Cada cierto tiempo", "✅ A horas fijas", "✏️ Escribir las horas"]
    assert "✏️ Otro intervalo" not in texts

    await app.click(SUPER_ID, "A horas fijas")  # already: nothing asked
    assert app.last_text(SUPER_ID).startswith(DEFAULT_TITLE)
    await app.click(SUPER_ID, "Escribir las horas")
    assert "🕐 Ahora: <b>10:30 y 22:00</b>" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "9")
    assert (await bot_rec(app)).freq["times"] == "09:00"

    await app.press(SUPER_ID, FqCB(a="dp", t=0, v=1).pack())
    await app.press(SUPER_ID, FqCB(a="mode", t=0, v=0).pack())  # back to an interval: the default one
    assert (await bot_rec(app)).freq == {"mode": "interval", "every": 240, "window": "", "days": "01234"}
    assert wakes == []


async def test_days_toggles_and_presets_of_a_post(app: App, wakes: list[int]) -> None:
    p = await add_post(app, "Promo")
    await started(app, SUPER_ID)
    await default_every_4h(app)
    await open_menu(app, SUPER_ID, "freq_edit", -p)
    await app.click(SUPER_ID, "L-V")
    post = await load(app, Post, p)
    assert post.freq["days"] == "01234" and fmt.to_local(post.next_send_at, TZ).weekday() < 5
    assert "🔄 Días: de lunes a viernes" in app.last_text(SUPER_ID)
    texts = button_texts(app)
    assert {"✅ L", "✅ V", "S", "D", "Todos", "✅ L-V", "S-D"} <= set(texts)

    await app.press(SUPER_ID, FqCB(a="day", t=-p, v=5).pack())
    assert (await load(app, Post, p)).freq["days"] == "012345"
    assert answers(app)[-1] == "✅ Guardado: cada 4 h · 08:00-22:00 · L, M, X, J, V, S"
    assert "🔄 Días: L, M, X, J, V, S" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "S-D")
    post = await load(app, Post, p)
    assert post.freq["days"] == "56" and fmt.to_local(post.next_send_at, TZ).weekday() >= 5
    await app.press(SUPER_ID, FqCB(a="day", t=-p, v=5).pack())
    await app.press(SUPER_ID, FqCB(a="day", t=-p, v=6).pack())  # the last one can't be removed
    assert "⚠️ Elige al menos un día." in answers(app)
    post = await load(app, Post, p)
    assert post.freq["days"] == "6" and fmt.to_local(post.next_send_at, TZ).weekday() == 6
    await app.click(SUPER_ID, "Todos")
    assert (await load(app, Post, p)).freq["days"] == "0123456"
    assert wakes == [1] * 5
    await app.press(SUPER_ID, FqCB(a="day", t=-p, v=7).pack())
    await app.press(SUPER_ID, FqCB(a="dp", t=-p, v=3).pack())
    assert (await load(app, Post, p)).freq["days"] == "0123456" and wakes == [1] * 5


async def test_groups_of_chats_have_no_schedule_editor(app: App, wakes: list[int]) -> None:
    g = await add_group(app, "Cine")
    await started(app, SUPER_ID)
    await default_every_4h(app)
    await open_menu(app, SUPER_ID, "freq_edit", g)  # an old button of a group of chats
    assert answers(app)[-1] == NOT_FOUND
    assert app.last_text(SUPER_ID).startswith("⏰ <b>Horarios</b>")
    await app.press(SUPER_ID, FqCB(a="ev", t=g, v=60).pack())
    await app.press(SUPER_ID, FqCB(a="evx", t=g).pack())
    assert answers(app)[-2:] == [NOT_FOUND] * 2
    await app.press(SUPER_ID, FqCB(a="glob", t=g).pack())  # "use the global one" is gone
    assert answers(app)[-1] == "⌛ Este botón ya no está activo. Pulsa /start."
    await open_menu(app, SUPER_ID, "freq_edit_dash", g)
    assert (await bot_rec(app)).freq == EVERY_4H and wakes == []


async def test_post_schedule_starts_from_a_copy_of_the_default_one(app: App, wakes: list[int]) -> None:
    default = {"mode": "interval", "every": 180, "window": "08:00-23:00", "days": "0123456"}
    async with app.db() as s:
        (await s.get(BotRecord, MAIN_BOT_ID)).freq = default
    p = await add_post(app, "Promo <Cine>")
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "freq_edit", -p)
    text = app.last_text(SUPER_ID)
    assert text.startswith("⏰ <b>Horario</b> · 📝 Promo &lt;Cine&gt;\n"
                           "📝 A cada hora de su horario se envía a todo su destino.\n🔁 Cada: <b>3 h</b>\n🕐 Horario: 08:00-23:00")
    assert "Horario por defecto" not in text and "no se envía con su propio horario" not in text
    assert button_data(app, "Regresar") == MenuCB(screen="post_sched", arg=p).pack()
    assert (await load(app, Post, p)).freq is None  # nothing is stored just by looking

    before = utcnow()
    await app.click(SUPER_ID, "1 h")
    post = await load(app, Post, p)
    assert post.freq == {"mode": "interval", "every": 60, "window": "08:00-23:00", "days": "0123456"}
    assert post.next_send_at in freq.upcoming(post.freq, TZ, before, 2)
    assert (await bot_rec(app)).freq == default and wakes == [1]

    manual = await add_post(app, "A mano", mode=SchedMode.MANUAL)
    await open_menu(app, SUPER_ID, "freq_edit", -manual)
    assert "ℹ️ Ahora este mensaje no se envía con su propio horario" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "2 h")
    post = await load(app, Post, manual)
    assert post.freq["every"] == 120 and post.next_send_at is None  # only own-schedule posts get a next send


async def test_post_campaign_dates_limit_the_next_sends(app: App) -> None:
    p = await add_post(app, "Campaña")
    start = fmt.to_local(utcnow(), TZ).date() + timedelta(days=3)
    async with app.db() as s:
        post = await s.get(Post, p)
        post.starts_on, post.ends_on = start, start
    await started(app, SUPER_ID)
    await default_every_4h(app)
    await app.press(SUPER_ID, FqCB(a="ev", t=-p, v=720).pack())
    post = await load(app, Post, p)
    assert fmt.to_local(post.next_send_at, TZ).date() == start
    text = app.last_text(SUPER_ID)
    first = fmt.to_local(post.next_send_at, TZ)
    assert f"📅 Próximos: {first:%d/%m} 08:00 AM, 08:00 PM\n" in text  # two slots that day, then the campaign ends


async def test_rows_of_another_network_are_not_found(app: App, wakes: list[int]) -> None:
    clone = 7_000_000_301
    await app.add_clone(clone, "clon_series_bot", OWNER2_ID)
    clone_post = await add_post(app, "Del clon", bot_id=clone)
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, FqCB(a="ev", t=-clone_post, v=60).pack())
    await open_menu(app, SUPER_ID, "freq_edit", -clone_post)
    await app.press(SUPER_ID, FqCB(a="ev", t=999_999, v=60).pack())
    assert answers(app) == [NOT_FOUND] * 3
    assert (await load(app, Post, clone_post)).freq is None
    assert (await bot_rec(app)).freq == DEFAULT_FREQ and (await bot_rec(app, clone)).freq == DEFAULT_FREQ
    assert wakes == []
    assert "⏰ <b>Horarios</b>" in app.last_text(SUPER_ID)


async def test_post_deleted_while_typing_its_interval(app: App, wakes: list[int]) -> None:
    p = await add_post(app, "Promo", freq=OWN_2H)
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, FqCB(a="evx", t=-p).pack())
    async with app.db() as s:  # e.g. another admin deletes it meanwhile
        await s.delete(await s.get(Post, p))
    await app.send(SUPER_ID, "3 h")
    sent = [c.params.get("text") for c in app.fake.calls_of("sendMessage", chat_id=SUPER_ID)]
    assert NOT_FOUND in sent
    assert wakes == []
    await app.send(SUPER_ID, "2 h")  # the input is over
    assert (await bot_rec(app)).freq == DEFAULT_FREQ


async def test_delete_from_a_group_button_ends_a_pending_input(app: App) -> None:
    g = await add_group(app, "Cine")
    p = await add_post(app, "Promo", freq=OWN_2H)
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, FqCB(a="evx", t=-p).pack())
    await app.press(SUPER_ID, GrCB(a="del_ok", id=g).pack())
    await app.send(SUPER_ID, "3 h")
    assert (await load(app, Post, p)).freq == OWN_2H
