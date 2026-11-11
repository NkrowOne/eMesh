"""Posts: the list, the detail panel and its actions (preview, send now, withdraw, update the published copies,
duplicate, pause / activate, delete), permissions and the rows of other networks. The engine is a stub here, so
its interface is monkeypatched (``engine`` fixture)."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.bot.routers.post_buttons import PbCB
from app.bot.routers.posts import PoCB, PwCB
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import BotUser, ChatOrigin, Delivery, DeliveryStatus, Post, PostStatus, Role, Run, SchedMode
from app.ui import fmt
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_posts_helpers import (  # noqa: F401 - fixtures
    CLONE_ID,
    NO_PERMISSION,
    NOT_FOUND,
    TZ,
    add_chat,
    add_clone,
    add_group,
    add_post,
    all_posts,
    answers,
    button_texts,
    engine_fixture,
    load,
    open_menu,
    started,
)

TWO_BUTTONS = [[{"text": "Web", "url": "https://example.com", "style": "success"}],
               [{"text": "Código", "copy": "PROMO10"}]]


async def open_post(app: App, post_id: int, user_id: int = SUPER_ID) -> str:
    await started(app, user_id)
    await open_menu(app, user_id, "post", post_id)
    return app.last_text(user_id)


# --------------------------------------------------------------------------- list
async def test_list_describes_posts_and_puts_finished_ones_last(app: App, engine: SimpleNamespace) -> None:
    gid = await add_group(app, "Cine")
    await add_post(app, name="Vieja", status=PostStatus.DONE, mode=SchedMode.ONCE, send_at=utcnow() - timedelta(days=1))
    await add_post(app, name="Promo <Cine>", runs_count=12, kind="photo", media={str(MAIN_BOT_ID): "ph"},
                   mode=SchedMode.MANUAL)
    own = await add_post(app, name="Horario", mode=SchedMode.OWN, targets=["own", f"g{gid}"],
                         freq={"mode": "interval", "every": 120, "window": "", "days": "0123456"})
    await add_post(app, name="Pausado", status=PostStatus.PAUSED, targets=[])
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "posts")
    text = app.last_text(SUPER_ID)
    nxt = fmt.dt((await load(app, Post, own)).next_send_at, TZ)
    assert text.startswith("📝 <b>Mensajes</b>\n⏰ con horario · 📢 puntual · ✋ manual\n\n1. ")
    assert "rotación" not in text and "🔁" not in text
    assert "1. ▶️ ✋ <b>Promo &lt;Cine&gt;</b> · 🖼\n   └🎯 Todos · 📤 12 envíos" in text
    assert f"2. ▶️ ⏰ <b>Horario</b> · 📝\n   └🎯 Propios, Cine · 📅 {nxt}" in text
    assert "3. ⏸ ⏰ <b>Pausado</b> · 📝\n   └🎯 ⚠️ nadie · 📤 0 envíos" in text  # paused: no next send
    assert "4. ✅ 📢 <b>Vieja</b> · 📝" in text  # finished posts last
    assert button_texts(app) == ["#1 Promo <Cine>", "#2 Horario", "#3 Pausado", "#4 Vieja", "➕ Nuevo mensaje",
                                 "⚙️ Opciones por defecto", "🔙 Regresar"]
    new, _ = app.find_button(SUPER_ID, "Nuevo mensaje")
    assert new.get("style") == "success"
    await app.click(SUPER_ID, "#2 Horario")
    assert "📝 <b>Horario</b>" in app.last_text(SUPER_ID)


async def test_list_pages_and_empty_list(app: App, engine: SimpleNamespace) -> None:
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "posts")
    assert "📭 Todavía no hay mensajes" in app.last_text(SUPER_ID)
    for i in range(12):
        await add_post(app, name=f"Mensaje {i + 1}")
    await open_menu(app, SUPER_ID, "posts")
    assert "📄 Página 1 de 2" in app.last_text(SUPER_ID) and "10. ▶️" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Siguiente")
    text = app.last_text(SUPER_ID)
    assert "11. ▶️ ⏰ <b>Mensaje 11</b>" in text and "📄 Página 2 de 2" in text and "\n1. ▶️" not in text
    assert "#12 Mensaje 12" in button_texts(app) and "⬅️ Anterior" in button_texts(app)


# --------------------------------------------------------------------------- detail
async def test_detail_panel(app: App, engine: SimpleNamespace) -> None:
    await add_chat(app, -1001, "Cine HD", 1200)
    await add_chat(app, -1002, "Series Club", 800, origin=ChatOrigin.EXTERNAL)
    today = utcnow().astimezone(fmt.zone(TZ)).date()
    last = utcnow() - timedelta(hours=1)
    pid = await add_post(app, buttons=TWO_BUTTONS, runs_count=12, sent_count=340, last_sent_at=last, pin=True,
                         starts_on=today - timedelta(days=5), ends_on=today + timedelta(days=30),
                         mode=SchedMode.MANUAL)
    text = await open_post(app, pid)
    for expected in (
        "📝 <b>Promo Cine</b>",
        "📌 Estado: ▶️ Activo",
        "🧩 Tipo: 📝 Texto · 🔘 2 botones",
        "🎯 Destino: 🌐 Todos → 2 chats (👤 2,000)",
        "⏰ Envío: ✋ Manual\n   └ Solo se envía al pulsar 🚀 Enviar ahora.",
        f"📆 Campaña: del {(today - timedelta(days=5)):%d/%m/%Y} al {(today + timedelta(days=30)):%d/%m/%Y}",
        f"📤 Enviado: 12 veces · 340 entregas · último {fmt.dt(last, TZ)}",
        "<blockquote expandable>⚙️ <b>Opciones</b>\n📌 Fijar: ✅\n🔕 Sin sonido: ✖️\n🛡 Proteger contenido: ✖️\n"
        "🔗 Vista previa de enlaces: ✖️\n♻️ Borrar su envío anterior: ✅\n🗑 Borrado automático: ✖️ nunca</blockquote>",
    ):
        assert expected in text, expected
    assert "Próximo envío" not in text and "Publicado ahora" not in text
    assert button_texts(app) == ["👁 Vista previa", "🚀 Enviar ahora", "✏️ Contenido", "🔘 Botones", "🎯 Destino",
                                 "⏰ Programación", "⚙️ Opciones", "🧬 Duplicar", "⏸ Pausar", "🗑 Eliminar",
                                 "🔙 Regresar"]
    for label, screen in (("Contenido", "post_content"), ("Botones", "post_buttons"), ("Destino", "post_targets"),
                          ("Programación", "post_sched"), ("Opciones", "post_opts")):
        button, _ = app.find_button(SUPER_ID, label)
        assert button["callback_data"] == MenuCB(screen=screen, arg=pid).pack()
    delete, _ = app.find_button(SUPER_ID, "Eliminar")
    assert delete.get("style") == "danger"

    engine.live = 23  # copies published right now: the actions on them appear
    text = await open_post(app, pid)
    assert "🟢 Publicado ahora en: <b>23 chats</b>" in text
    assert button_texts(app)[8:10] == ["🔄 Actualizar publicados (23)", "🔚 Retirar (23)"]


async def test_detail_of_own_and_once_posts(app: App, engine: SimpleNamespace) -> None:
    own = await add_post(app, mode=SchedMode.OWN, freq={"mode": "interval", "every": 120, "window": "",
                                                        "days": "0123456"})
    when = utcnow() + timedelta(days=2)
    once = await add_post(app, name="Una vez", kind="photo", text=None, media={str(MAIN_BOT_ID): "ph"},
                          mode=SchedMode.ONCE, send_at=when, status=PostStatus.PAUSED, targets=[], spoiler=True)
    text = await open_post(app, own)
    nxt = (await load(app, Post, own)).next_send_at
    assert nxt is not None
    assert "⏰ Envío: ⏰ Horario propio · cada 2 h\n   └ A cada hora de su horario se envía a todos sus chats." in text
    assert f"📅 Próximo envío: <b>{fmt.dt(nxt, TZ)}</b>" in text

    text = await open_post(app, once)
    assert "📌 Estado: ⏸ Pausado" in text and "🧩 Tipo: 🖼 Foto · sin botones" in text
    assert "🎯 Destino: ⚠️ ninguno, no se envía a nadie" in text
    assert f"⏰ Envío: 📢 Difusión puntual · {fmt.dt(when, TZ)}" in text and "📅 Próximo envío: <b>—</b>" in text
    assert "🔼 Texto encima del multimedia: ✖️\n🫣 Spoiler: ✅" in text and "Vista previa de enlaces" not in text
    activate, _ = app.find_button(SUPER_ID, "Activar")
    assert activate["text"] == "▶️ Activar" and activate.get("style") == "success"


# --------------------------------------------------------------------------- preview
async def test_preview_sends_the_real_post_and_the_panel_again(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, buttons=TWO_BUTTONS)
    await open_post(app, pid)
    before = len(app.fake.calls_of("sendMessage", chat_id=SUPER_ID))
    await app.click(SUPER_ID, "Vista previa")
    sent = app.fake.calls_of("sendMessage", chat_id=SUPER_ID)[before:]
    assert sent[0].params["text"] == "<b>Promo</b> de cine"
    rows = sent[0].params["reply_markup"]["inline_keyboard"]
    assert rows[0][0]["text"] == "Web" and rows[0][0]["url"] == "https://example.com"
    assert rows[0][0]["style"] == "success" and rows[1][0]["copy_text"] == {"text": "PROMO10"}
    assert "📝 <b>Promo Cine</b>" in sent[1].params["text"]  # the panel again, below the preview
    assert app.fake.calls_of("deleteMessage", chat_id=SUPER_ID)  # the old panel is gone


async def test_preview_of_media_and_its_errors(app: App, engine: SimpleNamespace) -> None:
    photo = await add_post(app, kind="photo", media={str(MAIN_BOT_ID): "ph_main"}, text="Foto")
    await open_post(app, photo)
    await app.click(SUPER_ID, "Vista previa")
    sent = app.fake.calls_of("sendPhoto", chat_id=SUPER_ID)
    assert sent and sent[-1].params["photo"] == "ph_main" and sent[-1].params["caption"] == "Foto"

    lost = await add_post(app, kind="photo", media={"424242": "ph_other"}, text="Perdida")  # no bot can get it
    await open_post(app, lost)
    await app.click(SUPER_ID, "Vista previa")
    assert answers(app)[-1] == "⚠️ No se ha podido obtener el archivo. Vuelve a enviar el mensaje."

    text_post = await add_post(app, text="Rechazado")
    app.fake.fail("sendMessage", when=lambda p: p.get("text") == "Rechazado")
    await open_post(app, text_post)
    await app.click(SUPER_ID, "Vista previa")
    assert answers(app)[-1] == "⚠️ No se ha podido enviar la vista previa. Inténtalo de nuevo."


# --------------------------------------------------------------------------- send now
async def test_send_now(app: App, engine: SimpleNamespace) -> None:
    await add_chat(app, -1001, "Cine HD", 1200)
    await add_chat(app, -1002, "Series Club", 800, origin=ChatOrigin.EXTERNAL)
    paused = await add_chat(app, -1003, "Externo pausado", 50, origin=ChatOrigin.EXTERNAL, owner_paused=True)
    gid = await add_group(app, "Pausados", (paused,))
    pid = await add_post(app)
    nobody = await add_post(app, name="Sin destino", targets=[f"g{gid}"], status=PostStatus.PAUSED)

    await open_post(app, pid)
    engine.busy = True
    await app.click(SUPER_ID, "Enviar ahora")
    assert answers(app)[-1] == "⏳ Este mensaje se está enviando ahora mismo. Espera a que termine."
    engine.busy = False
    await app.click(SUPER_ID, "Enviar ahora")
    text = app.last_text(SUPER_ID)
    assert "🚀 <b>Promo Cine</b>\n\nSe enviará ahora a <b>2 chats</b> (👤 2,000)." in text
    assert button_texts(app) == ["✅ Enviar", "❌ No"]
    await app.click(SUPER_ID, "No")
    assert "📝 <b>Promo Cine</b>" in app.last_text(SUPER_ID) and engine.sent == []
    await app.click(SUPER_ID, "Enviar ahora")
    await app.click(SUPER_ID, "✅ Enviar")
    assert engine.sent == [(pid, SUPER_ID)] and answers(app)[-1] == "🚀 Enviando…"
    assert "📝 <b>Promo Cine</b>" in app.last_text(SUPER_ID)

    engine.run_id = None  # the engine found nobody when the run started
    await app.press(SUPER_ID, PoCB(a="send_ok", id=pid).pack())
    assert answers(app)[-1] == ("⚠️ Ahora mismo ningún chat de su 🎯 Destino puede recibirlo: no hay ninguno o están pausados, "
                                "pendientes o sin permisos. Revisa su 🎯 Destino o 📣 Canales y grupos.")

    await open_post(app, nobody)  # targets only a paused external chat
    await app.click(SUPER_ID, "Enviar ahora")
    assert answers(app)[-1] == ("⚠️ Ahora mismo ningún chat de su 🎯 Destino puede recibirlo: no hay ninguno o están pausados, "
                                "pendientes o sin permisos. Revisa su 🎯 Destino o 📣 Canales y grupos.")
    assert len(engine.sent) == 2


# --------------------------------------------------------------------------- withdraw / update published
async def test_withdraw_and_update_published_copies(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app)
    await open_post(app, pid)
    await app.press(SUPER_ID, PoCB(a="ret", id=pid).pack())  # nothing published: no button, and no action
    assert answers(app)[-1] == "ℹ️ Ahora mismo no está publicado en ningún chat."

    engine.live = 3
    await open_post(app, pid)
    await app.click(SUPER_ID, "Retirar (3)")
    text = app.last_text(SUPER_ID)
    assert "🔚 Se borrará <b>Promo Cine</b> de donde está publicado ahora: <b>3 chats</b>." in text
    engine.busy = True
    await app.click(SUPER_ID, "🔚 Retirar")
    assert answers(app)[-1].startswith("⏳") and engine.retired == []
    engine.busy = False
    await app.click(SUPER_ID, "🔚 Retirar")
    await app.wait_for(lambda: engine.retired)
    assert engine.retired == [pid] and answers(app)[-1] == "🔚 Retirando…"

    await app.click(SUPER_ID, "Actualizar publicados (3)")
    text = app.last_text(SUPER_ID)
    assert "los botones actuales de <b>Promo Cine</b> a lo ya publicado: <b>3 copias</b>" in text
    await app.click(SUPER_ID, "🔄 Actualizar")
    await app.wait_for(lambda: engine.updated)
    assert engine.updated == [pid] and answers(app)[-1] == "🔄 Actualizando…"


# --------------------------------------------------------------------------- duplicate
async def test_duplicate_creates_a_paused_copy(app: App, engine: SimpleNamespace) -> None:
    gid = await add_group(app, "Cine")
    freq_value = {"mode": "times", "times": "10:00,22:00", "days": "01234"}
    pid = await add_post(app, kind="photo", media={str(MAIN_BOT_ID): "ph"}, buttons=TWO_BUTTONS,
                         targets=["own", f"g{gid}"], pin=True, spoiler=True, delete_after=60, mode=SchedMode.OWN,
                         freq=freq_value, runs_count=5, sent_count=50)
    await open_post(app, pid)
    await app.click(SUPER_ID, "Duplicar")
    assert answers(app)[-1] == "🧬 Copia creada en pausa: revísala y actívala."
    original, copy = await all_posts(app)
    assert copy.name == "Promo Cine (copia)" and copy.status == PostStatus.PAUSED and copy.next_send_at is None
    for name in ("kind", "text", "media", "media_name", "buttons", "targets", "mode", "freq", "pin", "spoiler",
                 "delete_after", "delete_previous", "silent", "protect"):
        assert getattr(copy, name) == getattr(original, name), name
    assert (copy.runs_count, copy.sent_count, copy.created_by) == (0, 0, SUPER_ID)
    text = app.last_text(SUPER_ID)
    assert "📝 <b>Promo Cine (copia)</b>" in text and "📌 Estado: ⏸ Pausado" in text
    assert original.status == PostStatus.ACTIVE

    long_name = await add_post(app, name="N" * 64)
    await open_post(app, long_name)
    await app.click(SUPER_ID, "Duplicar")
    newest = (await all_posts(app))[-1]
    assert len(newest.name) == 64 and newest.name.endswith("… (copia)")


# --------------------------------------------------------------------------- delete
async def test_delete_without_published_copies(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app)
    await open_post(app, pid)
    await app.click(SUPER_ID, "Eliminar")
    assert app.last_text(SUPER_ID) == "🗑 ¿Eliminar <b>Promo Cine</b>?"
    assert button_texts(app) == ["🗑 Sí, eliminar", "❌ No"]
    await app.click(SUPER_ID, "No")
    assert await load(app, Post, pid) is not None
    await app.click(SUPER_ID, "Eliminar")
    await app.click(SUPER_ID, "Sí, eliminar")
    assert await load(app, Post, pid) is None
    assert answers(app)[-1] == "🗑 Mensaje eliminado" and "📭 Todavía no hay mensajes" in app.last_text(SUPER_ID)


async def test_delete_only_the_post_keeps_the_published_copies(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app)
    delete_at = utcnow() + timedelta(hours=2)
    async with app.db() as s:
        run = Run(bot_id=MAIN_BOT_ID, post_id=pid, post_name="Promo Cine")
        s.add(run)
        await s.flush()
        s.add(Delivery(run_id=run.id, bot_id=MAIN_BOT_ID, post_id=pid, chat_id=-1001, message_id=7,
                       status=DeliveryStatus.SENT, sent_at=utcnow(), delete_at=delete_at))
    engine.live = 2
    await open_post(app, pid)
    await app.click(SUPER_ID, "Eliminar")
    text = app.last_text(SUPER_ID)
    assert "🟢 Ahora está publicado en <b>2 chats</b>" in text
    assert button_texts(app) == ["🗑 Eliminar y retirar lo publicado (2)", "🗑 Eliminar solo el mensaje", "❌ No"]
    engine.busy = True
    await app.click(SUPER_ID, "Eliminar solo el mensaje")
    assert answers(app)[-1].startswith("⏳") and await load(app, Post, pid) is not None
    engine.busy = False
    await app.click(SUPER_ID, "Eliminar solo el mensaje")
    assert await load(app, Post, pid) is None and engine.retired == []
    async with app.db() as s:
        delivery = (await s.execute(select(Delivery))).scalars().one()
        assert delivery.post_id is None and delivery.delete_at == delete_at  # its auto delete still happens


async def test_delete_and_withdraw_in_the_background(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, mode=SchedMode.OWN, freq={"mode": "interval", "every": 60, "days": "0123456"})
    await add_post(app, name="Otro mensaje")
    engine.live = 2
    await open_post(app, pid)
    await app.click(SUPER_ID, "Eliminar")
    await app.click(SUPER_ID, "Eliminar y retirar lo publicado (2)")
    assert answers(app)[-1] == "🗑 Eliminando: se está retirando lo publicado…"
    text = app.last_text(SUPER_ID)
    assert "Otro mensaje" in text and "Promo Cine" not in text  # hidden while it is withdrawn
    await app.wait_for(lambda: engine.retired)
    assert engine.retired == [pid]

    async def gone() -> bool:
        return await load(app, Post, pid) is None

    await app.wait_for(gone)


# --------------------------------------------------------------------------- pause / activate
async def test_pause_and_activate(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, mode=SchedMode.OWN, freq={"mode": "interval", "every": 60, "days": "0123456"})
    await open_post(app, pid)
    await app.click(SUPER_ID, "Pausar")
    post = await load(app, Post, pid)
    assert post.status == PostStatus.PAUSED and post.next_send_at is None and engine.woke == 1
    assert answers(app)[-1] == "⏸ Mensaje pausado" and "📌 Estado: ⏸ Pausado" in app.last_text(SUPER_ID)
    await app.press(SUPER_ID, PoCB(a="pause", id=pid).pack())  # a double tap changes nothing
    assert engine.woke == 1
    await app.click(SUPER_ID, "Activar")
    post = await load(app, Post, pid)
    assert post.status == PostStatus.ACTIVE and post.next_send_at is not None and engine.woke == 2
    assert answers(app)[-1] == "▶️ Mensaje activado" and "⏸ Pausar" in button_texts(app)
    await app.press(SUPER_ID, PoCB(a="play", id=pid).pack())
    assert engine.woke == 2


async def test_activating_a_finished_once_post_asks_a_new_date(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app, name="Una vez", mode=SchedMode.ONCE, send_at=utcnow() - timedelta(hours=2),
                         status=PostStatus.DONE)
    text = await open_post(app, pid)
    assert "📌 Estado: ✅ Terminado" in text
    await app.click(SUPER_ID, "Activar")
    assert "📆 <b>Nueva fecha</b> · Una vez" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "ayer")
    assert "Escribe la fecha y la hora así" in app.last_text(SUPER_ID)
    when = (utcnow() + timedelta(days=1)).astimezone(fmt.zone(TZ))
    await app.send(SUPER_ID, when.strftime("%d/%m/%Y") + " 10:00")
    post = await load(app, Post, pid)
    assert post.status == PostStatus.ACTIVE and post.send_at is not None and post.next_send_at == post.send_at
    assert app.last_text(SUPER_ID).startswith("▶️ Mensaje activado\n\n📝 <b>Una vez</b>") and engine.woke == 1

    ended = await add_post(app, name="Campaña vieja", status=PostStatus.DONE,
                           ends_on=utcnow().date() - timedelta(days=2))
    await open_post(app, ended)
    await app.click(SUPER_ID, "Activar")
    assert "Su campaña ya terminó" in answers(app)[-1]
    assert (await load(app, Post, ended)).status == PostStatus.DONE


async def test_limit_when_duplicating_or_reactivating(app: App, engine: SimpleNamespace) -> None:
    await add_clone(app, limit_posts=1)
    active = await add_post(app, bot_id=CLONE_ID)
    done = await add_post(app, bot_id=CLONE_ID, name="Terminado", status=PostStatus.DONE)
    await started(app, OWNER2_ID, bot_id=CLONE_ID)
    await open_menu(app, OWNER2_ID, "post", active, bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "Duplicar", bot_id=CLONE_ID)
    assert "máximo de mensajes (1)" in answers(app)[-1]
    await open_menu(app, OWNER2_ID, "post", done, bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "Activar", bot_id=CLONE_ID)
    assert "máximo de mensajes (1)" in answers(app)[-1]
    assert len(await all_posts(app)) == 2 and (await load(app, Post, done)).status == PostStatus.DONE


# --------------------------------------------------------------------------- permissions
async def test_partner_cannot_open_or_change_posts(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app)
    await started(app, USER_ID)
    forged = [
        MenuCB(screen="posts"), MenuCB(screen="post", arg=pid), MenuCB(screen="post_new"),
        MenuCB(screen="post_content", arg=pid), MenuCB(screen="post_buttons", arg=pid),
        MenuCB(screen="post_targets", arg=pid), MenuCB(screen="post_sched", arg=pid),
        MenuCB(screen="post_opts", arg=pid), MenuCB(screen="post_defaults"),
        PwCB(a="start"), PwCB(a="mode", v=0), PwCB(a="del", v=60), PoCB(a="pause", id=pid), PoCB(a="send_ok", id=pid),
        PoCB(a="del_one", id=pid), PoCB(a="del_all", id=pid), PoCB(a="dup", id=pid), PoCB(a="tg", id=pid, t="own"),
        PoCB(a="mode", id=pid, v=2), PoCB(a="opt", id=pid, v=0), PoCB(a="opt", id=0, v=0), PoCB(a="ad", id=0, v=60),
        PoCB(a="cname", id=pid), PoCB(a="nomedia_ok", id=pid), PoCB(a="ret_ok", id=pid), PoCB(a="upd_ok", id=pid),
        PoCB(a="prev", id=pid), PbCB(a="add", id=pid), PbCB(a="del", id=pid), PbCB(a="clear_ok", id=pid),
        PbCB(a="mv", id=pid, v=1), PbCB(a="bulk", id=pid), PbCB(a="acol", id=pid, v=1),
    ]
    for data in forged:
        await app.press(USER_ID, data.pack())
    assert answers(app).count(NO_PERMISSION) == len(forged)
    post = await load(app, Post, pid)
    assert (post.status, post.targets, post.mode, post.pin, post.name) == (PostStatus.ACTIVE, ["all"],
                                                                           SchedMode.OWN, False, "Promo Cine")
    assert engine.sent == [] and engine.retired == [] and engine.woke == 0 and len(await all_posts(app)) == 1
    assert (await load(app, BotRecord, MAIN_BOT_ID)).post_defaults == {}
    assert not any("Promo Cine" in str(c.params.get("text") or "") for c in app.panels(USER_ID))
    assert not app.fake.calls_of("sendMessage", chat_id=USER_ID, text="<b>Promo</b> de cine")  # no preview

    async with app.db() as s:  # a promoted admin manages the posts
        bu = await s.get(BotUser, (MAIN_BOT_ID, USER_ID))
        assert bu is not None
        bu.role = Role.ADMIN
    await open_menu(app, USER_ID, "posts")
    assert "Promo Cine" in app.last_text(USER_ID)
    await app.click(USER_ID, "Nuevo mensaje")
    async with app.db() as s:  # ...until demoted in the middle of the wizard
        bu = await s.get(BotUser, (MAIN_BOT_ID, USER_ID))
        assert bu is not None
        bu.role = Role.USER
    await app.send(USER_ID, "Mensaje coladizo")
    assert app.last_text(USER_ID) == NO_PERMISSION and len(await all_posts(app)) == 1


async def test_posts_of_other_networks_are_not_reachable(app: App, engine: SimpleNamespace) -> None:
    await add_clone(app)
    other = await add_post(app, bot_id=CLONE_ID, name="Del clon")
    await started(app, SUPER_ID, OWNER2_ID)
    await open_menu(app, SUPER_ID, "post", other)
    assert NOT_FOUND in answers(app) and "📝 <b>Mensajes</b>" in app.last_text(SUPER_ID)
    for data in (PoCB(a="pause", id=other), PoCB(a="tg", id=other, t="own"), PoCB(a="del_one", id=other),
                 PoCB(a="opt", id=other, v=0), PbCB(a="clear_ok", id=other)):
        await app.press(SUPER_ID, data.pack())
    post = await load(app, Post, other)
    assert post is not None and (post.status, post.targets, post.pin) == (PostStatus.ACTIVE, ["all"], False)

    mine = await add_post(app, name="Del principal")  # the clone's owner can't reach the main bot's posts either
    await open_menu(app, OWNER2_ID, "post", mine, bot_id=CLONE_ID)
    await app.press(OWNER2_ID, PoCB(a="pause", id=mine).pack(), bot_id=CLONE_ID)
    assert answers(app).count(NOT_FOUND) >= 7
    assert (await load(app, Post, mine)).status == PostStatus.ACTIVE


async def test_hub_main_bot_has_no_posts(app: App, engine: SimpleNamespace) -> None:
    pid = await add_post(app)
    app.settings.MAIN_BOT_MODE = "hub"
    await started(app, SUPER_ID)
    for data in (MenuCB(screen="posts"), MenuCB(screen="post_new"), PwCB(a="start"), PoCB(a="pause", id=pid)):
        await app.press(SUPER_ID, data.pack())
        assert app.last_text(SUPER_ID).startswith("🕸 <b>eMesh")  # the home screen of the hub
    assert (await load(app, Post, pid)).status == PostStatus.ACTIVE


async def test_counts_use_the_singular_for_one(app: App, engine: SimpleNamespace) -> None:
    await add_chat(app, -1001, "Cine HD", 1200)
    pid = await add_post(app, buttons=[[{"text": "Web", "url": "https://example.com"}]], runs_count=1, sent_count=1,
                         last_sent_at=utcnow(), mode=SchedMode.MANUAL)
    engine.live = 1
    text = await open_post(app, pid)
    assert "🧩 Tipo: 📝 Texto · 🔘 1 botón" in text and "🎯 Destino: 🌐 Todos → 1 chat (👤 1,200)" in text
    assert "📤 Enviado: 1 vez · 1 entrega · último" in text and "🟢 Publicado ahora en: <b>1 chat</b>" in text
    await open_menu(app, SUPER_ID, "posts")
    assert "└🎯 Todos · 📤 1 envío" in app.last_text(SUPER_ID)
