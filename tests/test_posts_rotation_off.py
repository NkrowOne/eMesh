"""Posts with the rotation of the network turned off (``Bot.rotation == "off"``): no 🔁 rotation choice in the
wizard nor in ⏰ Programación (a forged one is refused), the rotation posts left show they are not sent (detail,
⏰ Programación) and the list counts them."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.bot.routers.posts import PoCB, PwCB
from app.db.models import Bot as BotRecord
from app.db.models import Post, PostStatus, RotationOrder, SchedMode
from tests.conftest import MAIN_BOT_ID, SUPER_ID, App
from tests.test_posts_detail import open_post
from tests.test_posts_edit import open_screen_of
from tests.test_posts_helpers import (  # noqa: F401 - fixtures
    CLONE_ID,
    add_clone,
    add_post,
    all_posts,
    answers,
    button_texts,
    engine_fixture,
    load,
    open_menu,
    started,
)
from tests.test_posts_wizard import STEP_5, only_post, start_wizard

ALERT = "⚠️ La rotación está desactivada. Actívala en ⏰ Frecuencias o elige otro tipo de envío."
WHEN_OFF = (
    "⏰ <b>¿Cuándo se envía?</b> · 4/5\n\n"
    "⏰ <b>Con su propio horario</b>\n"
    "   └ Tiene su propia frecuencia; en cada turno se envía a todos sus chats.\n"
    "📢 <b>Difusión puntual</b>\n"
    "   └ Se envía una sola vez a todo su destino: ahora mismo o en la fecha que elijas.\n"
    "✋ <b>Solo cuando lo envíes</b>\n"
    "   └ Únicamente con 🚀 Enviar ahora."
)
MODES_OFF = (
    "⏰ <b>Con su propio horario</b>\n"
    "   └ En cada turno de su horario se envía a todos sus chats.\n"
    "📢 <b>Difusión puntual</b>\n"
    "   └ Se envía una sola vez, en la fecha elegida; después queda terminado.\n"
    "✋ <b>Solo cuando lo envíe yo</b>\n"
    "   └ Únicamente con 🚀 Enviar ahora."
)
NOT_SENT = "⚠️ <b>No se envía</b>: la rotación está desactivada. Elige otro tipo de envío o actívala en ⏰ Frecuencias."
HINT_OFF = "⏰ Envío: 🔁 En rotación\n   └ ⚠️ No se envía: la rotación está desactivada (⏰ Frecuencias)."
HINT_ON = "⏰ Envío: 🔁 En rotación\n   └ Cada canal lo recibe por turnos según su frecuencia."
TITLE = "📝 <b>Mensajes</b>\n"
LEGEND = "🔁 rotación · ⏰ horario propio · 📢 puntual · ✋ manual"
OWN_FREQ = {"mode": "interval", "every": 120, "window": "", "days": "0123456"}
MODE_BUTTONS = ["⏰ Con su propio horario", "📢 Difusión puntual", "✋ Solo cuando lo envíe yo"]


async def set_rotation(app: App, order: str, bot_id: int = MAIN_BOT_ID) -> None:
    async with app.db() as s:
        rec = await s.get(BotRecord, bot_id)
        assert rec is not None
        rec.rotation = order


async def to_step_4(app: App) -> None:
    """A text post without buttons, to everyone, up to step 4 (⏰ ¿Cuándo se envía?)."""
    await start_wizard(app)
    await app.send(SUPER_ID, "Promo de estrenos")
    await app.click(SUPER_ID, "Sin botones")
    await app.click(SUPER_ID, "Continuar")


def last_alert(app: App) -> tuple[str, bool]:
    call = app.fake.calls_of("answerCallbackQuery")[-1]
    return str(call.params.get("text") or ""), bool(call.params.get("show_alert"))


def callback_of(app: App, text: str) -> str:
    button, _ = app.find_button(SUPER_ID, text)
    return str(button["callback_data"])


# --------------------------------------------------------------------------- wizard
async def test_wizard_offers_no_rotation_when_off(app: App, engine: SimpleNamespace) -> None:
    await set_rotation(app, RotationOrder.OFF)
    await to_step_4(app)
    assert app.last_text(SUPER_ID) == WHEN_OFF
    assert button_texts(app) == [*MODE_BUTTONS, "🔙 Regresar", "❌ Cancelar"]
    assert callback_of(app, "Con su propio horario") == PwCB(a="mode", v=1).pack()  # still the index in MODES
    assert callback_of(app, "Solo cuando lo envíe yo") == PwCB(a="mode", v=3).pack()
    await app.send(SUPER_ID, "en rotación")  # a text: the same step with the buttons again
    assert app.last_text(SUPER_ID) == "👇 Usa los botones de abajo.\n\n" + WHEN_OFF

    await app.press(SUPER_ID, PwCB(a="mode", v=0).pack())  # an old or forged 🔁 En rotación
    assert last_alert(app) == (ALERT, True)
    assert app.last_text(SUPER_ID) == WHEN_OFF and button_texts(app)[:3] == MODE_BUTTONS
    assert await all_posts(app) == [] and engine.woke == 0

    await app.click(SUPER_ID, "Solo cuando lo envíe yo")  # still on step 4: the other modes work
    assert app.last_text(SUPER_ID) == STEP_5
    await app.click(SUPER_ID, "No borrar")
    post = await only_post(app)
    assert post.mode == SchedMode.MANUAL and post.status == PostStatus.ACTIVE


@pytest.mark.parametrize("order", [RotationOrder.SEQUENTIAL, RotationOrder.RANDOM])
async def test_wizard_offers_rotation_when_on(app: App, engine: SimpleNamespace, order: str) -> None:
    await set_rotation(app, order)
    await to_step_4(app)
    text = app.last_text(SUPER_ID)
    assert text.startswith("⏰ <b>¿Cuándo se envía?</b> · 4/5\n\n🔁 <b>En rotación</b>\n") and "(global: " in text
    assert button_texts(app) == ["🔁 En rotación", *MODE_BUTTONS, "🔙 Regresar", "❌ Cancelar"]
    await app.click(SUPER_ID, "En rotación")
    assert app.last_text(SUPER_ID) == STEP_5
    await app.click(SUPER_ID, "No borrar")
    assert (await only_post(app)).mode == SchedMode.ROTATION


# --------------------------------------------------------------------------- ⏰ Programación
async def test_schedule_of_a_rotation_post_while_off(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app)
    await set_rotation(app, RotationOrder.OFF)
    text = await open_screen_of(app, "post_sched", pid)
    assert text.startswith(f"⏰ <b>Programación</b> · Promo Cine\n\n{MODES_OFF}\n\n{NOT_SENT}\n\n📆 Campaña: sin fechas")
    assert "🔁 <b>En rotación</b>" not in text and "(global: " not in text
    # The current mode stays visible (ticked), the indexes of the callbacks don't move.
    assert button_texts(app) == ["✅ En rotación", "⚪ Con su propio horario", "⚪ Difusión puntual",
                                 "⚪ Solo cuando lo envíe yo", "📆 Desde: —", "📆 Hasta: —", "🔙 Regresar"]
    assert callback_of(app, "Solo cuando lo envíe yo") == PoCB(a="mode", id=pid, v=3).pack()

    await app.click(SUPER_ID, "En rotación")  # choosing it again: why it isn't sent
    assert last_alert(app) == (ALERT, True)
    post = await load(app, Post, pid)
    assert post.mode == SchedMode.ROTATION and engine.woke == 0
    assert NOT_SENT in app.last_text(SUPER_ID)

    await app.click(SUPER_ID, "Solo cuando lo envíe yo")
    assert (await load(app, Post, pid)).mode == SchedMode.MANUAL and engine.woke == 1
    assert answers(app)[-1] == "✅ Guardado"
    text = app.last_text(SUPER_ID)
    assert MODES_OFF in text and NOT_SENT not in text
    assert button_texts(app) == ["⚪ Con su propio horario", "⚪ Difusión puntual", "✅ Solo cuando lo envíe yo",
                                 "📆 Desde: —", "📆 Hasta: —", "🔙 Regresar"]  # no way back to rotation

    await app.press(SUPER_ID, PoCB(a="mode", id=pid, v=0).pack())  # an old or forged 🔁 En rotación
    assert last_alert(app) == (ALERT, True)
    assert (await load(app, Post, pid)).mode == SchedMode.MANUAL and engine.woke == 1
    assert "⏰ <b>Programación</b> · Promo Cine" in app.last_text(SUPER_ID)
    assert button_texts(app)[0] == "⚪ Con su propio horario"


async def test_schedule_offers_rotation_when_on(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, mode=SchedMode.MANUAL)
    text = await open_screen_of(app, "post_sched", pid)
    assert "🔁 <b>En rotación</b>" in text and "(global: " in text and NOT_SENT not in text
    assert button_texts(app)[:4] == ["⚪ En rotación", "⚪ Con su propio horario", "⚪ Difusión puntual",
                                     "✅ Solo cuando lo envíe yo"]
    await app.click(SUPER_ID, "En rotación")
    assert (await load(app, Post, pid)).mode == SchedMode.ROTATION and answers(app)[-1] == "✅ Guardado"


# --------------------------------------------------------------------------- detail
async def test_detail_says_a_rotation_post_is_not_sent_while_off(app: App, engine: SimpleNamespace) -> None:
    rotation = await add_post(app)
    manual = await add_post(app, name="Manual", mode=SchedMode.MANUAL)
    assert HINT_ON in await open_post(app, rotation)
    await set_rotation(app, RotationOrder.OFF)
    text = await open_post(app, rotation)
    assert HINT_OFF in text and "Cada canal lo recibe por turnos" not in text
    assert "⏰ Envío: ✋ Manual\n   └ Solo se envía al pulsar 🚀 Enviar ahora." in await open_post(app, manual)


# --------------------------------------------------------------------------- list
async def test_list_counts_the_rotation_posts_not_sent_while_off(app: App, engine: SimpleNamespace) -> None:
    await add_clone(app)
    await set_rotation(app, RotationOrder.OFF, CLONE_ID)
    await add_post(app, bot_id=CLONE_ID, name="Del clon")  # another network: not counted
    first = await add_post(app, name="Promo Cine")
    await add_post(app, name="Promo Series")
    await add_post(app, name="Pausado", status=PostStatus.PAUSED)  # not active: not counted
    await add_post(app, name="Horario", mode=SchedMode.OWN, freq=OWN_FREQ)
    await add_post(app, name="Manual", mode=SchedMode.MANUAL)
    await started(app, SUPER_ID)

    await open_menu(app, SUPER_ID, "posts")
    assert app.last_text(SUPER_ID).startswith(TITLE + LEGEND)  # rotation on: no banner

    await set_rotation(app, RotationOrder.OFF)
    await open_menu(app, SUPER_ID, "posts")
    text = app.last_text(SUPER_ID)
    assert text.startswith(TITLE + "⚠️ Rotación desactivada: 2 mensajes 🔁 en rotación no se envían.\n" + LEGEND)
    assert "1. ▶️ 🔁 <b>Promo Cine</b>" in text

    async with app.db() as s:
        post = await s.get(Post, first)
        assert post is not None
        post.mode = SchedMode.ONCE
        post.status = PostStatus.DONE
    await open_menu(app, SUPER_ID, "posts")
    assert app.last_text(SUPER_ID).startswith(
        TITLE + "⚠️ Rotación desactivada: 1 mensaje 🔁 en rotación no se envía.\n" + LEGEND)


async def test_list_without_rotation_posts_has_no_banner_while_off(app: App, engine: SimpleNamespace) -> None:
    await set_rotation(app, RotationOrder.OFF)
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "posts")
    assert app.last_text(SUPER_ID).startswith(TITLE + LEGEND + "\n\n📭 Todavía no hay mensajes")
    await add_post(app, name="Horario", mode=SchedMode.OWN, freq=OWN_FREQ)
    await add_post(app, name="Pausado", status=PostStatus.PAUSED)
    await open_menu(app, SUPER_ID, "posts")
    text = app.last_text(SUPER_ID)
    assert text.startswith(TITLE + LEGEND) and "Rotación desactivada" not in text
