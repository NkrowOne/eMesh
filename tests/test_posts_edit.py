"""Posts: the screens of content, targets, schedule (modes, date, campaign), options and default options."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.bot.routers.posts import OPTIONS, PoCB, defaults_of, parse_minutes, toggle_target
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import DEFAULT_DELETE_AFTER, ChatOrigin, Post, SchedMode
from app.ui import fmt
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, SUPER_ID, App
from tests.test_posts_helpers import (  # noqa: F401 - fixtures
    EXPIRED,
    TZ,
    add_chat,
    add_clone,
    add_group,
    add_post,
    all_posts,
    answers,
    button_texts,
    engine_fixture,
    freq_screen_fixture,
    load,
    open_menu,
    started,
)


def sticker_update(app: App) -> dict:
    update = app.message_update(SUPER_ID)
    update["message"]["sticker"] = {"file_id": "stk", "file_unique_id": "ustk", "type": "regular", "width": 512,
                                    "height": 512, "is_animated": False, "is_video": False}
    return update


async def open_screen_of(app: App, screen: str, post_id: int = 0) -> str:
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, screen, post_id)
    return app.last_text(SUPER_ID)


# --------------------------------------------------------------------------- helpers
@pytest.mark.parametrize(("text", "minutes"), [
    ("45 min", 45), ("2 h", 120), ("1h30", 90), ("1:30", 90), ("1.5 h", 90), ("1 h 30 min", 90), ("36", 2160),
    ("36 h", 2160), ("90", 90), ("48h", 2880), ("2 horas y 30 minutos", 150), ("0", 0), ("nunca", 0),
])
def test_parse_minutes(text: str, minutes: int) -> None:
    assert parse_minutes(text) == minutes


@pytest.mark.parametrize(("text", "key"), [
    ("10 min", "po.err.duration_range"), ("49 h", "po.err.duration_range"), ("abc", "po.err.duration"),
    ("", "po.err.duration"), ("0.1", "po.err.duration_range"),
])
def test_parse_minutes_errors(text: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        parse_minutes(text)


def test_default_options_never_delete_new_posts() -> None:
    assert DEFAULT_DELETE_AFTER == 0
    assert defaults_of(BotRecord(post_defaults={})) == {"pin": False, "silent": False, "protect": False,
                                                       "link_preview": False, "delete_previous": True,
                                                       "delete_after": 0}
    assert defaults_of(BotRecord(post_defaults={"pin": True}))["delete_after"] == 0  # a network without one
    assert defaults_of(BotRecord(post_defaults={"delete_after": 1440}))["delete_after"] == 1440
    assert defaults_of(BotRecord(post_defaults={"delete_after": 360}))["delete_after"] == 360


def test_toggle_target() -> None:
    groups = {3, 5}
    assert toggle_target(["all"], "own", groups) == ["own"]  # a specific target replaces 🌐 Todos
    assert toggle_target(["own"], "g5", groups) == ["own", "g5"]
    assert toggle_target(["own"], "ext", groups) == ["all"]  # own + external = everyone
    assert toggle_target(["own", "g5"], "own", groups) == ["g5"]
    assert toggle_target(["g5"], "g5", groups) == []  # the caller refuses an empty list
    assert toggle_target(["all"], "all", groups) == []
    assert toggle_target(["g5", "g9"], "all", groups) == ["all"]
    assert toggle_target(["g9", "ext"], "g3", groups) == ["ext", "g3"]  # groups that no longer exist are dropped


# --------------------------------------------------------------------------- ✏️ Contenido
async def test_change_the_message_the_text_and_the_name(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, name="Promo de cine")  # the automatic name (its first words)
    text = await open_screen_of(app, "post_content", pid)
    for expected in ("✏️ <b>Contenido</b> · Promo de cine", "🏷 Nombre interno: Promo de cine",
                     "🧩 Tipo: 📝 Texto", "📝 Texto: <i>Promo de cine</i>"):
        assert expected in text, expected
    assert button_texts(app) == ["✏️ Cambiar el mensaje", "📝 Cambiar solo el texto", "🏷 Nombre interno",
                                 "🔙 Regresar"]

    await app.click(SUPER_ID, "Cambiar el mensaje")
    assert "✏️ <b>Cambiar el mensaje</b> · Promo de cine" in app.last_text(SUPER_ID)
    await app.feed(sticker_update(app))
    assert "Ese tipo de mensaje no se puede distribuir" in app.last_text(SUPER_ID)
    await app.feed(app.message_update(SUPER_ID, photo="ph_new", caption="Gran estreno"))
    post = await load(app, Post, pid)
    assert (post.kind, post.media, post.text) == ("photo", {str(MAIN_BOT_ID): "ph_new"}, "Gran estreno")
    assert post.name == "Gran estreno"  # the automatic name follows the new text
    text = app.last_text(SUPER_ID)
    assert text.startswith("✅ Guardado\n\n✏️ <b>Contenido</b>") and "🧩 Tipo: 🖼 Foto" in text
    assert "Actualizar publicados" not in text  # nothing published
    assert "🖼 Quitar multimedia" in button_texts(app)

    await app.click(SUPER_ID, "Cambiar solo el texto")
    assert "así que el texto puede tener como máximo 1024 caracteres" in app.last_text(SUPER_ID)
    await app.feed(app.message_update(SUPER_ID, photo="ph_other"))
    assert "⚠️ Envíalo como texto." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "y" * 1100)
    assert "como máximo 1024 caracteres. Acórtalo" in app.last_text(SUPER_ID)
    engine.live = 3
    await app.send(SUPER_ID, "Nuevo texto", entities=[{"type": "bold", "offset": 0, "length": 5}])
    post = await load(app, Post, pid)
    assert (post.text, post.media, post.name) == ("<b>Nuevo</b> texto", {str(MAIN_BOT_ID): "ph_new"}, "Nuevo texto")
    assert "🔄 Pulsa Actualizar publicados para aplicarlo a los ya enviados." in app.last_text(SUPER_ID)

    await app.click(SUPER_ID, "Nombre interno")
    assert "Actual: Nuevo texto" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "x" * 65)
    assert "demasiado largo (máximo 64 caracteres)" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "  Promo   <Viernes> ")
    assert (await load(app, Post, pid)).name == "Promo <Viernes>"
    assert "🏷 Nombre interno: Promo &lt;Viernes&gt;" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Cambiar solo el texto")
    await app.send(SUPER_ID, "Otro texto")
    assert (await load(app, Post, pid)).name == "Promo <Viernes>"  # a name set by hand stays


async def test_remove_the_media(app: App, engine: SimpleNamespace) -> None:
    bare = await add_post(app, kind="photo", text=None, media={str(MAIN_BOT_ID): "ph"})
    await open_screen_of(app, "post_content", bare)
    await app.click(SUPER_ID, "Quitar multimedia")
    assert answers(app)[-1].startswith("⚠️ Sin el contenido multimedia quedaría vacío")
    assert (await load(app, Post, bare)).kind == "photo"

    pid = await add_post(app, kind="video", text="Tráiler", media={str(MAIN_BOT_ID): "vid"}, media_name="t.mp4")
    await open_screen_of(app, "post_content", pid)
    await app.click(SUPER_ID, "Quitar multimedia")
    assert "🖼 ¿Quitar el contenido multimedia de <b>Promo Cine</b>?" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "No")
    assert (await load(app, Post, pid)).kind == "video"
    await app.click(SUPER_ID, "Quitar multimedia")
    await app.click(SUPER_ID, "🖼 Quitar multimedia")
    post = await load(app, Post, pid)
    assert (post.kind, post.media, post.media_name, post.text) == ("text", {}, None, "Tráiler")
    assert answers(app)[-1] == "🖼 Multimedia quitado" and "🧩 Tipo: 📝 Texto" in app.last_text(SUPER_ID)
    assert "🖼 Quitar multimedia" not in button_texts(app)


# --------------------------------------------------------------------------- 🎯 Destino
async def test_targets_are_saved_at_once(app: App, engine: SimpleNamespace) -> None:
    await add_chat(app, -1001, "Cine HD", 1200)
    ext = await add_chat(app, -1002, "Series Club", 800, origin=ChatOrigin.EXTERNAL)
    gid = await add_group(app, "Series", (ext,))
    await add_clone(app)
    foreign = await add_group(app, "Ajeno", bot_id=7_000_000_031)
    pid = await add_post(app)

    text = await open_screen_of(app, "post_targets", pid)
    assert "🎯 <b>Destino</b> · Promo Cine" in text and "👥 Lo recibirán: <b>2 chats</b> · 👤 2,000" in text
    assert button_texts(app) == ["✅ Todos", "⚪ Solo propios", "⚪ Solo externos", "⚪ Series (1)", "🔙 Regresar"]
    await app.click(SUPER_ID, "Series (1)")
    assert (await load(app, Post, pid)).targets == [f"g{gid}"]
    assert "👥 Lo recibirán: <b>1 chat</b> · 👤 800" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Solo propios")
    assert (await load(app, Post, pid)).targets == ["own", f"g{gid}"]
    assert "👥 Lo recibirán: <b>2 chats</b>" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Solo propios")
    await app.click(SUPER_ID, "Series (1)")  # the last target stays
    assert answers(app)[-1] == "⚠️ Elige al menos un destino."
    assert (await load(app, Post, pid)).targets == [f"g{gid}"]
    await app.press(SUPER_ID, PoCB(a="tg", id=pid, t=f"g{foreign}").pack())  # a group of another network
    assert answers(app)[-1] == EXPIRED and (await load(app, Post, pid)).targets == [f"g{gid}"]
    await app.click(SUPER_ID, "Todos")
    assert (await load(app, Post, pid)).targets == ["all"]
    await app.click(SUPER_ID, "Regresar")
    assert "🎯 Destino: 🌐 Todos → 2 chats (👤 2,000)" in app.last_text(SUPER_ID)


# --------------------------------------------------------------------------- ⏰ Programación
SCHED_MODES = (
    "⏰ <b>A sus horas</b>\n"
    "   └ Se envía a todo su destino a cada hora de su horario.\n"
    "📢 <b>Difusión puntual</b>\n"
    "   └ Se envía una sola vez, en la fecha elegida; después queda terminado.\n"
    "✋ <b>Solo cuando lo envíe yo</b>\n"
    "   └ Únicamente con 🚀 Enviar ahora."
)
CAMPAIGN_HINT = "   └ Opcional. Fuera de esas fechas no se envía a sus horas; pasado el último día queda terminado."


async def test_schedule_modes(app: App, engine: SimpleNamespace, freq_screen: list[int]) -> None:
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        assert rec is not None
        rec.freq = {"mode": "interval", "every": 180, "window": "", "days": "0123456"}
    pid = await add_post(app, mode=SchedMode.MANUAL, freq=None)
    text = await open_screen_of(app, "post_sched", pid)
    assert text == f"⏰ <b>Programación</b> · Promo Cine\n\n{SCHED_MODES}\n\n📆 Campaña: sin fechas\n{CAMPAIGN_HINT}"
    assert button_texts(app) == ["⚪ A sus horas", "⚪ Difusión puntual", "✅ Solo cuando lo envíe yo",
                                 "📆 Desde: —", "📆 Hasta: —", "🔙 Regresar"]  # exactly the three modes
    assert [app.find_button(SUPER_ID, label)[0]["callback_data"] for label in ("A sus horas", "Difusión puntual",
                                                                               "Solo cuando lo envíe yo")] == [
        PoCB(a="mode", id=pid, v=i).pack() for i in range(3)]
    await app.press(SUPER_ID, PoCB(a="mode", id=pid, v=3).pack())  # an old or forged index outside the modes
    assert answers(app)[-1] == EXPIRED and (await load(app, Post, pid)).mode == SchedMode.MANUAL
    assert engine.woke == 0

    await app.click(SUPER_ID, "A sus horas")  # it starts with a copy of the default schedule
    post = await load(app, Post, pid)
    assert post.mode == SchedMode.OWN and post.freq == {"mode": "interval", "every": 180, "window": "",
                                                        "days": "0123456"}
    assert post.next_send_at is not None and engine.woke == 1 and answers(app)[-1] == "✅ Guardado"
    assert f"📅 Próximo envío: <b>{fmt.dt(post.next_send_at, TZ)}</b>" in app.last_text(SUPER_ID)
    own, _ = app.find_button(SUPER_ID, "Horario propio: cada 3 h")
    assert own["callback_data"] == MenuCB(screen="freq_edit", arg=-pid).pack()
    await app.click(SUPER_ID, "Horario propio")
    assert freq_screen == [-pid]

    await open_menu(app, SUPER_ID, "post_sched", pid)
    await app.click(SUPER_ID, "Solo cuando lo envíe yo")
    post = await load(app, Post, pid)
    assert post.mode == SchedMode.MANUAL and post.next_send_at is None and engine.woke == 2

    await app.click(SUPER_ID, "Difusión puntual")  # no date yet: it is asked first
    assert "📆 <b>Fecha del envío</b> · Promo Cine" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "32/13/2026 10:00")
    assert "Escribe la fecha y la hora así" in app.last_text(SUPER_ID)
    assert (await load(app, Post, pid)).mode == SchedMode.MANUAL
    when = (utcnow() + timedelta(days=2)).astimezone(fmt.zone(TZ))
    await app.send(SUPER_ID, when.strftime("%d/%m %H:%M"))
    post = await load(app, Post, pid)
    assert post.mode == SchedMode.ONCE and post.send_at is not None and post.next_send_at == post.send_at
    assert post.send_at.astimezone(fmt.zone(TZ)).strftime("%d/%m %H:%M") == when.strftime("%d/%m %H:%M")
    assert app.last_text(SUPER_ID).startswith("✅ Guardado\n\n⏰ <b>Programación</b>") and engine.woke == 3
    assert f"📆 Fecha: {when:%d/%m %H:%M}" in button_texts(app)

    await app.click(SUPER_ID, "📆 Fecha")
    await app.click(SUPER_ID, "Cancelar")
    assert "⏰ <b>Programación</b>" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "A sus horas")  # back to its own times: the schedule it had is kept
    post = await load(app, Post, pid)
    assert post.mode == SchedMode.OWN and post.freq == {"mode": "interval", "every": 180, "window": "",
                                                        "days": "0123456"}
    assert post.next_send_at is not None and post.next_send_at != post.send_at and post.send_at is not None
    await app.click(SUPER_ID, "Difusión puntual")  # its date is still in the future: no question
    post = await load(app, Post, pid)
    assert post.mode == SchedMode.ONCE and post.next_send_at == post.send_at


async def test_campaign_dates(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, mode=SchedMode.OWN, freq={"mode": "interval", "every": 60, "window": "",
                                                        "days": "0123456"})
    await open_screen_of(app, "post_sched", pid)
    await app.click(SUPER_ID, "Desde")
    assert "📆 <b>Inicio de la campaña</b> · Promo Cine" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "32/01/2099")
    assert "⚠️ Escribe la fecha así" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "10/12/2099")
    post = await load(app, Post, pid)
    assert post.starts_on is not None and f"{post.starts_on:%d/%m/%Y}" == "10/12/2099"
    assert post.next_send_at is not None and post.next_send_at.year == 2099  # not before the campaign starts
    assert "📆 Campaña: desde el 10/12/2099" in app.last_text(SUPER_ID)

    await app.click(SUPER_ID, "Hasta")
    await app.send(SUPER_ID, "01/12/2099")
    assert "⚠️ El fin de la campaña no puede ser anterior a su inicio." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "01/01/2020")
    assert "⚠️ Esa fecha ya ha pasado." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "31/12/2099")
    text = app.last_text(SUPER_ID)
    assert "📆 Campaña: del 10/12/2099 al 31/12/2099" in text
    assert "📆 Desde: 10/12/2099" in button_texts(app) and "📆 Hasta: 31/12/2099" in button_texts(app)

    await app.click(SUPER_ID, "Desde")
    await app.send(SUPER_ID, "0")
    post = await load(app, Post, pid)
    assert post.starts_on is None and f"{post.ends_on:%d/%m/%Y}" == "31/12/2099"
    assert post.next_send_at is not None and post.next_send_at < utcnow() + timedelta(hours=2)
    assert engine.woke == 3


# --------------------------------------------------------------------------- ⚙️ Opciones
async def test_options_of_a_post(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app)
    text = await open_screen_of(app, "post_opts", pid)
    assert "⚙️ <b>Opciones</b> · Promo Cine" in text
    assert "📌 Fijar: ✖️\n   └ Se fija en el chat sin avisar a los miembros." in text
    assert "🗑 Borrado automático: ✖️ nunca\n   └ Cada copia se borra automáticamente" in text
    assert button_texts(app) == ["✖️ Fijar", "✖️ Sin sonido", "✖️ Proteger contenido", "✖️ Vista previa de enlaces",
                                 "✅ Borrar su envío anterior", "✅ Nunca", "⚪ 1 h", "⚪ 3 h", "⚪ 6 h", "⚪ 12 h",
                                 "⚪ 1 día", "⚪ 2 días", "✏️ Otro", "🔙 Regresar"]
    await app.click(SUPER_ID, "Fijar")
    assert answers(app)[-1] == "✅ Fijar" and (await load(app, Post, pid)).pin is True
    await app.click(SUPER_ID, "Vista previa de enlaces")
    await app.click(SUPER_ID, "Borrar su envío anterior")
    await app.click(SUPER_ID, "1 día")
    post = await load(app, Post, pid)
    assert (post.pin, post.link_preview, post.delete_previous, post.delete_after) == (True, True, False, 1440)
    assert "🗑 Borrado automático: a las 24 h de enviarse" in app.last_text(SUPER_ID)
    assert "✅ 1 día" in button_texts(app)
    await app.press(SUPER_ID, PoCB(a="opt", id=pid, v=OPTIONS.index("spoiler")).pack())  # not for text posts
    await app.press(SUPER_ID, PoCB(a="ad", id=pid, v=7).pack())  # not one of the choices
    assert answers(app)[-2:] == [EXPIRED, EXPIRED]
    post = await load(app, Post, pid)
    assert post.spoiler is False and post.delete_after == 1440

    await app.click(SUPER_ID, "Otro")
    assert "🗑 <b>Borrado automático</b>" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "10 min")
    assert "⚠️ Elige entre 15 minutos y 48 horas." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "cuando sea")
    assert "⚠️ No se entiende." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "1 h 30 min")
    assert (await load(app, Post, pid)).delete_after == 90
    assert "✅ 1 h 30 min" in button_texts(app) and "✏️ Otro" not in button_texts(app)
    assert "a las 1 h 30 min de enviarse" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Regresar")
    assert "🗑 Borrado automático: a las 1 h 30 min de enviarse</blockquote>" in app.last_text(SUPER_ID)

    photo = await add_post(app, kind="photo", media={str(MAIN_BOT_ID): "ph"})
    await open_menu(app, SUPER_ID, "post_opts", photo)
    assert "✖️ Texto encima del multimedia" in button_texts(app) and "✖️ Spoiler" in button_texts(app)
    assert "✖️ Vista previa de enlaces" not in button_texts(app)
    await app.click(SUPER_ID, "Spoiler")
    await app.click(SUPER_ID, "Texto encima del multimedia")
    post = await load(app, Post, photo)
    assert post.spoiler is True and post.caption_above is True


async def test_default_options_of_new_posts(app: App, engine: SimpleNamespace) -> None:
    text = await open_screen_of(app, "post_defaults")
    assert text.startswith("⚙️ <b>Opciones por defecto</b>\nSe aplican a los mensajes nuevos")
    assert "🗑 Borrado automático: ✖️ nunca" in text  # nothing stored yet: never
    assert button_texts(app)[:5] == ["✖️ Fijar", "✖️ Sin sonido", "✖️ Proteger contenido",
                                     "✖️ Vista previa de enlaces", "✅ Borrar su envío anterior"]
    assert button_texts(app)[5:12] == ["✅ Nunca", "⚪ 1 h", "⚪ 3 h", "⚪ 6 h", "⚪ 12 h", "⚪ 1 día", "⚪ 2 días"]
    assert "✖️ Spoiler" not in button_texts(app)
    await app.click(SUPER_ID, "Proteger contenido")
    await app.click(SUPER_ID, "6 h")
    rec = await load(app, BotRecord, MAIN_BOT_ID)
    assert rec.post_defaults == {"pin": False, "silent": False, "protect": True, "link_preview": False,
                                 "delete_previous": True, "delete_after": 360}
    await app.click(SUPER_ID, "Otro")
    await app.send(SUPER_ID, "36 h")
    assert (await load(app, BotRecord, MAIN_BOT_ID)).post_defaults["delete_after"] == 2160
    assert "✅ 36 h" in button_texts(app)
    await app.click(SUPER_ID, "Regresar")
    assert "📝 <b>Mensajes</b>" in app.last_text(SUPER_ID)

    await app.click(SUPER_ID, "Nuevo mensaje")  # a new post takes them
    await app.send(SUPER_ID, "Con opciones por defecto")
    await app.click(SUPER_ID, "Sin botones")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "Solo cuando lo envíe yo")
    assert "✅ 36 h" in button_texts(app)  # step 5: the network's default pre-selected
    await app.click(SUPER_ID, "36 h")
    (post,) = await all_posts(app)
    assert (post.protect, post.delete_after, post.pin, post.delete_previous) == (True, 2160, False, True)
