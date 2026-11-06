"""Clones module: the 👑 panel of the super admins (platform numbers, clones list and search, a clone's page with
🛠 Gestionar, enable / disable, limits, DM to the owner, activity and delete, ⚙️ Plataforma, 📢 Aviso a los dueños,
📄 Errores) and its permissions."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from app.bot.routers.clone import CloneCB
from app.bot.routers.panel import PanelCB, parse_limits
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import (
    BotStatus,
    BotUser,
    Chat,
    ChatOrigin,
    ChatStatus,
    Event,
    EventKind,
    Post,
    PostStatus,
    Run,
)
from app.services import clones, limits, logbook
from app.ui import screens
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App

CLONE_ID = 6_200_000_001
CLONE_USERNAME = "pepe_cine_bot"


def answer_text(app: App) -> str:
    call = app.fake.last("answerCallbackQuery")
    return str(call.params.get("text", "")) if call else ""


def button_texts(app: App, chat_id: int) -> list[str]:
    return [b["text"] for b in app.buttons(app.last_panel(chat_id))]


def dms(app: App, chat_id: int) -> list[str]:
    return [str(c.params.get("text", "")) for c in app.fake.calls_of("sendMessage", chat_id=chat_id)
            if c.token == app.settings.BOT_TOKEN]


async def get_bot(app: App, bot_id: int = CLONE_ID) -> BotRecord | None:
    async with app.db() as s:
        return await s.get(BotRecord, bot_id)


async def make_bot(app: App, bot_id: int, username: str, owner_id: int, *, status: str = BotStatus.ACTIVE,
                   reason: str | None = None, minutes_ago: int = 0) -> None:
    """A clone row straight in the database (not running)."""
    async with app.db() as s:
        s.add(BotRecord(id=bot_id, username=username, name=username, token_enc="", owner_id=owner_id, status=status,
                        status_reason=reason, created_at=utcnow() - timedelta(minutes=minutes_ago)))


async def add_rows(app: App, *rows: Any) -> None:
    async with app.db() as s:
        s.add_all(rows)


def chat(bot_id: int, chat_id: int, title: str, members: int, **kw: Any) -> Chat:
    values: dict[str, Any] = {"status": ChatStatus.APPROVED, "rights_ok": True, "origin": ChatOrigin.OWN}
    values.update(kw)
    return Chat(bot_id=bot_id, chat_id=chat_id, title=title, members=members, **values)


async def open_bot(app: App, bot_id: int = CLONE_ID) -> str:
    await app.press(SUPER_ID, PanelCB(action="bot", id=bot_id).pack())
    return app.last_text(SUPER_ID)


# ------------------------------------------------------------------------- panel
async def test_panel_numbers(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_cine_bot", USER_ID)  # ✅
    await app.add_clone(CLONE_ID + 1, "clon_series_bot", OWNER2_ID)
    await app.manager.disable_bot(CLONE_ID + 1, reason=clones.REASON_OWNER)  # ⏸
    await make_bot(app, CLONE_ID + 2, "clon_espera_bot", OWNER2_ID, status=BotStatus.PENDING)  # ⏳
    await make_bot(app, CLONE_ID + 3, "clon_roto_bot", USER_ID, status=BotStatus.INVALID)  # ❌
    now = utcnow()
    await add_rows(
        app,
        chat(CLONE_ID, -1001, "Canal de Cine", 1200),
        chat(CLONE_ID, -1002, "Cine Clásico", 300, origin=ChatOrigin.EXTERNAL, owner_paused=True),
        chat(CLONE_ID, -1003, "Pausa vencida", 0, owner_paused=True, owner_paused_until=now - timedelta(hours=1)),
        chat(MAIN_BOT_ID, -1004, "Noticias", 500),
        chat(CLONE_ID, -1005, "Pendiente", 10, status=ChatStatus.PENDING),
        Post(bot_id=CLONE_ID, name="Promo Cine"), Post(bot_id=MAIN_BOT_ID, name="Noticias"),
        Post(bot_id=CLONE_ID, name="Vieja", status=PostStatus.DONE),
        Run(bot_id=CLONE_ID, post_name="Promo Cine", total=5, sent=5, status="done", started_at=now),
        Run(bot_id=CLONE_ID, post_name="Antigua", total=7, sent=7, status="done", started_at=now - timedelta(days=2)),
    )
    await app.send(USER_ID, "/start")
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    await app.send(SUPER_ID, "/start")
    await app.press(SUPER_ID, MenuCB(screen="panel").pack())
    text = app.last_text(SUPER_ID)
    assert "👑 <b>Panel de la plataforma</b>" in text
    assert "🤖 Bots: <b>4</b> (✅ 1 · ⏸ 1 · ⏳ 1 · ❌ 1)" in text
    assert "👥 Usuarios: <b>3</b>" in text
    assert "📣 Chats: <b>4</b> (👤 2,000) · ⏸ pausados por su dueño: 1" in text  # an expired pause doesn't count
    assert "📝 Mensajes activos: <b>2</b>" in text
    assert "📤 Últimas 24 h: 1 envíos · 5 entregas" in text
    assert "⚙️ Clonación: 🌐 Abierta" in text
    assert app.find_button(SUPER_ID, "Pendientes (1)")[0]["callback_data"] == PanelCB(action="bots", f=3).pack()
    for label in ("Clones", "Plataforma", "Aviso a los dueños", "Errores", "Regresar"):
        assert any(label in b for b in button_texts(app, SUPER_ID)), label


# --------------------------------------------------------------------- clones list
async def test_clones_list_pages_and_filters(app: App) -> None:
    await app.send(USER_ID, "/start")
    await app.send(OWNER2_ID, "/start")
    for i in range(12):  # clon11 is the newest: listed first
        await make_bot(app, CLONE_ID + i, f"clon{i:02d}_bot", USER_ID if i % 2 else OWNER2_ID,
                       status=BotStatus.PENDING if i == 3 else BotStatus.ACTIVE, minutes_ago=60 - i)
    await add_rows(app, chat(CLONE_ID + 11, -1001, "Canal de Cine", 900),
                   chat(CLONE_ID + 11, -1002, "Cine Clásico", 90, owner_paused=True), Post(bot_id=CLONE_ID + 11))
    await app.press(SUPER_ID, PanelCB(action="bots").pack())
    text = app.last_text(SUPER_ID)
    assert "🤖 <b>Clones</b> · 🌐 Todos: <b>12</b>" in text
    assert "1. ✅ @clon11_bot · 👤 @pepe\n   └📣 2 · 📝 1 · ⏸ 1" in text
    assert "2. ✅ @clon10_bot · 👤 @owner2\n   └📣 0 · 📝 0" in text
    assert "📄 Página 1 de 2" in text and "@clon01_bot" not in text
    assert "✅ Todos" in button_texts(app, SUPER_ID)

    await app.click(SUPER_ID, "Siguiente")
    text = app.last_text(SUPER_ID)
    assert "11. ✅ @clon01_bot" in text and "12. ✅ @clon00_bot" in text and "@clon11_bot" not in text

    await app.click(SUPER_ID, "Pendientes")
    text = app.last_text(SUPER_ID)
    assert "⏳ Pendientes: <b>1</b>" in text and "1. ⏳ @clon03_bot" in text and "@clon11_bot" not in text
    assert "✅ Pendientes" in button_texts(app, SUPER_ID)
    # a clone's page goes back to the list it came from
    await app.click(SUPER_ID, "#1 @clon03_bot")
    assert "📌 Estado: ⏳ Pendiente de aprobación" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Regresar")
    assert "⏳ Pendientes: <b>1</b>" in app.last_text(SUPER_ID)

    await app.click(SUPER_ID, "Token no válido")
    assert "📭 No hay ningún bot aquí." in app.last_text(SUPER_ID)


async def test_clones_search(app: App) -> None:
    await app.send(OWNER2_ID, "/start")
    await make_bot(app, CLONE_ID, "clon_cine_bot", OWNER2_ID)
    await make_bot(app, CLONE_ID + 1, "clon_series_bot", OWNER2_ID)
    await make_bot(app, CLONE_ID + 2, "clonXcine_bot", USER_ID)
    await app.press(SUPER_ID, PanelCB(action="bots").pack())
    await app.click(SUPER_ID, "Buscar")
    assert "Buscar un bot" in app.last_text(SUPER_ID)

    await app.send(SUPER_ID, "@nada_bot")
    assert "No se ha encontrado ningún bot con «@nada_bot»" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "@clon_cine_bot")  # still searching: one result opens its page
    assert "🤖 <b>@clon_cine_bot</b>" in app.last_text(SUPER_ID)

    await app.press(SUPER_ID, PanelCB(action="find").pack())
    await app.send(SUPER_ID, "clon_")  # part of a username ("_" is not a wildcard)
    text = app.last_text(SUPER_ID)
    assert "Resultados de «clon_»" in text and "@clon_cine_bot" in text and "@clon_series_bot" in text
    assert "clonXcine_bot" not in text

    await app.press(SUPER_ID, PanelCB(action="find").pack())
    await app.send(SUPER_ID, "@owner2")  # the owner's @username
    text = app.last_text(SUPER_ID)
    assert "@clon_cine_bot" in text and "@clon_series_bot" in text and "clonXcine_bot" not in text
    await app.click(SUPER_ID, "@clon_series_bot")
    assert "🤖 <b>@clon_series_bot</b>" in app.last_text(SUPER_ID)

    await app.press(SUPER_ID, PanelCB(action="find").pack())
    await app.send(SUPER_ID, str(CLONE_ID + 2))  # an id
    assert "🤖 <b>@clonXcine_bot</b>" in app.last_text(SUPER_ID)


# ---------------------------------------------------------------------- clone page
async def test_clone_page(app: App) -> None:
    await app.send(USER_ID, "/start")
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    now = utcnow()
    await add_rows(
        app,
        chat(CLONE_ID, -1001, "Canal de Cine", 1000),
        chat(CLONE_ID, -1002, "Cine <Clásico>", 500, origin=ChatOrigin.EXTERNAL, owner_paused=True),
        chat(CLONE_ID, -1003, "Pendiente", 10, status=ChatStatus.PENDING),
        Post(bot_id=CLONE_ID, name="Promo Cine"), Post(bot_id=CLONE_ID, name="Estrenos"),
        Run(bot_id=CLONE_ID, post_name="Promo Cine", total=9, sent=7, failed=2, status="done", started_at=now),
    )
    text = await open_bot(app)
    assert f"🤖 <b>@{CLONE_USERNAME}</b> ({CLONE_USERNAME})\n🆔 <code>{CLONE_ID}</code>" in text
    assert f"👤 Dueño: @pepe (<code>{USER_ID}</code>)" in text
    assert "📌 Estado: ✅ Activo" in text
    assert "📣 Chats: <b>2</b> (🏠 1 · 🤝 1) · 👤 1,500" in text
    assert "⏸ Pausados por su dueño: 1 · ⏳ Pendientes: 1" in text
    assert "📝 Mensajes activos: <b>2</b> · ⏰ cada 4 h" in text
    assert "📤 Últimas 24 h: 1 envíos · 7 entregas · 2 fallos" in text
    assert "🔒 Límites: sin límites (predeterminado)" in text
    buttons = button_texts(app, SUPER_ID)
    for label in ("Gestionar", "Desactivar", "Límites", "Escribir al dueño", "Actividad", "Errores", "Eliminar",
                  "Regresar"):
        assert any(label in b for b in buttons), label
    assert not any("Aprobar" in b for b in buttons)

    # a pending clone is approved or rejected instead
    await make_bot(app, CLONE_ID + 1, "clon_espera_bot", USER_ID, status=BotStatus.PENDING)
    await open_bot(app, CLONE_ID + 1)
    buttons = button_texts(app, SUPER_ID)
    assert "✅ Aprobar" in buttons and "❌ Rechazar" in buttons
    assert not any("Activar" in b for b in buttons)
    # the screen can be opened by name too
    await app.press(SUPER_ID, MenuCB(screen="panel_bot", arg=CLONE_ID).pack())
    assert f"🤖 <b>@{CLONE_USERNAME}</b>" in app.last_text(SUPER_ID)


async def test_manage_a_clone_from_the_main_bot(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    seen: list[tuple[int, bool]] = []
    home = screens._SCREENS["home"]  # noqa: SLF001

    async def spy_home(event: Any, ctx: Any, session: Any, arg: int = 0, **kw: Any) -> None:
        seen.append((ctx.ws_id, ctx.in_ws))
        await home(event, ctx, session, arg=arg, **kw)

    monkeypatch.setitem(screens._SCREENS, "home", spy_home)  # noqa: SLF001
    await app.send(SUPER_ID, "/start")
    await open_bot(app)
    await app.click(SUPER_ID, "Gestionar")
    async with app.db() as s:
        assert (await s.get(BotUser, (MAIN_BOT_ID, SUPER_ID))).ws_bot_id == CLONE_ID
    assert seen[-1] == (CLONE_ID, True)  # the home of the clone's network, right away
    assert f"🛠 Gestionando <b>@{CLONE_USERNAME}</b>" in app.last_text(SUPER_ID)

    await app.send(SUPER_ID, "/start")
    assert seen[-1] == (CLONE_ID, True)
    assert f"🛠 Gestionando <b>@{CLONE_USERNAME}</b>" in app.last_text(SUPER_ID)
    # the panel keeps working meanwhile
    await app.press(SUPER_ID, MenuCB(screen="panel").pack())
    assert "Panel de la plataforma" in app.last_text(SUPER_ID)


async def test_disable_and_enable(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    await open_bot(app)
    button, _ = app.find_button(SUPER_ID, "Desactivar")
    await app.press(SUPER_ID, button["callback_data"])
    await app.press(SUPER_ID, button["callback_data"])  # a double tap keeps it disabled
    rec = await get_bot(app)
    assert (rec.status, rec.status_reason) == (BotStatus.DISABLED, clones.REASON_ADMIN)
    assert not app.manager.is_running(CLONE_ID)
    assert "📌 Estado: 🔒 Desactivado por la administración" in app.last_text(SUPER_ID)

    await app.press(USER_ID, CloneCB(action="resume", id=CLONE_ID).pack())  # its owner can't bring it back
    assert "administración ha desactivado" in answer_text(app)
    assert not app.manager.is_running(CLONE_ID)

    button, _ = app.find_button(SUPER_ID, "▶️ Activar")
    await app.press(SUPER_ID, button["callback_data"])
    await app.press(SUPER_ID, button["callback_data"])
    rec = await get_bot(app)
    assert rec.status == BotStatus.ACTIVE and rec.status_reason is None and app.manager.is_running(CLONE_ID)
    assert "📌 Estado: ✅ Activo" in app.last_text(SUPER_ID)


def test_parse_limits() -> None:
    assert parse_limits("50 20") == (50, 20)
    assert parse_limits("0, -") == (0, None)
    assert parse_limits("-") == (None, None)
    assert parse_limits("10") == (10, 10)
    for bad in ("", "a b", "1 2 3", "-5 3", "²"):
        assert parse_limits(bad) is None, bad


async def test_limits(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    await open_bot(app)
    await app.click(SUPER_ID, "Límites")
    text = app.last_text(SUPER_ID)
    assert f"Límites de @{CLONE_USERNAME}" in text and "Ahora: sin límites (predeterminado)" in text
    await app.send(SUPER_ID, "muchos")
    assert "No se entiende" in app.last_text(SUPER_ID)

    await app.send(SUPER_ID, "50 20")
    text = app.last_text(SUPER_ID)
    assert text.startswith("✅ Guardado") and "🔒 Límites: 50 chats · 20 mensajes\n" in text + "\n"
    rec = await get_bot(app)
    assert (rec.limit_chats, rec.limit_posts) == (50, 20)
    async with app.db() as s:
        assert await limits.max_chats(s, app.settings, rec) == 50
        assert await limits.max_posts(s, app.settings, rec) == 20

    async with app.db() as s:  # the platform default: 30 posts per clone
        p = await limits.platform(s, app.settings)
        p.limit_posts = 30
        await limits.save_platform(s, p)
    await app.click(SUPER_ID, "Límites")
    await app.send(SUPER_ID, "0 -")
    assert "🔒 Límites: chats sin límite · 30 mensajes (predeterminado)" in app.last_text(SUPER_ID)
    rec = await get_bot(app)
    assert (rec.limit_chats, rec.limit_posts) == (0, None)

    # the bots of a super admin have no limits: nothing to set
    await make_bot(app, CLONE_ID + 1, "super_cine_bot", SUPER_ID)
    text = await open_bot(app, CLONE_ID + 1)
    assert "🔒 Límites: sin límites (es de un super admin)" in text
    assert not any("Límites" in b for b in button_texts(app, SUPER_ID))


async def test_write_to_the_owner(app: App) -> None:
    await app.send(USER_ID, "/start")
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    await open_bot(app)
    await app.click(SUPER_ID, "Escribir al dueño")
    assert f"Mensaje para el dueño de @{CLONE_USERNAME}" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, None, photo="AgADphoto")  # type: ignore[arg-type]
    assert "Envía el mensaje como texto" in app.last_text(SUPER_ID)

    await app.send(SUPER_ID, "Hola Pepe, revisa tu canal <ya>",
                   entities=[{"type": "bold", "offset": 0, "length": 9}])
    dm = dms(app, USER_ID)[-1]
    assert dm == (f"💬 <b>Mensaje de la administración</b> sobre tu bot @{CLONE_USERNAME}:\n\n"
                  "<b>Hola Pepe</b>, revisa tu canal &lt;ya&gt;")
    text = app.last_text(SUPER_ID)
    assert text.startswith("✅ Mensaje enviado al dueño.") and f"@{CLONE_USERNAME}" in text

    app.fake.blocked.add((MAIN_BOT_ID, USER_ID))  # the owner blocked the main bot
    await app.click(SUPER_ID, "Escribir al dueño")
    await app.send(SUPER_ID, "¿Sigues ahí?")
    assert app.last_text(SUPER_ID).startswith("⚠️ No se ha podido enviar")


async def test_activity_of_a_clone(app: App) -> None:
    await app.send(USER_ID, "/start")
    await make_bot(app, CLONE_ID, CLONE_USERNAME, USER_ID)
    await make_bot(app, CLONE_ID + 1, "clon_vacio_bot", USER_ID)
    now = utcnow()
    await add_rows(app, *(Event(bot_id=CLONE_ID, kind=EventKind.CHAT_PAUSED, chat_title=f"Canal {i}", actor_id=USER_ID,
                                data={"by": "owner", "until": None}, created_at=now - timedelta(minutes=i))
                          for i in range(10)))
    await open_bot(app)
    await app.click(SUPER_ID, "Actividad")
    text = app.last_text(SUPER_ID)
    assert f"📜 <b>Actividad de @{CLONE_USERNAME}</b>" in text
    assert "<b>Canal 0</b> ha pausado la distribución hasta que la reanude (@pepe)." in text
    assert "Canal 7" in text and "Canal 8" not in text
    await app.click(SUPER_ID, "Siguiente")
    text = app.last_text(SUPER_ID)
    assert "Canal 8" in text and "Canal 9" in text and "Canal 0<" not in text
    assert any("Anterior" in b for b in button_texts(app, SUPER_ID))
    await app.click(SUPER_ID, "Regresar")
    assert f"🤖 <b>@{CLONE_USERNAME}</b>" in app.last_text(SUPER_ID)

    await open_bot(app, CLONE_ID + 1)
    await app.click(SUPER_ID, "Actividad")
    assert "Todavía no hay actividad" in app.last_text(SUPER_ID)


async def test_delete_after_two_confirmations(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    await app.send(USER_ID, "/start", bot_id=CLONE_ID)
    await add_rows(app, chat(CLONE_ID, -1001, "Canal de Cine", 1000), Post(bot_id=CLONE_ID, name="Promo Cine"),
                   Event(bot_id=CLONE_ID, kind=EventKind.BOT_PAUSED, created_at=utcnow()))
    await app.send(SUPER_ID, "/start")
    await open_bot(app)
    await app.click(SUPER_ID, "Gestionar")  # being managed by this super admin doesn't matter
    await open_bot(app)

    await app.click(SUPER_ID, "🗑 Eliminar")
    assert f"¿Eliminar @{CLONE_USERNAME}?" in app.last_text(SUPER_ID)
    await app.click(SUPER_ID, "Sí, eliminar")
    assert "Última confirmación" in app.last_text(SUPER_ID)
    assert await get_bot(app) is not None and app.manager.is_running(CLONE_ID)

    await app.click(SUPER_ID, "Eliminar definitivamente")
    assert "Bot eliminado" in answer_text(app)
    assert not app.manager.is_running(CLONE_ID) and await get_bot(app) is None
    async with app.db() as s:
        for model in (Chat, Post, Event, BotUser):
            n = (await s.execute(select(func.count()).select_from(model).where(model.bot_id == CLONE_ID))).scalar()
            assert n == 0, model.__name__
        assert (await s.get(BotUser, (MAIN_BOT_ID, SUPER_ID))).ws_bot_id is None
    text = app.last_text(SUPER_ID)
    assert "<b>Clones</b>" in text and "Gestionando" not in text
    await app.send(SUPER_ID, "/start")
    assert "Gestionando" not in app.last_text(SUPER_ID)

    await app.press(SUPER_ID, PanelCB(action="del3", id=CLONE_ID).pack())  # stale button
    assert "Ya no existe" in answer_text(app)


# ---------------------------------------------------------------- ⚙️ Plataforma
async def test_platform_settings(app: App) -> None:
    await app.send(SUPER_ID, "/start")
    await app.press(SUPER_ID, MenuCB(screen="panel").pack())
    await app.click(SUPER_ID, "Plataforma")
    text = app.last_text(SUPER_ID)
    assert "🤖 Creación de bots: 🌐 Abierta" in text and "🔢 Bots por usuario: <b>3</b>" in text
    assert "📣 Chats por clon: <b>sin límite</b>" in text and "📝 Mensajes por clon: <b>sin límite</b>" in text
    assert "✅ Abierta" in button_texts(app, SUPER_ID)

    await app.click(SUPER_ID, "Con aprobación")
    assert "esperan a que un super admin los apruebe" in app.last_text(SUPER_ID)
    assert "✅ Con aprobación" in button_texts(app, SUPER_ID)

    await app.click(SUPER_ID, "Bots por usuario")
    assert "Ahora: 3" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "muchos")
    assert "Envía un número válido" in app.last_text(SUPER_ID)
    await app.send(SUPER_ID, "5")
    text = app.last_text(SUPER_ID)
    assert text.startswith("✅ Guardado") and "🔢 Bots por usuario: <b>5</b>" in text
    await app.click(SUPER_ID, "Chats por clon")
    await app.send(SUPER_ID, "100")
    await app.click(SUPER_ID, "Mensajes por clon")
    await app.send(SUPER_ID, "0")
    async with app.db() as s:
        p = await limits.platform(s, app.settings)
    assert (p.clone_policy, p.max_clones, p.limit_chats, p.limit_posts) == ("approval", 5, 100, 0)

    # it applies at once: the clone screen of a user and the limits of a clone without its own
    await app.send(USER_ID, "/start")
    await app.press(USER_ID, MenuCB(screen="clone").pack())
    assert "Tus bots: <b>0</b>/5" in app.last_text(USER_ID) and "pendiente" in app.last_text(USER_ID)
    await make_bot(app, CLONE_ID, CLONE_USERNAME, USER_ID)
    assert "🔒 Límites: 100 chats (predeterminado) · mensajes sin límite (predeterminado)" in await open_bot(app)


# ------------------------------------------------------------ 📢 Aviso a los dueños
async def test_notice_to_the_owners(app: App) -> None:
    await app.send(USER_ID, "/start")
    await app.send(OWNER2_ID, "/start")
    await make_bot(app, CLONE_ID, "clon_uno_bot", USER_ID)
    await make_bot(app, CLONE_ID + 1, "clon_dos_bot", OWNER2_ID, status=BotStatus.PENDING)
    await make_bot(app, CLONE_ID + 2, "clon_tres_bot", OWNER2_ID)
    await make_bot(app, CLONE_ID + 3, "super_bot", SUPER_ID)  # the sender doesn't get it
    await make_bot(app, CLONE_ID + 4, "fuera_bot", 444, status=BotStatus.DISABLED, reason=clones.REASON_REMOVED)
    await app.send(SUPER_ID, "/start")
    await app.press(SUPER_ID, MenuCB(screen="panel").pack())
    await app.click(SUPER_ID, "Aviso a los dueños")
    assert "(<b>2</b> personas)" in app.last_text(SUPER_ID)

    await app.send(SUPER_ID, "¡Novedades en la plataforma!")
    assert "Este mensaje se enviará a <b>2</b> dueños de bots." in app.last_text(SUPER_ID)
    button, _ = app.find_button(SUPER_ID, "Enviar")
    await app.press(SUPER_ID, button["callback_data"])
    await app.wait_for(lambda: any("Aviso a los dueños enviado" in t for t in dms(app, SUPER_ID)))
    copies = app.fake.calls_of("copyMessage")
    assert sorted(c.params["chat_id"] for c in copies) == sorted([USER_ID, OWNER2_ID])
    assert all(c.params["from_chat_id"] == SUPER_ID for c in copies)
    report = next(t for t in dms(app, SUPER_ID) if "Aviso a los dueños enviado" in t)
    assert "✅ Entregados: <b>2</b>" in report and "❌ Fallidos: 0" in report

    await app.press(SUPER_ID, button["callback_data"])  # a second tap doesn't send it again
    assert "ya se ha enviado" in answer_text(app)
    assert len(app.fake.calls_of("copyMessage")) == 2

    # opened by its name, the screen explains it before asking for the message
    await app.press(SUPER_ID, MenuCB(screen="panel_blast").pack())
    assert "✏️ Escribir el aviso" in button_texts(app, SUPER_ID)
    await app.click(SUPER_ID, "Escribir el aviso")
    assert "Envía el mensaje" in app.last_text(SUPER_ID)


async def test_notice_without_owners(app: App) -> None:
    await app.send(SUPER_ID, "/start")
    await app.press(SUPER_ID, PanelCB(action="blast").pack())
    assert "no hay dueños de bots" in app.last_text(SUPER_ID)


# -------------------------------------------------------------------- 📄 Errores
async def test_errors_file(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    book = logbook.LogBook()
    monkeypatch.setattr(logbook, "book", book)
    book.entries.append(logbook.Entry(utcnow(), CLONE_ID, "WARNING | app.engine | algo raro en el clon"))
    book.entries.append(logbook.Entry(utcnow(), None, "ERROR | app.main | fallo general"))
    await make_bot(app, CLONE_ID, CLONE_USERNAME, USER_ID)
    await app.send(SUPER_ID, "/start")
    await app.press(SUPER_ID, MenuCB(screen="panel").pack())
    await app.click(SUPER_ID, "Errores")
    doc = app.fake.last("sendDocument", chat_id=SUPER_ID)
    data = app.fake.files[doc.params["document"]].decode()
    assert data.startswith("Errores y avisos de todos los bots")
    assert f"[bot {CLONE_ID}] WARNING | app.engine | algo raro en el clon" in data and "fallo general" in data
    assert "2 entradas" in doc.params["caption"]
    assert "Archivo enviado" in answer_text(app)

    await open_bot(app)
    await app.click(SUPER_ID, "Errores")  # only this clone's
    doc = app.fake.last("sendDocument", chat_id=SUPER_ID)
    data = app.fake.files[doc.params["document"]].decode()
    assert data.startswith(f"Errores y avisos de @{CLONE_USERNAME}")
    assert "algo raro en el clon" in data and "fallo general" not in data


# ------------------------------------------------------------------- permissions
async def test_the_panel_is_only_for_super_admins_in_main_bots(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    await app.send(USER_ID, "/start")
    await app.send(USER_ID, "hola")  # a message to copy, if a forged blast went through
    for name in ("panel", "panel_bots", "panel_settings", "panel_blast"):
        await app.press(USER_ID, MenuCB(screen=name).pack())
        assert "permiso" in answer_text(app), name
    await app.press(USER_ID, MenuCB(screen="panel_bot", arg=CLONE_ID).pack())
    assert "permiso" in answer_text(app)
    forged = [PanelCB(action=a, id=CLONE_ID) for a in (
        "bot", "ws", "off", "on", "ok", "no", "lim", "dm", "act", "logs", "del", "del2", "del3", "bots", "find",
        "blast")]
    forged += [PanelCB(action="pol", v=2), PanelCB(action="set", v=0), PanelCB(action="logs"),
               PanelCB(action="blast_go", v=1)]
    for cb in forged:
        await app.press(USER_ID, cb.pack())
        assert "permiso" in answer_text(app), cb.action
    # the clone's owner is no super admin either
    await app.press(OWNER2_ID, PanelCB(action="del3", id=CLONE_ID).pack())
    assert "permiso" in answer_text(app)

    rec = await get_bot(app)
    assert rec is not None and rec.status == BotStatus.ACTIVE and app.manager.is_running(CLONE_ID)
    async with app.db() as s:
        assert (await limits.platform(s, app.settings)).clone_policy == "open"
        assert (await s.get(BotUser, (MAIN_BOT_ID, USER_ID))).ws_bot_id is None
    assert not app.fake.calls_of("sendDocument") and not app.fake.calls_of("copyMessage")
    assert await app.storage.get_state(_key(USER_ID)) is None

    # a super admin finds the panel in the main bots only
    await app.press(SUPER_ID, MenuCB(screen="panel").pack(), bot_id=CLONE_ID)
    assert "permiso" in answer_text(app)
    await app.press(SUPER_ID, PanelCB(action="off", id=CLONE_ID).pack(), bot_id=CLONE_ID)
    assert "permiso" in answer_text(app) and app.manager.is_running(CLONE_ID)
    # ... and never changes a main bot from it
    for action in ("off", "del3", "ws"):
        await app.press(SUPER_ID, PanelCB(action=action, id=MAIN_BOT_ID).pack())
        assert "El bot principal no se gestiona desde aquí" in answer_text(app)
    assert app.manager.is_running(MAIN_BOT_ID) and await get_bot(app, MAIN_BOT_ID) is not None


def _key(user_id: int) -> Any:
    from aiogram.fsm.storage.base import StorageKey

    return StorageKey(bot_id=MAIN_BOT_ID, chat_id=user_id, user_id=user_id)
