"""⏰ freq_edit: the global frequency, a group of chats' own one and a post's own one."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.bot.routers.freqs import FqCB
from app.bot.routers.groups import GrCB
from app.db.base import utcnow
from app.db.models import DEFAULT_FREQ, ChatGroup, Post, SchedMode
from app.db.models import Bot as BotRecord
from app.services import freq
from app.ui import fmt
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, App
from tests.test_groups_helpers import (
    NOT_FOUND,
    TZ,
    add_chat,
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


async def bot_rec(app: App, bot_id: int = MAIN_BOT_ID) -> BotRecord:
    return await load(app, BotRecord, bot_id)


async def global_every_4h(app: App, bot_id: int = MAIN_BOT_ID) -> None:
    """The editors start from an interval frequency (the default one is once a day at 12:00)."""
    async with app.db() as s:
        (await s.get(BotRecord, bot_id)).freq = EVERY_4H


def local(value, fmt_: str = "%H:%M") -> str:  # noqa: ANN001
    return fmt.to_local(value, TZ).strftime(fmt_)


async def test_global_frequency_editor_and_quick_interval(app: App, wakes: list[int]) -> None:
    await add_chat(app, -1001, "Cine HD")
    await started(app, SUPER_ID)
    await global_every_4h(app)
    await open_menu(app, SUPER_ID, "freqs")
    await app.click(SUPER_ID, "🌐 Global")
    text = app.last_text(SUPER_ID)
    assert text.startswith("⏰ <b>Frecuencia</b> · 🌐 Global\n📣 La siguen: <b>1 chat</b>\n")
    assert "└ Los chats que reciben mensajes y no están en ningún grupo de canales" in text
    assert "🔁 Cada: <b>4 h</b>\n🕐 Horario: 08:00-22:00\n🔄 Días: todos los días\n📅 Próximos: " in text
    assert "≈ <b>4</b> envíos al día por chat\n🗺 Zona horaria: Europe/Madrid" in text
    expected = ["✅ Cada cierto tiempo", "⚪ A horas fijas",
                *[("✅ " if b == "4 h" else "⚪ ") + b for b in EVERY_BUTTONS],
                "✏️ Otro intervalo", "🕐 Horario activo: 08:00-22:00",
                *[f"✅ {d}" for d in DAY_BUTTONS[:8]], "L-V", "S-D", "🔙 Regresar"]
    assert button_texts(app) == expected
    assert button_data(app, "Regresar") == MenuCB(screen="freqs").pack()

    before = utcnow()
    await app.click(SUPER_ID, "2 h")
    rec = await bot_rec(app)
    assert rec.freq == OWN_2H
    assert rec.rot_next_at in freq.upcoming(rec.freq, TZ, before, 2)
    assert wakes == [1] and answers(app)[-1] == "✅ Guardado: cada 2 h · 08:00-22:00"
    text = app.last_text(SUPER_ID)
    assert "🔁 Cada: <b>2 h</b>" in text and "≈ <b>8</b> envíos al día por chat" in text
    assert f"📅 Próximos: {local(rec.rot_next_at, '%d/%m %I:%M %p')}" in text
    assert "✅ 2 h" in button_texts(app)

    await app.press(SUPER_ID, FqCB(a="ev", t=0, v=7).pack())  # not a quick choice: forged
    assert (await bot_rec(app)).freq == OWN_2H and wakes == [1]


async def test_custom_interval(app: App, wakes: list[int]) -> None:
    await started(app, SUPER_ID)
    await global_every_4h(app)
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
    assert wakes == []

    before = utcnow()
    await app.send(SUPER_ID, "1 h 30 min")
    rec = await bot_rec(app)
    assert rec.freq == {"mode": "interval", "every": 90, "window": "08:00-22:00", "days": "0123456"}
    assert rec.rot_next_at in freq.upcoming(rec.freq, TZ, before, 2) and wakes == [1]
    text = app.last_text(SUPER_ID)
    assert text.startswith("✅ Guardado: cada 1 h 30 min · 08:00-22:00\n\n") and "🔁 Cada: <b>1 h 30 min</b>" in text
    assert "✅ Otro: 1 h 30 min" in button_texts(app)
    assert not any(t.startswith("✅ ") and t[2:] in EVERY_BUTTONS for t in button_texts(app))

    await app.click(SUPER_ID, "Otro: 1 h 30 min")
    await app.click(SUPER_ID, "Cancelar")
    assert "❌ Cancelado" in answers(app)
    assert app.last_text(SUPER_ID).startswith("⏰ <b>Frecuencia</b> · 🌐 Global")
    await app.send(SUPER_ID, "2 h")  # the input was cancelled
    assert (await bot_rec(app)).freq["every"] == 90


async def test_active_hours(app: App, wakes: list[int]) -> None:
    await started(app, SUPER_ID)
    await global_every_4h(app)
    await app.press(SUPER_ID, FqCB(a="win", t=0).pack())
    text = app.last_text(SUPER_ID)
    assert "🕐 <b>Horario activo</b>" in text and "🕐 Ahora: <b>08:00-22:00</b>" in text
    assert button_texts(app) == ["⚪ Todo el día", "✅ 08:00-22:00", "⚪ 08:00-23:00", "⚪ 09:00-22:00", "❌ Cancelar"]
    await app.send(SUPER_ID, "de 8 a 8")
    assert app.last_text(SUPER_ID).startswith("⚠️ Escribe el horario así")
    await app.send(SUPER_ID, "de 8 a 23")
    rec = await bot_rec(app)
    assert rec.freq == {"mode": "interval", "every": 240, "window": "08:00-23:00", "days": "0123456"}
    assert local(rec.rot_next_at) in {"08:00", "12:00", "16:00", "20:00"}
    text = app.last_text(SUPER_ID)
    assert "🕐 Horario: 08:00-23:00" in text and "≈ <b>4</b> envíos al día por chat" in text
    assert "🕐 Horario activo: 08:00-23:00" in button_texts(app)

    await app.press(SUPER_ID, FqCB(a="win", t=0).pack())
    await app.click(SUPER_ID, "09:00-22:00")
    rec = await bot_rec(app)
    assert rec.freq["window"] == "09:00-22:00" and local(rec.rot_next_at) in {"09:00", "13:00", "17:00", "21:00"}
    await app.press(SUPER_ID, FqCB(a="win", t=0).pack())
    await app.send(SUPER_ID, "0")
    assert (await bot_rec(app)).freq["window"] == ""
    assert wakes == [1, 1, 1]
    await app.press(SUPER_ID, FqCB(a="wq", t=0, v=9).pack())
    assert "⌛ Este botón ya no está activo. Pulsa /start." in answers(app)


async def test_fixed_times(app: App, wakes: list[int]) -> None:
    await started(app, SUPER_ID)
    await global_every_4h(app)
    await open_menu(app, SUPER_ID, "freq_edit")
    await app.click(SUPER_ID, "A horas fijas")  # the times are asked first
    text = app.last_text(SUPER_ID)
    assert "🕐 <b>Horas fijas</b>" in text and "🕐 Ahora: <b>—</b>" in text
    assert (await bot_rec(app)).freq == EVERY_4H
    await app.send(SUPER_ID, "25:00")
    assert app.last_text(SUPER_ID).startswith("⚠️ No se entiende la hora")
    await app.send(SUPER_ID, ", ".join(f"{h}:00" for h in range(24)) + ", 9:30")
    assert app.last_text(SUPER_ID).startswith("⚠️ Como máximo 24 horas distintas.")
    assert wakes == []

    await app.send(SUPER_ID, "22 y 10:30")
    assert app.last_text(SUPER_ID).startswith("✅ Guardado: a las 10:30 y 22:00\n\n")
    rec = await bot_rec(app)
    assert rec.freq == {"mode": "times", "times": "10:30,22:00", "days": "0123456"}
    assert local(rec.rot_next_at) in {"10:30", "22:00"} and wakes == [1]
    text = app.last_text(SUPER_ID)
    assert "🕐 A las: <b>10:30 y 22:00</b>\n🔄 Días: todos los días" in text and "≈ <b>2</b>" in text
    assert "Cada:" not in text and "Horario:" not in text
    texts = button_texts(app)
    assert texts[:3] == ["⚪ Cada cierto tiempo", "✅ A horas fijas", "✏️ Escribir las horas"]
    assert "✏️ Otro intervalo" not in texts

    await app.click(SUPER_ID, "A horas fijas")  # already: nothing asked
    assert app.last_text(SUPER_ID).startswith("⏰ <b>Frecuencia</b>")
    await app.click(SUPER_ID, "Escribir las horas")
    assert "🕐 Ahora: <b>10:30 y 22:00</b>" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "9")
    assert (await bot_rec(app)).freq["times"] == "09:00"

    await app.press(SUPER_ID, FqCB(a="dp", t=0, v=1).pack())
    await app.press(SUPER_ID, FqCB(a="mode", t=0, v=0).pack())  # back to an interval: the default one
    rec = await bot_rec(app)
    assert rec.freq == {"mode": "interval", "every": 240, "window": "", "days": "01234"}


async def test_days_toggles_and_presets(app: App, wakes: list[int]) -> None:
    await started(app, SUPER_ID)
    await global_every_4h(app)
    await open_menu(app, SUPER_ID, "freq_edit")
    await app.click(SUPER_ID, "L-V")
    rec = await bot_rec(app)
    assert rec.freq["days"] == "01234" and fmt.to_local(rec.rot_next_at, TZ).weekday() < 5
    assert "🔄 Días: de lunes a viernes" in app.last_text(SUPER_ID)
    texts = button_texts(app)
    assert {"✅ L", "✅ V", "S", "D", "Todos", "✅ L-V", "S-D"} <= set(texts)

    await app.press(SUPER_ID, FqCB(a="day", t=0, v=5).pack())
    assert (await bot_rec(app)).freq["days"] == "012345"
    assert answers(app)[-1] == "✅ Guardado: cada 4 h · 08:00-22:00 · L, M, X, J, V, S"
    assert "🔄 Días: L, M, X, J, V, S" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "S-D")
    rec = await bot_rec(app)
    assert rec.freq["days"] == "56" and fmt.to_local(rec.rot_next_at, TZ).weekday() >= 5
    await app.press(SUPER_ID, FqCB(a="day", t=0, v=5).pack())
    await app.press(SUPER_ID, FqCB(a="day", t=0, v=6).pack())  # the last one can't be removed
    assert "⚠️ Elige al menos un día." in answers(app)
    rec = await bot_rec(app)
    assert rec.freq["days"] == "6" and fmt.to_local(rec.rot_next_at, TZ).weekday() == 6
    await app.click(SUPER_ID, "Todos")
    assert (await bot_rec(app)).freq["days"] == "0123456"
    assert wakes == [1] * 5
    await app.press(SUPER_ID, FqCB(a="day", t=0, v=7).pack())
    await app.press(SUPER_ID, FqCB(a="dp", t=0, v=3).pack())
    assert (await bot_rec(app)).freq["days"] == "0123456" and wakes == [1] * 5


async def test_group_frequency_use_global_on_and_off(app: App, wakes: list[int]) -> None:
    g = await add_group(app, "Cine")
    await add_chat(app, -1001, "Cine HD", groups=[g])
    await started(app, SUPER_ID)
    await global_every_4h(app)
    await open_menu(app, SUPER_ID, "group", g)
    await app.click(SUPER_ID, "⏰ Frecuencia")
    text = app.last_text(SUPER_ID)
    assert text.startswith("⏰ <b>Frecuencia</b> · 🗂 Cine\n🌐 Sigue la frecuencia global: <b>cada 4 h · 08:00-22:00</b>")
    assert "Para darle una propia, desmarca «Usar la global»" in text and "≈ <b>4</b>" in text
    assert button_texts(app) == ["✅ Usar la global: cada 4 h · 08:00-22:00", "🔙 Regresar"]
    assert button_data(app, "Regresar") == MenuCB(screen="group", arg=g).pack()

    before = utcnow()
    await app.click(SUPER_ID, "Usar la global")
    group = await load(app, ChatGroup, g)
    assert group.freq == EVERY_4H and group.rot_next_at in freq.upcoming(EVERY_4H, TZ, before, 2)
    assert "✅ Ahora tiene su propia frecuencia (una copia de la global)." in answers(app)
    text = app.last_text(SUPER_ID)
    assert "📣 La siguen: <b>1 chat</b>\n   └ Un canal sigue la frecuencia del primero de sus grupos" in text
    assert "⚪ Usar la global: cada 4 h · 08:00-22:00" in button_texts(app) and "✅ 4 h" in button_texts(app)

    await app.click(SUPER_ID, "1 h")
    group = await load(app, ChatGroup, g)
    assert group.freq == {"mode": "interval", "every": 60, "window": "08:00-22:00", "days": "0123456"}
    assert group.rot_next_at in freq.upcoming(group.freq, TZ, before, 2)
    assert (await bot_rec(app)).freq == EVERY_4H  # the global one didn't change
    await app.click(SUPER_ID, "Regresar")
    assert "⏰ Frecuencia: cada 1 h · 08:00-22:00 (propia)" in app.last_text(SUPER_ID)

    await app.click(SUPER_ID, "⏰ Frecuencia")
    await app.click(SUPER_ID, "Usar la global")
    group = await load(app, ChatGroup, g)
    assert group.freq is None and group.rot_next_at is None
    assert "🌐 Ahora sigue la frecuencia global." in answers(app)
    assert wakes == [1, 1, 1]
    await app.press(SUPER_ID, FqCB(a="glob", t=0).pack())  # only groups follow the global one
    assert (await bot_rec(app)).freq == EVERY_4H and wakes == [1, 1, 1]


async def test_a_change_on_a_group_that_follows_the_global_one_gives_it_its_own(app: App, wakes: list[int]) -> None:
    async with app.db() as s:
        (await s.get(BotRecord, MAIN_BOT_ID)).freq = {"mode": "interval", "every": 180, "window": "08:00-23:00",
                                                      "days": "0123456"}
    g = await add_group(app, "Cine")
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, FqCB(a="day", t=g, v=6).pack())  # e.g. an old panel
    assert (await load(app, ChatGroup, g)).freq == {"mode": "interval", "every": 180, "window": "08:00-23:00",
                                                    "days": "012345"}
    other = await add_group(app, "Otro")
    await app.press(SUPER_ID, FqCB(a="mode", t=other, v=1).pack())
    await app.send(SUPER_ID, "12:00")
    assert (await load(app, ChatGroup, other)).freq == {"mode": "times", "times": "12:00", "days": "0123456"}
    assert wakes == [1, 1]


async def test_group_editor_opened_from_the_dashboard_goes_back_there(app: App) -> None:
    g = await add_group(app, "Cine", freq=OWN_2H)
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "freqs")
    await app.click(SUPER_ID, "🗂 Cine")
    assert app.last_text(SUPER_ID).startswith("⏰ <b>Frecuencia</b> · 🗂 Cine")
    assert button_data(app, "Regresar") == MenuCB(screen="freqs").pack()
    await app.click(SUPER_ID, "Otro intervalo")
    await app.click(SUPER_ID, "Cancelar")
    assert button_data(app, "Regresar") == MenuCB(screen="freqs").pack()  # still the dashboard's editor
    await app.click(SUPER_ID, "Otro intervalo")
    await app.send(SUPER_ID, "45")
    assert (await load(app, ChatGroup, g)).freq["every"] == 45
    assert button_data(app, "Regresar") == MenuCB(screen="freqs").pack()
    await app.click(SUPER_ID, "3 h")
    assert button_data(app, "Regresar") == MenuCB(screen="freqs").pack()
    await app.click(SUPER_ID, "Regresar")
    assert "🗂 <b>Cine</b>: cada 3 h" in app.last_text(SUPER_ID)

    await open_menu(app, SUPER_ID, "freq_edit", g)  # from the group's detail: back to it
    assert button_data(app, "Regresar") == MenuCB(screen="group", arg=g).pack()


async def test_post_frequency_starts_from_a_copy_of_the_global_one(app: App, wakes: list[int]) -> None:
    global_freq = {"mode": "interval", "every": 180, "window": "08:00-23:00", "days": "0123456"}
    async with app.db() as s:
        (await s.get(BotRecord, MAIN_BOT_ID)).freq = global_freq
    p = await add_post(app, "Promo <Cine>", mode=SchedMode.OWN)
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "freq_edit", -p)
    text = app.last_text(SUPER_ID)
    assert text.startswith("⏰ <b>Frecuencia</b> · 📝 Promo &lt;Cine&gt;\n📝 En cada turno se envía a todo su destino")
    assert "🔁 Cada: <b>3 h</b>\n🕐 Horario: 08:00-23:00" in text and "La siguen" not in text
    assert "no se envía con su propio horario" not in text
    assert button_data(app, "Regresar") == MenuCB(screen="post_sched", arg=p).pack()
    assert (await load(app, Post, p)).freq is None  # nothing is stored just by looking

    before = utcnow()
    await app.click(SUPER_ID, "1 h")
    post = await load(app, Post, p)
    assert post.freq == {"mode": "interval", "every": 60, "window": "08:00-23:00", "days": "0123456"}
    assert post.next_send_at in freq.upcoming(post.freq, TZ, before, 2)
    assert (await bot_rec(app)).freq == global_freq and wakes == [1]

    rot = await add_post(app, "En rotación")
    await open_menu(app, SUPER_ID, "freq_edit", -rot)
    assert "ℹ️ Ahora este mensaje no se envía con su propio horario" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "2 h")
    post = await load(app, Post, rot)
    assert post.freq["every"] == 120 and post.next_send_at is None  # only own-schedule posts get a next send


async def test_post_campaign_dates_limit_the_next_sends(app: App) -> None:
    p = await add_post(app, "Campaña", mode=SchedMode.OWN)
    start = fmt.to_local(utcnow(), TZ).date() + timedelta(days=3)
    async with app.db() as s:
        post = await s.get(Post, p)
        post.starts_on, post.ends_on = start, start
    await started(app, SUPER_ID)
    await global_every_4h(app)
    await app.press(SUPER_ID, FqCB(a="ev", t=-p, v=720).pack())
    post = await load(app, Post, p)
    assert fmt.to_local(post.next_send_at, TZ).date() == start
    text = app.last_text(SUPER_ID)
    first = fmt.to_local(post.next_send_at, TZ)
    assert f"📅 Próximos: {first:%d/%m} 08:00 AM, 08:00 PM\n" in text  # two slots that day, then the campaign ends


async def test_rows_of_another_network_are_not_found(app: App, wakes: list[int]) -> None:
    clone = 7_000_000_301
    await app.add_clone(clone, "clon_series_bot", OWNER2_ID)
    clone_group = await add_group(app, "Del clon", bot_id=clone)
    clone_post = await add_post(app, "Del clon", mode=SchedMode.OWN, bot_id=clone)
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, FqCB(a="ev", t=clone_group, v=60).pack())
    await app.press(SUPER_ID, FqCB(a="ev", t=-clone_post, v=60).pack())
    await open_menu(app, SUPER_ID, "freq_edit", clone_group)
    await app.press(SUPER_ID, FqCB(a="ev", t=999_999, v=60).pack())
    assert answers(app) == [NOT_FOUND] * 4
    assert (await load(app, ChatGroup, clone_group)).freq is None
    assert (await load(app, Post, clone_post)).freq is None
    assert wakes == []
    assert "⏰ <b>Frecuencias</b>" in app.last_text(SUPER_ID)


async def test_group_deleted_while_typing_its_interval(app: App, wakes: list[int]) -> None:
    g = await add_group(app, "Cine", freq=OWN_2H)
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, FqCB(a="evx", t=g).pack())
    async with app.db() as s:  # e.g. another admin deletes it meanwhile
        await s.delete(await s.get(ChatGroup, g))
    await app.send(SUPER_ID, "3 h")
    sent = [c.params.get("text") for c in app.fake.calls_of("sendMessage", chat_id=SUPER_ID)]
    assert NOT_FOUND in sent and "⏰ <b>Frecuencias</b>" in app.last_text(SUPER_ID)
    assert wakes == []
    await app.send(SUPER_ID, "2 h")  # the input is over
    assert (await bot_rec(app)).freq == DEFAULT_FREQ


async def test_delete_from_a_group_button_ends_a_pending_input(app: App) -> None:
    g = await add_group(app, "Cine", freq=OWN_2H)
    other = await add_group(app, "Series", freq=OWN_2H)
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, FqCB(a="evx", t=other).pack())
    await app.press(SUPER_ID, GrCB(a="del_ok", id=g).pack())
    await app.send(SUPER_ID, "3 h")
    assert (await load(app, ChatGroup, other)).freq == OWN_2H
