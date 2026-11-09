"""Posts: the create wizard (content → buttons → targets → when → how long it stays published), default options,
limits and workspaces."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.bot.routers.posts import PwCB
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import Chat, ChatGroup, ChatOrigin, Post, PostStatus, Run, SchedMode
from app.services.scheduler import Scheduler
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, App
from tests.test_engine import make_chats, texts_in
from tests.test_posts_helpers import (  # noqa: F401 - fixtures
    CLONE_ID,
    EXPIRED,
    NOT_FOUND,
    add_chat,
    add_clone,
    add_group,
    add_post,
    all_posts,
    answers,
    button_texts,
    engine_fixture,
    freq_screen_fixture,
    keyboard,
    manage_clone,
    open_menu,
    started,
)

MADRID = ZoneInfo("Europe/Madrid")
BUTTONS = ("Web - https://example.com 🟢\n"
           "Canal - @micanal && Grupo - t.me/migrupo 🔴\n"
           "Código - copiar: PROMO10 🔵")
STEP_5 = "🗑 <b>¿Cuánto tiempo sigue publicado?</b> · 5/5\n   └ Pasado ese tiempo se borra solo de los canales."


async def start_wizard(app: App, user_id: int = SUPER_ID, bot_id: int = MAIN_BOT_ID) -> None:
    await started(app, user_id, bot_id=bot_id)
    await open_menu(app, user_id, "posts", bot_id=bot_id)
    await app.click(user_id, "Nuevo mensaje", bot_id=bot_id)
    assert "📝 <b>Nuevo mensaje</b> · 1/5" in app.last_text(user_id)


async def to_step_5(app: App, mode: str = "Solo cuando lo envíe yo") -> None:
    """A text post without buttons, to everyone, up to step 5 (🗑 ¿Cuánto tiempo sigue publicado?)."""
    await start_wizard(app)
    await app.send(SUPER_ID, "Promo de estrenos")
    await app.click(SUPER_ID, "Sin botones")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, mode)
    assert app.last_text(SUPER_ID) == STEP_5


def step_5_rows(app: App) -> list[list[str]]:
    return [[b["text"] for b in row] for row in keyboard(app)]


async def set_default_delete_after(app: App, minutes: int) -> None:
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        assert rec is not None
        rec.post_defaults = {"pin": True, "delete_after": minutes}


async def only_post(app: App) -> Post:
    posts = await all_posts(app)
    assert len(posts) == 1, posts
    return posts[0]


def sticker_update(app: App, user_id: int = SUPER_ID) -> dict:
    update = app.message_update(user_id)
    update["message"]["sticker"] = {"file_id": "stk", "file_unique_id": "ustk", "type": "regular", "width": 512,
                                    "height": 512, "is_animated": False, "is_video": False}
    return update


async def test_wizard_text_post_with_colored_buttons_and_defaults(app: App, engine: SimpleNamespace) -> None:
    await add_chat(app, -1001, "Cine HD", 1200)
    await add_chat(app, -1002, "Series Club", 800, origin=ChatOrigin.EXTERNAL)
    await add_chat(app, -1003, "Canal Pausado", 5000, admin_paused=True)  # not sendable: not counted
    async with app.db() as s:  # the default options of the network apply to new posts
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        assert rec is not None
        rec.post_defaults = {"pin": True, "silent": True, "delete_after": 720, "delete_previous": False}

    await start_wizard(app)
    assert button_texts(app) == ["❌ Cancelar"]  # the first step only has Cancel
    await app.send(SUPER_ID, "Oferta de cine hoy", entities=[{"type": "bold", "offset": 10, "length": 4}])
    text = app.last_text(SUPER_ID)
    assert "🔘 <b>Botones</b> · 2/5" in text and "Código - copiar: PROMO10 🔵" in text and "&amp;&amp;" in text
    assert button_texts(app) == ["⏭ Sin botones", "🔙 Regresar", "❌ Cancelar"]
    await app.send(SUPER_ID, "Web sin enlace")
    assert "Línea 1: escribe cada botón así" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, BUTTONS)

    text = app.last_text(SUPER_ID)
    assert "🎯 <b>¿A quién se envía?</b> · 3/5" in text
    assert "👥 Lo recibirán: <b>2 chats</b> · 👤 2,000" in text
    assert button_texts(app) == ["✅ Todos", "⚪ Solo propios", "⚪ Solo externos", "✅ Continuar", "🔙 Regresar",
                                 "❌ Cancelar"]
    await app.click(SUPER_ID, "Solo propios")
    assert "👥 Lo recibirán: <b>1 chat</b> · 👤 1,200" in app.last_text(SUPER_ID)
    assert button_texts(app)[:3] == ["⚪ Todos", "✅ Solo propios", "⚪ Solo externos"]
    await app.click(SUPER_ID, "Solo propios")  # the only target can't be removed
    assert answers(app)[-1] == "⚠️ Elige al menos un destino."
    assert button_texts(app)[1] == "✅ Solo propios"
    await app.send(SUPER_ID, "solo los propios")
    assert "👇 Usa los botones de abajo." in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Continuar")

    text = app.last_text(SUPER_ID)
    assert "⏰ <b>¿Cuándo se envía?</b> · 4/5" in text and "(global: a las 12:00)" in text
    assert button_texts(app)[:4] == ["🔁 En rotación", "⏰ Con su propio horario", "📢 Difusión puntual",
                                     "✋ Solo cuando lo envíe yo"]
    await app.click(SUPER_ID, "En rotación")

    assert app.last_text(SUPER_ID) == STEP_5  # the network's default is pre-selected
    assert button_texts(app) == ["⚪ 1 h", "⚪ 3 h", "⚪ 6 h", "✅ 12 h", "⚪ 1 día", "⚪ 2 días", "⚪ No borrar",
                                 "🔙 Regresar", "❌ Cancelar"]
    assert await all_posts(app) == [] and engine.woke == 0  # created only after the last step
    await app.click(SUPER_ID, "12 h")

    post = await only_post(app)
    assert (post.name, post.text, post.kind, post.media) == ("Oferta de cine hoy", "Oferta de <b>cine</b> hoy", "text",
                                                             {})
    assert post.buttons == [
        [{"text": "Web", "url": "https://example.com", "style": "success"}],
        [{"text": "Canal", "url": "https://t.me/micanal"},
         {"text": "Grupo", "url": "https://t.me/migrupo", "style": "danger"}],
        [{"text": "Código", "copy": "PROMO10", "style": "primary"}],
    ]
    assert post.targets == ["own"] and post.mode == SchedMode.ROTATION and post.status == PostStatus.ACTIVE
    assert (post.pin, post.silent, post.protect, post.link_preview) == (True, True, False, False)
    assert (post.delete_after, post.delete_previous, post.caption_above, post.spoiler) == (720, False, False, False)
    assert (post.bot_id, post.created_by, post.next_send_at) == (MAIN_BOT_ID, SUPER_ID, None)
    assert engine.woke == 1
    text = app.last_text(SUPER_ID)
    assert text.startswith("✅ Mensaje guardado\n\n📝 <b>Oferta de cine hoy</b>")
    assert "🎯 Destino: 🏠 Propios → 1 chat (👤 1,200)" in text and "🧩 Tipo: 📝 Texto · 🔘 4 botones" in text
    assert "🗑 Borrado automático: a las 12 h de enviarse</blockquote>" in text


async def test_wizard_photo_post_to_a_group_of_chats_once(app: App, engine: SimpleNamespace) -> None:
    cine = await add_chat(app, -1001, "Cine HD", 1200)
    await add_chat(app, -1002, "Series Club", 800)
    gid = await add_group(app, "Cine", (cine,))

    await start_wizard(app)
    await app.feed(app.message_update(SUPER_ID, photo="ph_big", caption="x" * 1100))
    assert "como máximo 1024 caracteres" in app.last_text(SUPER_ID)
    await app.feed(app.message_update(SUPER_ID, photo="ph_1", caption="Estreno del viernes",
                                      caption_entities=[{"type": "italic", "offset": 0, "length": 7}]))
    assert "🔘 <b>Botones</b> · 2/5" in app.last_text(SUPER_ID)
    await app.feed(app.message_update(SUPER_ID, photo="ph_2"))
    assert "⚠️ Envíalo como texto." in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Entradas - https://cine.example.com 🟢 && Código - copiar: CINE5 🔴")
    assert "⚪ Cine (1)" in button_texts(app)
    await app.click(SUPER_ID, "Cine (1)")
    assert "👥 Lo recibirán: <b>1 chat</b> · 👤 1,200" in app.last_text(SUPER_ID)
    assert "✅ Cine (1)" in button_texts(app) and "⚪ Todos" in button_texts(app)
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "Difusión puntual")
    assert "📢 <b>Difusión puntual</b> · 4/5" in app.last_text(SUPER_ID)  # the date still belongs to step 4
    assert "🗺 Zona horaria: Europe/Madrid" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "mañana por la tarde")
    assert "Escribe la fecha y la hora así" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "01/01/2020 10:00")
    assert "⚠️ Esa fecha ya ha pasado." in app.last_text(SUPER_ID)
    day = (utcnow() + timedelta(days=3)).astimezone(MADRID)
    await app.send(SUPER_ID, day.strftime("%d/%m/%Y") + " 20:30")
    assert app.last_text(SUPER_ID) == STEP_5 and await all_posts(app) == []
    await app.click(SUPER_ID, "2 días")

    post = await only_post(app)
    expected = datetime(day.year, day.month, day.day, 20, 30, tzinfo=MADRID)
    assert post.kind == "photo" and post.media == {str(MAIN_BOT_ID): "ph_1"}
    assert (post.text, post.name) == ("<i>Estreno</i> del viernes", "Estreno del viernes")
    assert post.buttons == [[{"text": "Entradas", "url": "https://cine.example.com", "style": "success"},
                             {"text": "Código", "copy": "CINE5", "style": "danger"}]]
    assert post.targets == [f"g{gid}"] and post.mode == SchedMode.ONCE
    assert post.send_at == expected and post.next_send_at == expected and post.delete_after == 2880
    text = app.last_text(SUPER_ID)
    assert "✅ Mensaje guardado" in text and "🎯 Destino: 🗂 Cine → 1 chat (👤 1,200)" in text
    assert "⏰ Envío: 📢 Difusión puntual · " in text and "🧩 Tipo: 🖼 Foto · 🔘 2 botones" in text
    assert "🫣 Spoiler: ✖️" in text and "🗑 Borrado automático: a las 48 h de enviarse" in text  # visual media


async def test_wizard_own_schedule_opens_the_frequency_editor(app: App, engine: SimpleNamespace,
                                                              freq_screen: list[int]) -> None:
    await add_chat(app, -1001)
    global_freq = {"mode": "interval", "every": 120, "window": "08:00-22:00", "days": "0123456"}
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        assert rec is not None
        rec.freq = dict(global_freq)
    await start_wizard(app)
    await app.send(SUPER_ID, "Noticias del día")
    await app.click(SUPER_ID, "Sin botones")
    await app.click(SUPER_ID, "Continuar")
    assert "(global: cada 2 h · 08:00-22:00)" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Con su propio horario")
    assert "✅ No borrar" in button_texts(app) and freq_screen == []  # no default stored: never
    await app.click(SUPER_ID, "1 día")

    post = await only_post(app)
    assert freq_screen == [-post.id] and app.last_text(SUPER_ID) == f"FREQ_EDIT {-post.id}"
    assert answers(app)[-1] == "✅ Mensaje guardado"
    assert post.mode == SchedMode.OWN and post.freq == global_freq  # a copy of the global frequency
    assert post.delete_after == 1440
    assert post.next_send_at is not None and post.next_send_at > utcnow()
    assert engine.woke == 1


async def test_wizard_from_the_post_new_screen_in_manual_mode(app: App, engine: SimpleNamespace) -> None:
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post_new")  # other modules open the wizard by its screen name
    assert "📝 <b>Nuevo mensaje</b> · 1/5" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Solo a mano")
    await app.click(SUPER_ID, "Sin botones")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "Solo cuando lo envíe yo")
    await app.click(SUPER_ID, "No borrar")
    post = await only_post(app)
    assert post.mode == SchedMode.MANUAL and post.next_send_at is None and post.targets == ["all"]
    assert post.delete_after == 0
    text = app.last_text(SUPER_ID)
    assert "⏰ Envío: ✋ Manual\n   └ Solo se envía al pulsar 🚀 Enviar ahora." in text
    assert "🗑 Borrado automático: ✖️ nunca</blockquote>" in text


async def test_wizard_back_goes_to_the_previous_step_keeping_answers(app: App, engine: SimpleNamespace) -> None:
    gid = await add_group(app, "Cine")
    await start_wizard(app)
    await app.send(SUPER_ID, "Primera versión")
    await app.click(SUPER_ID, "Regresar")
    assert "📝 <b>Nuevo mensaje</b> · 1/5" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Segunda versión")
    await app.send(SUPER_ID, "Web - https://example.com")
    await app.click(SUPER_ID, "Solo externos")
    await app.click(SUPER_ID, "Cine (0)")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "Regresar")
    assert "· 3/5" in app.last_text(SUPER_ID)
    assert "✅ Solo externos" in button_texts(app) and "✅ Cine (0)" in button_texts(app)
    await app.click(SUPER_ID, "Regresar")
    assert "· 2/5" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Sin botones")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "Difusión puntual")
    await app.click(SUPER_ID, "Regresar")
    assert "¿Cuándo se envía?" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "En rotación")
    await app.click(SUPER_ID, "Regresar")  # from step 5 to step 4
    assert "⏰ <b>¿Cuándo se envía?</b> · 4/5" in app.last_text(SUPER_ID) and await all_posts(app) == []
    await app.click(SUPER_ID, "Solo cuando lo envíe yo")
    await app.click(SUPER_ID, "6 h")
    post = await only_post(app)
    assert (post.name, post.buttons, post.targets) == ("Segunda versión", [], ["ext", f"g{gid}"])
    assert (post.mode, post.delete_after) == (SchedMode.MANUAL, 360)


async def test_wizard_stale_buttons_unsupported_content_and_cancel(app: App, engine: SimpleNamespace) -> None:
    await start_wizard(app)
    await app.press(SUPER_ID, PwCB(a="mode", v=0).pack())  # a button of another step
    await app.press(SUPER_ID, PwCB(a="tg", t="own").pack())
    await app.press(SUPER_ID, PwCB(a="del", v=60).pack())
    assert answers(app)[-3:] == [EXPIRED, EXPIRED, EXPIRED]
    await app.feed(sticker_update(app))
    assert "Ese tipo de mensaje no se puede distribuir" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Cancelar")
    assert "📝 <b>Mensajes</b>" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "Texto suelto")  # no wizard any more: this isn't a post
    assert await all_posts(app) == []


async def test_wizard_respects_the_post_limit(app: App, engine: SimpleNamespace) -> None:
    await add_clone(app, limit_posts=1)
    first = await add_post(app, bot_id=CLONE_ID)
    await started(app, OWNER2_ID, bot_id=CLONE_ID)
    await open_menu(app, OWNER2_ID, "posts", bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "Nuevo mensaje", bot_id=CLONE_ID)
    assert "🔒 Esta red ya tiene el máximo de mensajes (1)" in answers(app)[-1]
    assert "Nuevo mensaje</b> · 1/5" not in app.last_text(OWNER2_ID)

    async with app.db() as s:  # a finished post doesn't count
        post = await s.get(Post, first)
        assert post is not None
        post.status = PostStatus.DONE
    await app.click(OWNER2_ID, "Nuevo mensaje", bot_id=CLONE_ID)
    assert "📝 <b>Nuevo mensaje</b> · 1/5" in app.last_text(OWNER2_ID)
    await app.send(OWNER2_ID, "Promo del clon", bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "Sin botones", bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "Continuar", bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "En rotación", bot_id=CLONE_ID)
    await add_post(app, bot_id=CLONE_ID, name="Otra")  # the limit is reached meanwhile: checked again at the end
    await app.click(OWNER2_ID, "1 día", bot_id=CLONE_ID)
    assert "máximo de mensajes (1)" in answers(app)[-1]
    assert [p.name for p in await all_posts(app)] == ["Promo Cine", "Otra"]


async def test_super_admin_managing_a_clone_creates_its_posts(app: App, engine: SimpleNamespace) -> None:
    await add_clone(app)
    await add_chat(app, -1009, "Canal del clon", 300, bot_id=CLONE_ID)
    main_post = await add_post(app, name="Del bot principal")
    await manage_clone(app)
    await open_menu(app, SUPER_ID, "posts")
    text = app.last_text(SUPER_ID)
    assert "🛠 Gestionando <b>@clon_cine_bot</b>" in text and "Del bot principal" not in text
    await open_menu(app, SUPER_ID, "post", main_post)  # the main bot's posts aren't this workspace's
    assert NOT_FOUND in answers(app)

    await app.click(SUPER_ID, "Nuevo mensaje")
    await app.feed(app.message_update(SUPER_ID, photo="ph_ws", caption="Promo del clon"))
    await app.click(SUPER_ID, "Sin botones")
    assert "👥 Lo recibirán: <b>1 chat</b> · 👤 300" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "En rotación")
    await app.click(SUPER_ID, "1 día")
    created = [p for p in await all_posts(app) if p.bot_id == CLONE_ID]
    assert len(created) == 1
    assert created[0].media == {str(MAIN_BOT_ID): "ph_ws"}  # the file id of the bot that received it
    text = app.last_text(SUPER_ID)
    assert text.startswith("🛠 Gestionando <b>@clon_cine_bot</b>") and "✅ Mensaje guardado" in text


async def test_wizard_never_widens_the_audience_when_its_group_is_deleted(app: App, engine: SimpleNamespace) -> None:
    await add_chat(app, -1001, "Cine HD", 1200)
    gid = await add_group(app, "Cine")
    await start_wizard(app)
    await app.send(SUPER_ID, "Solo para el grupo de canales")
    await app.click(SUPER_ID, "Sin botones")
    await app.click(SUPER_ID, "Cine (0)")
    await app.click(SUPER_ID, "Continuar")
    async with app.db() as s:  # the group of chats is deleted meanwhile
        group = await s.get(ChatGroup, gid)
        assert group is not None
        await s.delete(group)
    await app.click(SUPER_ID, "En rotación")
    await app.click(SUPER_ID, "1 día")
    text = app.last_text(SUPER_ID)
    assert text.startswith("⚠️ Elige al menos un destino.") and "· 3/5" in text
    assert await all_posts(app) == []
    assert button_texts(app)[:3] == ["⚪ Todos", "⚪ Solo propios", "⚪ Solo externos"]
    await app.click(SUPER_ID, "Solo propios")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "En rotación")
    await app.click(SUPER_ID, "1 día")
    assert (await only_post(app)).targets == ["own"]


# --------------------------------------------------------------------------- step 5: how long it stays published
@pytest.mark.parametrize(("choice", "minutes", "shown"), [
    ("1 h", 60, "a las 1 h de enviarse"), ("3 h", 180, "a las 3 h de enviarse"), ("6 h", 360, "a las 6 h de enviarse"),
    ("12 h", 720, "a las 12 h de enviarse"), ("1 día", 1440, "a las 24 h de enviarse"),
    ("2 días", 2880, "a las 48 h de enviarse"), ("No borrar", 0, "✖️ nunca"),
])
async def test_wizard_step_5_stores_each_choice(app: App, engine: SimpleNamespace, choice: str, minutes: int,
                                                shown: str) -> None:
    await to_step_5(app)
    await app.click(SUPER_ID, choice)
    post = await only_post(app)
    assert post.delete_after == minutes and post.mode == SchedMode.MANUAL
    text = app.last_text(SUPER_ID)
    assert text.startswith("✅ Mensaje guardado") and f"🗑 Borrado automático: {shown}</blockquote>" in text


async def test_wizard_step_5_preselects_the_default_of_the_network(app: App, engine: SimpleNamespace) -> None:
    await to_step_5(app, "En rotación")
    assert step_5_rows(app) == [["⚪ 1 h", "⚪ 3 h", "⚪ 6 h"], ["⚪ 12 h", "⚪ 1 día", "⚪ 2 días"], ["✅ No borrar"],
                                ["🔙 Regresar", "❌ Cancelar"]]  # no default stored: never
    for stored, rows in (
        (360, [["⚪ 1 h", "⚪ 3 h", "✅ 6 h"], ["⚪ 12 h", "⚪ 1 día", "⚪ 2 días"], ["⚪ No borrar"]]),
        (0, [["⚪ 1 h", "⚪ 3 h", "⚪ 6 h"], ["⚪ 12 h", "⚪ 1 día", "⚪ 2 días"], ["✅ No borrar"]]),
        # a default written with ✏️ Otro in the default options gets its own choice
        (2160, [["⚪ 1 h", "⚪ 3 h", "⚪ 6 h"], ["⚪ 12 h", "⚪ 1 día", "⚪ 2 días"], ["✅ 36 h", "⚪ No borrar"]]),
    ):
        await set_default_delete_after(app, stored)
        await app.click(SUPER_ID, "Regresar")
        await app.click(SUPER_ID, "En rotación")
        assert step_5_rows(app)[:-1] == rows, stored
    await app.press(SUPER_ID, PwCB(a="del", v=90).pack())  # not one of the choices
    assert answers(app)[-1] == EXPIRED and await all_posts(app) == []
    await app.click(SUPER_ID, "36 h")
    post = await only_post(app)
    assert (post.delete_after, post.pin, post.mode) == (2160, True, SchedMode.ROTATION)  # the other defaults apply


async def test_wizard_step_5_back_cancel_and_stray_input(app: App, engine: SimpleNamespace,
                                                         freq_screen: list[int]) -> None:
    gid = await add_group(app, "Cine")
    await start_wizard(app)
    await app.send(SUPER_ID, "Estreno del viernes")
    await app.send(SUPER_ID, "Web - https://example.com")
    await app.click(SUPER_ID, "Cine (0)")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "Con su propio horario")
    assert app.last_text(SUPER_ID) == STEP_5
    await app.send(SUPER_ID, "36 h")  # step 5 is answered with its buttons
    assert app.last_text(SUPER_ID) == "👇 Usa los botones de abajo.\n\n" + STEP_5
    await app.press(SUPER_ID, PwCB(a="mode", v=0).pack())  # a button of step 4
    assert answers(app)[-1] == EXPIRED and await all_posts(app) == [] and freq_screen == []

    await app.click(SUPER_ID, "Regresar")  # step 4 again, the answers kept
    assert "⏰ <b>¿Cuándo se envía?</b> · 4/5" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "En rotación")
    await app.click(SUPER_ID, "3 h")
    post = await only_post(app)
    assert (post.name, post.buttons, post.targets) == ("Estreno del viernes",
                                                        [[{"text": "Web", "url": "https://example.com"}]], [f"g{gid}"])
    assert (post.mode, post.freq, post.delete_after) == (SchedMode.ROTATION, None, 180) and freq_screen == []

    await open_menu(app, SUPER_ID, "post_new")  # ❌ Cancelar at step 5: nothing is created
    await app.send(SUPER_ID, "Se cancela")
    await app.click(SUPER_ID, "Sin botones")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "Solo cuando lo envíe yo")
    await app.click(SUPER_ID, "Cancelar")
    assert "📝 <b>Mensajes</b>" in app.last_text(SUPER_ID)
    await app.press(SUPER_ID, PwCB(a="del", v=60).pack())  # its buttons don't work any more
    assert answers(app)[-1] == EXPIRED and [p.name for p in await all_posts(app)] == ["Estreno del viernes"]


async def test_wizard_once_mode_asks_the_date_then_step_5(app: App, engine: SimpleNamespace,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    await start_wizard(app)
    await app.send(SUPER_ID, "Gran estreno")
    await app.click(SUPER_ID, "Sin botones")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "Difusión puntual")
    assert "📢 <b>Difusión puntual</b> · 4/5" in app.last_text(SUPER_ID)
    day = (utcnow() + timedelta(days=2)).astimezone(MADRID)
    await app.send(SUPER_ID, day.strftime("%d/%m/%Y") + " 21:00")
    assert app.last_text(SUPER_ID) == STEP_5 and await all_posts(app) == []
    await app.click(SUPER_ID, "Regresar")  # back to step 4: the date is asked again with 📢 Difusión puntual
    assert "⏰ <b>¿Cuándo se envía?</b> · 4/5" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Difusión puntual")
    await app.send(SUPER_ID, day.strftime("%d/%m/%Y") + " 21:00")
    assert app.last_text(SUPER_ID) == STEP_5

    later = datetime(day.year, day.month, day.day, 21, 1, tzinfo=MADRID).astimezone(timezone.utc)
    monkeypatch.setattr("app.bot.routers.posts.utcnow", lambda: later)  # the date passes while step 5 is open
    await app.click(SUPER_ID, "12 h")
    text = app.last_text(SUPER_ID)
    assert text.startswith("⚠️ Esa fecha ya ha pasado.\n\n📢 <b>Difusión puntual</b> · 4/5") and await all_posts(app) == []
    nxt = day + timedelta(days=1)
    await app.send(SUPER_ID, nxt.strftime("%d/%m/%Y") + " 10:00")
    assert app.last_text(SUPER_ID) == STEP_5
    await app.click(SUPER_ID, "12 h")

    post = await only_post(app)
    expected = datetime(nxt.year, nxt.month, nxt.day, 10, 0, tzinfo=MADRID)
    assert (post.mode, post.send_at, post.next_send_at, post.delete_after) == (SchedMode.ONCE, expected, expected, 720)
    assert "🗑 Borrado automático: a las 12 h de enviarse" in app.last_text(SUPER_ID)


# --- 📢 Difusión puntual › 🚀 Ahora mismo ------------------------------------------------------------------------
async def to_date_step(app: App) -> None:
    """A text post without buttons, to everyone, in 📢 Difusión puntual: waiting for the date (step 4)."""
    await start_wizard(app)
    await app.send(SUPER_ID, "Aviso urgente")
    await app.click(SUPER_ID, "Sin botones")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "Difusión puntual")
    assert "📢 <b>Difusión puntual</b> · 4/5" in app.last_text(SUPER_ID)
    assert "🚀 Ahora mismo" in button_texts(app)


async def all_runs(app: App) -> list[Run]:
    async with app.db() as s:
        return list((await s.execute(select(Run))).scalars())


async def test_wizard_send_right_now_creates_a_once_post_that_the_scheduler_sends_once(
        app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Scheduler, "_refresh_chats", AsyncMock())
    monkeypatch.setattr(Scheduler, "_summary", AsyncMock())
    pks = await make_chats(app, 2)
    before = utcnow()
    await to_date_step(app)
    button, _ = app.find_button(SUPER_ID, "Ahora mismo")
    assert button.get("style") == "success"
    await app.click(SUPER_ID, "Ahora mismo")
    assert app.last_text(SUPER_ID) == STEP_5 and await all_posts(app) == []  # created only after step 5
    await app.click(SUPER_ID, "No borrar")

    post = await only_post(app)
    assert post.mode == SchedMode.ONCE and post.status == PostStatus.ACTIVE and post.runs_count == 0
    assert post.send_at is not None and before <= post.send_at <= utcnow()
    assert post.next_send_at == post.send_at
    assert "⏰ Envío: 📢 Difusión puntual · " in app.last_text(SUPER_ID)

    await app.scheduler.tick(wait=True)
    async with app.db() as s:
        chats = list((await s.execute(select(Chat).where(Chat.id.in_(pks)))).scalars())
    assert len(chats) == 2
    for chat in chats:
        assert texts_in(app, chat.chat_id) == ["Aviso urgente"]
    post = await only_post(app)
    assert (post.status, post.next_send_at, post.runs_count) == (PostStatus.DONE, None, 1)
    [run] = await all_runs(app)
    assert run.post_id == post.id and run.sent == 2

    await app.scheduler.tick(wait=True)  # it is done: nothing more is sent
    assert len(await all_runs(app)) == 1
    for chat in chats:
        assert texts_in(app, chat.chat_id) == ["Aviso urgente"]


async def test_wizard_back_from_step_5_returns_to_the_date_step_after_send_right_now(app: App) -> None:
    await to_date_step(app)
    await app.click(SUPER_ID, "Ahora mismo")
    assert app.last_text(SUPER_ID) == STEP_5
    await app.click(SUPER_ID, "Regresar")  # back to step 4: the mode is asked again
    assert "⏰ <b>¿Cuándo se envía?</b> · 4/5" in app.last_text(SUPER_ID) and await all_posts(app) == []
    await app.click(SUPER_ID, "Difusión puntual")
    assert "📢 <b>Difusión puntual</b> · 4/5" in app.last_text(SUPER_ID) and "🚀 Ahora mismo" in button_texts(app)
    await app.click(SUPER_ID, "Ahora mismo")  # it can be chosen again
    assert app.last_text(SUPER_ID) == STEP_5


async def test_wizard_a_date_typed_after_send_right_now_replaces_it(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Scheduler, "_refresh_chats", AsyncMock())
    monkeypatch.setattr(Scheduler, "_summary", AsyncMock())
    await make_chats(app, 1)
    await to_date_step(app)
    await app.click(SUPER_ID, "Ahora mismo")
    await app.click(SUPER_ID, "Regresar")
    await app.click(SUPER_ID, "Difusión puntual")
    day = (utcnow() + timedelta(days=3)).astimezone(MADRID)
    await app.send(SUPER_ID, day.strftime("%d/%m/%Y") + " 20:30")
    assert app.last_text(SUPER_ID) == STEP_5
    await app.click(SUPER_ID, "No borrar")

    post = await only_post(app)
    expected = datetime(day.year, day.month, day.day, 20, 30, tzinfo=MADRID)
    assert post.mode == SchedMode.ONCE and post.send_at == expected and post.next_send_at == expected
    await app.scheduler.tick(wait=True)  # its date is in the future: it is not sent right now
    assert await all_runs(app) == [] and (await only_post(app)).status == PostStatus.ACTIVE
