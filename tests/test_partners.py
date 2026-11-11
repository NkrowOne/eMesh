"""Chats module, partners: how to join, 📣 Mis canales and the panel of their chats (pause, resume, categories,
leave the network)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.bot.routers.chats import ChCB
from app.bot.routers.partners import PaCB
from app.db.base import utcnow
from app.db.models import Chat, ChatOrigin, ChatStatus, EventKind, GroupChat
from app.ui.callbacks import MenuCB
from app.ui.fmt import dt
from tests.conftest import OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_chats_support import (  # noqa: F401  (reset_chat_caches is an autouse fixture)
    CHANNEL,
    GROUP,
    button,
    db_chat,
    dms,
    events_of,
    get_chat,
    is_alert,
    labels,
    last_answer,
    make_group,
    partner_chat,
    record_drops,
    reset_chat_caches,
    set_bot,
    start,
)

TZ = "Europe/Madrid"


async def pa(app: App, user_id: int, action: str, pk: int = 0, **kw: int) -> None:
    await app.press(user_id, PaCB(a=action, id=pk, **kw).pack())


# --------------------------------------------------------------------------- join
async def test_join_screen(app: App) -> None:
    await start(app, USER_ID)
    await app.press(USER_ID, "m:join:0")
    assert app.last_text(USER_ID) == "🔒 Esta red es privada."

    await set_bot(app, join_open=True, min_members=500)
    await app.press(USER_ID, "m:join:0")
    text = app.last_text(USER_ID)
    assert text.startswith("🤝 <b>Únete a la red de @emesh_test_bot</b>")
    assert ("publicar mensajes, editar mensajes, eliminar mensajes en canales; eliminar mensajes, fijar mensajes en "
            "grupos") in text
    assert "La administración revisará la solicitud" in text and "👤 Mínimo: <b>500</b> miembros." in text
    assert "⏸ Puedes pausar la distribución cuando quieras" in text
    panel = app.last_panel(USER_ID)
    assert "startchannel" in button(panel, "Añadir canal")["url"]
    assert "startgroup" in button(panel, "Añadir grupo")["url"]

    await set_bot(app, join_approval=False)
    await app.press(USER_ID, "m:join:0")
    assert "Entrará en la red al momento" in app.last_text(USER_ID)


# --------------------------------------------------------------------------- 📣 Mis canales
async def test_my_chats_lists_only_my_external_chats(app: App) -> None:
    await start(app, SUPER_ID, USER_ID, OWNER2_ID)
    mine = await partner_chat(app)
    await db_chat(app, GROUP, "Grupo Pendiente", type="group", origin=ChatOrigin.EXTERNAL, owner=USER_ID,
                  status=ChatStatus.PENDING, members=300)
    await db_chat(app, -1003, "Se fue", origin=ChatOrigin.EXTERNAL, owner=USER_ID, status=ChatStatus.LEFT)
    await db_chat(app, -1004, "De Otro", origin=ChatOrigin.EXTERNAL, owner=OWNER2_ID)
    await db_chat(app, -1005, "Propio del admin", owner=USER_ID)

    await app.press(USER_ID, "m:my_chats:0")
    text = app.last_text(USER_ID)
    assert "📣 <b>Mis canales</b>" in text
    assert "1. 📣 Cine HD ✅\n   └👤 1,200 · ✅ Recibe los mensajes de la red" in text
    assert "2. 👥 Grupo Pendiente ⏳\n   └👤 300 · ⏳ Pendiente de aprobación" in text
    assert "Se fue" not in text and "De Otro" not in text and "Propio del admin" not in text
    assert button(app.last_panel(USER_ID), "#1 📣 Cine HD")["callback_data"] == PaCB(a="op", id=mine.id).pack()

    await app.press(OWNER2_ID, "m:my_chats:0")
    text = app.last_text(OWNER2_ID)
    assert "De Otro" in text and "Cine HD" not in text
    await app.press(444, "m:my_chats:0")
    assert "Aún no tienes canales ni grupos en esta red" in app.last_text(444)
    assert button(app.last_panel(444), "Cómo unirse")["callback_data"] == MenuCB(screen="join").pack()


async def test_my_chat_panel(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await make_group(app, "Cine", open=True)
    chat = await partner_chat(app)
    await pa(app, USER_ID, "op", chat.id)
    text = app.last_text(USER_ID)
    assert text == ("📣 <b>Cine HD</b>\n📌 Estado: ✅ Recibe los mensajes de la red\n📨 Recibidos: 0 · últimos 7 días: 0"
                    "\n🕐 Último: —\n🗂 Categorías: Cine")
    assert labels(app.last_panel(USER_ID)) == ["⏸ Pausar", "🗂 Categorías", "🚪 Salir de la red", "🔙 Regresar"]


# --------------------------------------------------------------------------- ⏸ pause / ▶️ resume
@pytest.mark.parametrize(("value", "label", "length"), [
    (1, "1 h", timedelta(hours=1)),
    (2, "6 h", timedelta(hours=6)),
    (3, "24 h", timedelta(hours=24)),
    (4, "3 días", timedelta(days=3)),
    (5, "7 días", timedelta(days=7)),
    (6, "Hasta que la reanude", None),
])
async def test_partner_pauses_and_resumes(app: App, value: int, label: str, length: timedelta | None) -> None:
    await start(app, SUPER_ID, USER_ID)
    await set_bot(app, pause_max_hours=0)  # no limit: every duration is offered (the rules: test_chats_rules.py)
    chat = await partner_chat(app)
    await pa(app, USER_ID, "op", chat.id)
    await app.click(USER_ID, "Pausar")
    assert "¿Cuánto tiempo?" in app.last_text(USER_ID)
    assert labels(app.last_panel(USER_ID)) == ["⏸ 1 h", "⏸ 6 h", "⏸ 24 h", "⏸ 3 días", "⏸ 7 días",
                                               "⏸ Hasta que la reanude", "🔙 Regresar"]
    before = utcnow()
    await app.click(USER_ID, label)

    chat = await get_chat(app)
    assert chat.owner_paused and chat.owner_pause_active() and chat.paused_at is not None
    assert last_answer(app)["text"] == "⏸ Pausado. Se ha avisado a la administración."
    [event] = await events_of(app, EventKind.CHAT_PAUSED)
    assert event.actor_id == USER_ID and event.data["by"] == "owner"
    if length is None:
        assert chat.owner_paused_until is None and event.data["until"] is None
        assert "📌 Estado: ⏸ Pausado hasta que lo reanudes" in app.last_text(USER_ID)
        alert = "Tu asociado @pepe ha pausado <b>Cine HD</b> hasta que la reanude."
    else:
        assert before + length - timedelta(seconds=5) < chat.owner_paused_until < utcnow() + length
        assert event.data["until"] == chat.owner_paused_until.isoformat()
        assert f"📌 Estado: ⏸ Pausado hasta {dt(chat.owner_paused_until, TZ)}" in app.last_text(USER_ID)
        alert = f"Tu asociado @pepe ha pausado <b>Cine HD</b> hasta el {dt(chat.owner_paused_until, TZ)}."
    assert any(alert in t for t in dms(app, SUPER_ID)), "the admins are alerted"
    assert labels(app.last_panel(USER_ID))[0] == "▶️ Reanudar"

    # The admins see it in the list and in its detail.
    await app.press(SUPER_ID, "m:chats:0")
    assert "Cine HD ⏸" in app.last_text(SUPER_ID)

    await app.click(USER_ID, "Reanudar")
    chat = await get_chat(app)
    assert not chat.owner_paused and chat.owner_paused_until is None and chat.paused_at is None
    assert last_answer(app)["text"] == "▶️ Reanudado. Se ha avisado a la administración."
    [resumed] = await events_of(app, EventKind.CHAT_RESUMED)
    assert resumed.data == {"by": "owner"} and resumed.actor_id == USER_ID
    assert any("Tu asociado @pepe ha reanudado <b>Cine HD</b>." in t for t in dms(app, SUPER_ID))


async def test_partner_cant_resume_an_admin_pause(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await app.press(SUPER_ID, ChCB(a="pz", id=chat.id).pack())
    await pa(app, USER_ID, "op", chat.id)
    text = app.last_text(USER_ID)
    assert "📌 Estado: ⏸ Pausado por la administración" in text and "Solo la administración puede reanudarlo" in text
    assert "▶️ Reanudar" not in labels(app.last_panel(USER_ID))
    await pa(app, USER_ID, "rs", chat.id)  # forged
    assert is_alert(app, "Lo ha pausado la administración")
    assert (await get_chat(app)).admin_paused
    assert not await events_of(app, EventKind.CHAT_RESUMED)

    # Their own pause on top of it: resuming lifts only theirs.
    await pa(app, USER_ID, "pz", chat.id, v=1)
    await pa(app, USER_ID, "rs", chat.id)
    chat = await get_chat(app)
    assert not chat.owner_paused and chat.admin_paused and chat.paused_at is not None


async def test_pause_needs_an_approved_chat_and_a_known_duration(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await pa(app, USER_ID, "pz", chat.id, v=99)
    assert is_alert(app, "Ya no existe")
    pending = await db_chat(app, GROUP, "Pendiente", origin=ChatOrigin.EXTERNAL, owner=USER_ID,
                            status=ChatStatus.PENDING)
    await pa(app, USER_ID, "pz", pending, v=1)
    assert is_alert(app, "No es posible con su estado actual: ⏳ Pendiente de aprobación")
    await pa(app, USER_ID, "rs", chat.id)
    assert is_alert(app, "No está pausado")
    assert not await events_of(app, EventKind.CHAT_PAUSED)


async def test_other_users_cant_touch_a_partner_chat(app: App) -> None:
    await start(app, SUPER_ID, USER_ID, OWNER2_ID)
    chat = await partner_chat(app)
    gid = await make_group(app, "Cine", open=True)
    for action, value in (("op", 0), ("pm", 0), ("pz", 1), ("rs", 0), ("ct", 0), ("cx", gid), ("lv", 0), ("lvy", 0)):
        await pa(app, OWNER2_ID, action, chat.id, v=value)
        assert is_alert(app, "Ya no existe"), action
    chat = await get_chat(app)
    assert chat.status == ChatStatus.APPROVED and not chat.owner_paused
    await app.press(OWNER2_ID, f"m:my_chat:{chat.id}")
    assert "Ya no existe" in app.last_text(OWNER2_ID)
    # Admins only look at it (no action as its owner).
    await app.press(SUPER_ID, f"m:my_chat:{chat.id}")
    assert "👁 Así lo ve su dueño." in app.last_text(SUPER_ID)
    assert labels(app.last_panel(SUPER_ID)) == ["🛠 Ficha de admin", "🔙 Regresar"]
    await pa(app, SUPER_ID, "pz", chat.id, v=1)
    assert is_alert(app, "Ya no existe")


async def test_own_chats_have_no_partner_panel(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    pk = await db_chat(app, CHANNEL, "Propio", owner=USER_ID)
    await pa(app, USER_ID, "pz", pk, v=1)
    assert is_alert(app, "Ya no existe")
    async with app.db() as s:
        assert not (await s.get(Chat, pk)).owner_paused


# --------------------------------------------------------------------------- 🗂 categories
async def test_categories_are_the_open_groups(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    cine = await make_group(app, "Cine", open=True)
    series = await make_group(app, "Series", open=True)
    private = await make_group(app, "Privado")
    chat = await partner_chat(app)  # joins every open group
    await pa(app, USER_ID, "ct", chat.id)
    text = app.last_text(USER_ID)
    assert text.startswith("🗂 <b>Categorías</b> · Cine HD") and "Toca una para entrar o salir" in text
    assert labels(app.last_panel(USER_ID)) == ["✅ Cine", "✅ Series", "🔙 Regresar"]

    await app.click(USER_ID, "Series")
    assert last_answer(app)["text"] == "➖ Ya no está en Series"
    assert labels(app.last_panel(USER_ID))[:2] == ["✅ Cine", "✖️ Series"]
    async with app.db() as s:
        assert await s.get(GroupChat, (series, chat.id)) is None
        assert await s.get(GroupChat, (cine, chat.id)) is not None
    await app.click(USER_ID, "Series")
    assert last_answer(app)["text"] == "✅ Ahora está en Series"

    await pa(app, USER_ID, "cx", chat.id, v=private)  # forged: a group that isn't open
    assert is_alert(app, "Ya no existe")
    async with app.db() as s:
        assert await s.get(GroupChat, (private, chat.id)) is None


async def test_no_categories_button_without_open_groups(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    await make_group(app, "Privado")
    chat = await partner_chat(app)
    await pa(app, USER_ID, "op", chat.id)
    assert "🗂 Categorías" not in labels(app.last_panel(USER_ID))
    await pa(app, USER_ID, "ct", chat.id)
    assert "Esta red no tiene categorías por ahora" in app.last_text(USER_ID)


# --------------------------------------------------------------------------- 🚪 leave the network
async def test_partner_leaves_the_network(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    drops = record_drops(app, monkeypatch)
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    await pa(app, USER_ID, "op", chat.id)
    await app.click(USER_ID, "Salir de la red")
    assert "🚪 ¿Sacar tu canal <b>Cine HD</b> de la red?" in app.last_text(USER_ID)
    assert not drops.calls
    await app.click(USER_ID, "Sí, salir")

    assert drops.calls == [chat.id] and drops.left_before == [False]
    assert app.fake.calls_of("leaveChat", chat_id=CHANNEL)
    chat = await get_chat(app)
    assert chat.status == ChatStatus.LEFT and chat.decided_by == USER_ID
    [event] = await events_of(app, EventKind.CHAT_REMOVED)
    assert event.data == {"by": "owner"} and event.actor_id == USER_ID
    assert any("Tu asociado @pepe ha retirado <b>Cine HD</b> de la red." in t for t in dms(app, SUPER_ID))
    assert "🚪 Tu canal <b>Cine HD</b> ha salido de la red." in app.last_text(USER_ID)
    assert not any("se ha quitado de la red" in t for t in dms(app)), "no DM about their own decision"
    assert button(app.last_panel(USER_ID), "Mis canales")["callback_data"] == MenuCB(screen="my_chats").pack()
    await app.press(USER_ID, "m:my_chats:0")
    assert "Cine HD" not in app.last_text(USER_ID)


# --------------------------------------------------------------------------- the scheduler's end of a pause
async def test_expired_pause_counts_as_over(app: App) -> None:
    await start(app, SUPER_ID, USER_ID)
    chat = await partner_chat(app)
    async with app.db() as s:
        row = await s.get(Chat, chat.id)
        row.owner_paused, row.owner_paused_until = True, utcnow() - timedelta(minutes=1)
    await pa(app, USER_ID, "op", chat.id)
    assert "📌 Estado: ✅ Recibe los mensajes de la red" in app.last_text(USER_ID)
    assert labels(app.last_panel(USER_ID))[0] == "⏸ Pausar"
