"""Start module: 📊 statistics (24 h / 7 days / 30 days) and 📜 activity (paginated events of the network)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.db.base import utcnow
from app.db.models import ChatOrigin, ChatStatus, EventKind
from app.ui.callbacks import MenuCB
from app.ui.common import TEXT_LIMIT, visible_len
from tests.conftest import SUPER_ID, USER_ID, App
from tests.test_start_helpers import (
    CLONE_ID,
    add_chat_row,
    add_clone,
    add_event,
    add_run,
    button_texts,
    callback_of,
    denied,
    make_admin,
    manage,
)


async def open_stats(app: App, user_id: int = SUPER_ID) -> None:
    await app.send(user_id, "/start")
    await app.click(user_id, "Estadísticas")


async def seed_runs(app: App) -> None:
    await add_run(app, ago=timedelta(hours=1), post_name="Promo Cine", sent=10, failed=1, skipped=2, reach=1000)
    await add_run(app, ago=timedelta(days=3), post_name="Promo Series", sent=20, failed=3, reach=2000)
    await add_run(app, ago=timedelta(days=20), post_name="Promo Cine", sent=5, skipped=4, reach=1_234_567)
    await add_run(app, ago=timedelta(days=40), post_name="Muy antiguo", sent=99, reach=99)  # out of every period
    await add_run(app, ago=timedelta(hours=1), post_name="Sin entregas", failed=7)  # never in the top
    await add_run(app, ago=timedelta(hours=1), bot_id=CLONE_ID, post_name="Otra red", sent=50)


async def test_stats_periods_with_seeded_runs(app: App) -> None:
    await add_clone(app)
    await seed_runs(app)
    await open_stats(app)
    text = app.last_text(SUPER_ID)
    assert text.startswith("📊 <b>Estadísticas</b> · últimas 24 h\n\n📤 Envíos: <b>2</b>\n✅ Entregados: <b>10</b>\n"
                           "❌ Fallidos: <b>8</b>\n🛡 Omitidos por anti-spam: <b>2</b>\n👁 Alcance: <b>1,000</b>\n"
                           "   └ Miembros de los chats que recibieron los mensajes.\n\n")
    assert text.endswith("🏆 <b>Mensajes más enviados</b>\n1. Promo Cine — 10")
    assert "Otra red" not in text and "Sin entregas" not in text
    assert button_texts(app, SUPER_ID) == ["✅ 24 h", "⚪ 7 días", "⚪ 30 días", "📜 Actividad", "🔙 Regresar"]
    assert callback_of(app, SUPER_ID, "7 días") == MenuCB(screen="stats", arg=1).pack()
    assert callback_of(app, SUPER_ID, "Actividad") == MenuCB(screen="activity").pack()
    assert callback_of(app, SUPER_ID, "Regresar") == MenuCB(screen="home").pack()
    await app.click(SUPER_ID, "7 días")
    text = app.last_text(SUPER_ID)
    assert "· últimos 7 días" in text and "📤 Envíos: <b>3</b>" in text and "✅ Entregados: <b>30</b>" in text
    assert "❌ Fallidos: <b>11</b>" in text and "👁 Alcance: <b>3,000</b>" in text
    assert text.endswith("1. Promo Series — 20\n2. Promo Cine — 10")
    assert button_texts(app, SUPER_ID)[:3] == ["⚪ 24 h", "✅ 7 días", "⚪ 30 días"]
    await app.click(SUPER_ID, "30 días")
    text = app.last_text(SUPER_ID)
    assert "· últimos 30 días" in text and "📤 Envíos: <b>4</b>" in text and "✅ Entregados: <b>35</b>" in text
    assert "🛡 Omitidos por anti-spam: <b>6</b>" in text and "👁 Alcance: <b>1,237,567</b>" in text
    assert text.endswith("1. Promo Series — 20\n2. Promo Cine — 15")
    assert "Muy antiguo" not in text
    await app.press(SUPER_ID, MenuCB(screen="stats", arg=7).pack())  # unknown periods show the last 24 h
    assert "· últimas 24 h" in app.last_text(SUPER_ID)


async def test_stats_of_the_chats(app: App) -> None:
    future = utcnow() + timedelta(hours=6)
    await add_chat_row(app, members=1000)
    await add_chat_row(app, members=2000, origin=ChatOrigin.EXTERNAL, owner_paused=True, owner_paused_until=future)
    await add_chat_row(app, members=300, admin_paused=True)
    await add_chat_row(app, members=20, owner_paused=True, admin_paused=True)  # paused twice: counted once
    await add_chat_row(app, members=40, rights_ok=False, owner_paused=True)  # missing rights wins
    await add_chat_row(app, members=10, owner_paused=True, owner_paused_until=utcnow() - timedelta(hours=1))  # over
    await add_chat_row(app, status=ChatStatus.PENDING)
    await add_chat_row(app, status=ChatStatus.REJECTED)
    await open_stats(app)
    text = app.last_text(SUPER_ID)
    assert "📣 Chats: 6 (🏠 5 · 🤝 1) · 👤 3,370\n⏸ Pausados: 3 · ⚠️ Sin permisos: 1 · ⏳ Pendientes: 1" in text
    assert "🏆" not in text  # nothing was sent


async def test_an_empty_network_has_no_state_line(app: App) -> None:
    await open_stats(app)
    text = app.last_text(SUPER_ID)
    assert "📣 Chats: 0 (🏠 0 · 🤝 0) · 👤 0" in text and "Pausados" not in text and "Pendientes" not in text


async def test_post_names_are_escaped(app: App) -> None:
    await add_run(app, ago=timedelta(hours=1), post_name="<b>Promo</b> & co", sent=3)
    await open_stats(app)
    assert "1. &lt;b&gt;Promo&lt;/b&gt; &amp; co — 3" in app.last_text(SUPER_ID)


async def test_stats_and_activity_are_for_admins_only(app: App) -> None:
    await app.send(USER_ID, "/start")
    for screen in ("stats", "activity"):
        await app.press(USER_ID, MenuCB(screen=screen).pack())
        assert denied(app), screen
    await make_admin(app, USER_ID)
    await app.press(USER_ID, MenuCB(screen="stats").pack())
    assert app.last_text(USER_ID).startswith("📊 <b>Estadísticas</b>")


async def test_stats_in_hub_mode_open_the_home(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.settings, "MAIN_BOT_MODE", "hub")
    await app.send(SUPER_ID, "/start")
    for screen in ("stats", "activity"):
        await app.press(SUPER_ID, MenuCB(screen=screen).pack())
        assert app.last_text(SUPER_ID).startswith("🕸 <b>eMesh · Tu propia red de distribución</b>"), screen


async def test_stats_while_managing_a_clone(app: App) -> None:
    await add_clone(app)
    await seed_runs(app)
    await manage(app, SUPER_ID, CLONE_ID)
    await open_stats(app)
    text = app.last_text(SUPER_ID)
    assert "Gestionando" in text and "✅ Entregados: <b>50</b>" in text and "1. Otra red — 50" in text


# ------------------------------------------------------------------------------------------ activity
async def test_activity_pagination(app: App) -> None:
    start = utcnow() - timedelta(hours=30)
    for i in range(23):
        await add_event(app, EventKind.CHAT_ADDED, chat_title=f"Canal {i:02d}", actor_id=SUPER_ID,
                        created_at=start + timedelta(minutes=i))
    await add_clone(app)
    await add_event(app, EventKind.CHAT_ADDED, bot_id=CLONE_ID, chat_title="De otra red")
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Actividad")
    text = app.last_text(SUPER_ID)
    assert text.startswith("📜 <b>Actividad</b>\n\n➕ <i>")
    assert text.count("➕ <i>") == 10 and "<b>Canal 22</b> se ha añadido a la red (@superadmin)." in text
    assert text.index("Canal 22") < text.index("Canal 13")  # newest first
    assert "Canal 12" not in text and "De otra red" not in text
    assert text.endswith("📄 Página 1 de 3")
    assert button_texts(app, SUPER_ID) == ["Siguiente ➡️", "🔙 Regresar"]
    assert callback_of(app, SUPER_ID, "Regresar") == MenuCB(screen="home").pack()
    await app.click(SUPER_ID, "Siguiente")
    text = app.last_text(SUPER_ID)
    assert "Canal 12" in text and "Canal 03" in text and "Canal 13" not in text and "Canal 02" not in text
    assert button_texts(app, SUPER_ID) == ["⬅️ Anterior", "Siguiente ➡️", "🔙 Regresar"]
    await app.click(SUPER_ID, "Siguiente")
    text = app.last_text(SUPER_ID)
    assert text.count("➕ <i>") == 3 and "Canal 00" in text and text.endswith("📄 Página 3 de 3")
    assert button_texts(app, SUPER_ID) == ["⬅️ Anterior", "🔙 Regresar"]
    await app.press(SUPER_ID, MenuCB(screen="activity", arg=50).pack())  # clamped to the last page
    assert app.last_text(SUPER_ID).endswith("📄 Página 3 de 3")


async def test_empty_activity(app: App) -> None:
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Actividad")
    assert app.last_text(SUPER_ID) == (
        "📜 <b>Actividad</b>\n\nTodavía no hay actividad. Aquí aparece lo que pasa en los canales de la red: los que "
        "se unen, se pausan, pierden permisos o salen.")
    assert button_texts(app, SUPER_ID) == ["🔙 Regresar"]


async def test_activity_describes_each_event(app: App) -> None:
    await app.send(USER_ID, "/start")
    await add_event(app, EventKind.CHAT_PAUSED, chat_title="Cine <HD>", actor_id=USER_ID,
                    data={"by": "owner", "until": None})
    await add_event(app, EventKind.BOT_PAUSED, chat_title="", actor_id=SUPER_ID)
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Actividad")
    text = app.last_text(SUPER_ID)
    assert "⏸ <i>" in text
    assert "<b>Cine &lt;HD&gt;</b> ha pausado la distribución hasta que la reanude (@pepe)." in text
    assert "Distribución de toda la red pausada (@superadmin)." in text
    assert "Página" not in text  # a single page


async def test_very_long_activity_entries_still_fit(app: App) -> None:
    app.fake.add_user(555, "🦁" * 64, None)
    await app.send(555, "/start")
    for _ in range(10):
        await add_event(app, EventKind.CHAT_PAUSED, chat_title="🎬" * 128, actor_id=555,
                        data={"by": "owner", "until": None})
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Actividad")
    text = app.last_text(SUPER_ID)
    assert visible_len(text) <= TEXT_LIMIT
    assert text.count("…") == 10  # each entry was cut


async def test_activity_while_managing_a_clone(app: App) -> None:
    await add_clone(app)
    await add_event(app, EventKind.CHAT_ADDED, chat_title="Del principal")
    await add_event(app, EventKind.CHAT_ADDED, bot_id=CLONE_ID, chat_title="Del clon")
    await manage(app, SUPER_ID, CLONE_ID)
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Actividad")
    text = app.last_text(SUPER_ID)
    assert "Del clon" in text and "Del principal" not in text
