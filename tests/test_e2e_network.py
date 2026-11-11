"""End to end: a whole network built through the real screens, across every module.

The owner adds a channel, opens the network to partners, accepts a partner's channel, makes a group of chats, sets
the default schedule, writes a post with colored buttons (it starts with that schedule); the scheduler distributes
it; the partner pauses the distribution (the owner is alerted and sees it); a user creates a clone and the super
admin manages the clone's network from the main bot, posting a photo the clone publishes.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import BotUser, Chat, ChatGroup, ChatOrigin, ChatStatus, Event, EventKind, GroupChat, Post
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App

OWN_CHANNEL = -1001001
PARTNER_CHANNEL = -1002002
CLONE_ID = 7_100_000_001
CLONE_CHANNEL = -1003003


async def chat_row(app: App, chat_id: int, bot_id: int = MAIN_BOT_ID) -> Chat:
    async with app.db() as s:
        row = (await s.execute(select(Chat).where(Chat.bot_id == bot_id, Chat.chat_id == chat_id))).scalar_one()
        return row


def channel_posts(app: App, chat_id: int) -> list[dict]:
    return [c.params for c in app.fake.messages_to(chat_id)]


def dm_texts(app: App, user_id: int, token: str | None = None) -> list[str]:
    return [str(c.params.get("text") or c.params.get("caption") or "") for c in app.panels(user_id, token)]


async def due_now(app: App, post_id: int) -> None:
    """Makes the next time of a post due and runs the scheduler once."""
    async with app.db() as s:
        post = await s.get(Post, post_id)
        assert post is not None
        post.next_send_at = utcnow() - timedelta(minutes=1)
    await app.scheduler.tick(wait=True)


async def test_network_end_to_end(app: App) -> None:  # noqa: PLR0915 - one story, step by step
    # 1. The owner (super admin of the platform) opens the main bot and adds their channel: it is in at once.
    await app.send(SUPER_ID, "/start")
    await app.add_chat(OWN_CHANNEL, SUPER_ID, "Cine HD", members=5000)
    own = await chat_row(app, OWN_CHANNEL)
    assert (own.status, own.origin, own.rights_ok) == (ChatStatus.APPROVED, ChatOrigin.OWN, True)

    # 2. They open the network to partners: ⚙️ Ajustes › 🤝 Canales externos › Admitir.
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Ajustes")
    await app.click(SUPER_ID, "Canales externos")
    await app.click(SUPER_ID, "Admitir canales externos")
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        assert rec is not None and rec.join_open and rec.join_approval

    # 3. A partner adds their channel: it waits; the owner accepts the request from the notice.
    await app.send(USER_ID, "/start")
    await app.add_chat(PARTNER_CHANNEL, USER_ID, "Series Club", members=2000)
    partner = await chat_row(app, PARTNER_CHANNEL)
    assert (partner.status, partner.origin, partner.owner_user_id) == (ChatStatus.PENDING, ChatOrigin.EXTERNAL,
                                                                       USER_ID)
    assert any("Series Club" in t for t in dm_texts(app, SUPER_ID))
    await app.click(SUPER_ID, "Aceptar")
    partner = await chat_row(app, PARTNER_CHANNEL)
    assert partner.status == ChatStatus.APPROVED

    # 4. A group of chats "Cine" with the owner's channel in it.
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Grupos de canales")
    await app.click(SUPER_ID, "Nuevo grupo de canales")
    await app.send(SUPER_ID, "Cine")
    async with app.db() as s:
        group = (await s.execute(select(ChatGroup).where(ChatGroup.bot_id == MAIN_BOT_ID))).scalar_one()
    await app.click(SUPER_ID, "Cine HD")  # group_chats: toggle the channel in
    async with app.db() as s:
        assert await s.get(GroupChat, (group.id, own.id)) is not None

    # 5. ⏰ Horarios: the default schedule becomes every 2 h (the default is a fixed hour).
    await app.press(SUPER_ID, MenuCB(screen="freqs").pack())
    await app.click(SUPER_ID, "Horario por defecto")
    await app.click(SUPER_ID, "Cada cierto tiempo")
    await app.click(SUPER_ID, "2 h")
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        assert rec is not None and rec.freq["every"] == 120

    # 6. A post with colored buttons for everyone, at its own times, deleted after one day (the 5-step wizard).
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Mensajes")
    await app.click(SUPER_ID, "Nuevo mensaje")
    await app.send(SUPER_ID, "Estreno hoy", entities=[{"type": "bold", "offset": 0, "length": 7}])
    await app.send(SUPER_ID, "Ver ahora - https://example.com/cine 🟢\nCódigo - copiar: CINE10 🔵")
    await app.click(SUPER_ID, "Continuar")  # 🌐 Todos is selected by default
    await app.click(SUPER_ID, "A sus horas")
    await app.click(SUPER_ID, "1 día")  # how long it stays published
    async with app.db() as s:
        post = (await s.execute(select(Post).where(Post.bot_id == MAIN_BOT_ID))).scalar_one()
    assert post.text == "<b>Estreno</b> hoy" and post.targets == ["all"] and post.delete_after == 1440
    assert post.buttons[0][0]["style"] == "success" and post.buttons[1][0]["copy"] == "CINE10"
    assert post.freq["every"] == 120 and post.next_send_at is not None  # a copy of the default schedule

    # 7. Its time comes: both channels get it with the colored buttons.
    await due_now(app, post.id)
    sent = channel_posts(app, PARTNER_CHANNEL)
    assert len(sent) == 1 and sent[0]["text"] == "<b>Estreno</b> hoy"
    keyboard = sent[0]["reply_markup"]["inline_keyboard"]
    assert keyboard[0][0]["style"] == "success" and keyboard[1][0]["copy_text"] == {"text": "CINE10"}
    assert len(channel_posts(app, OWN_CHANNEL)) == 1

    # 8. The partner pauses the distribution for 24 h from 📣 Mis canales: the owner is alerted and sees it.
    await app.send(USER_ID, "/start")
    await app.click(USER_ID, "Mis canales")
    await app.click(USER_ID, "Series Club")
    await app.click(USER_ID, "Pausar")
    await app.click(USER_ID, "24 h")
    partner = await chat_row(app, PARTNER_CHANNEL)
    assert partner.owner_pause_active() and partner.owner_paused_until is not None
    assert any("ha pausado <b>" in t for t in dm_texts(app, SUPER_ID))
    async with app.db() as s:
        kinds = [e.kind for e in (await s.execute(select(Event).where(Event.bot_id == MAIN_BOT_ID))).scalars()]
    assert EventKind.CHAT_PAUSED in kinds
    await app.send(SUPER_ID, "/start")
    assert "Pausados por su socio" in app.last_text(SUPER_ID)

    # 9. Its next time: the paused channel gets nothing.
    await due_now(app, post.id)
    assert len(channel_posts(app, PARTNER_CHANNEL)) == 1

    # 10. A user creates their own bot (clone) in the main bot with a @BotFather token.
    token = app.fake.add_bot(CLONE_ID, "clon_series_bot", first_name="Clon Series")
    await app.send(OWNER2_ID, "/start")
    await app.press(OWNER2_ID, MenuCB(screen="clone").pack())
    await app.click(OWNER2_ID, "Usar token")
    await app.send(OWNER2_ID, token)
    assert app.manager.is_running(CLONE_ID)
    await app.add_chat(CLONE_CHANNEL, OWNER2_ID, "Noticias 24", bot_id=CLONE_ID)
    clone_chat = await chat_row(app, CLONE_CHANNEL, CLONE_ID)
    assert (clone_chat.status, clone_chat.origin) == (ChatStatus.APPROVED, ChatOrigin.OWN)

    # 11. The super admin manages the clone's network from the main bot (👑 Panel › 🛠 Gestionar) and posts a photo.
    await app.press(SUPER_ID, MenuCB(screen="panel_bot", arg=CLONE_ID).pack())
    await app.click(SUPER_ID, "Gestionar")
    assert "Gestionando <b>@clon_series_bot</b>" in app.last_text(SUPER_ID)
    async with app.db() as s:
        bu = await s.get(BotUser, (MAIN_BOT_ID, SUPER_ID))
        assert bu is not None and bu.ws_bot_id == CLONE_ID
    await app.click(SUPER_ID, "Mensajes")
    await app.click(SUPER_ID, "Nuevo mensaje")
    await app.feed(app.message_update(SUPER_ID, photo="mainphoto1", caption="Última hora"))
    await app.click(SUPER_ID, "Sin botones")
    await app.click(SUPER_ID, "Continuar")
    await app.click(SUPER_ID, "Solo cuando lo envíe yo")
    await app.click(SUPER_ID, "1 día")
    async with app.db() as s:
        clone_post = (await s.execute(select(Post).where(Post.bot_id == CLONE_ID))).scalar_one()
    assert clone_post.media == {str(MAIN_BOT_ID): "mainphoto1"}
    await app.click(SUPER_ID, "Enviar ahora")
    await app.click(SUPER_ID, "Enviar")
    await app.wait_for(lambda: channel_posts(app, CLONE_CHANNEL))
    photo = channel_posts(app, CLONE_CHANNEL)[0]
    clone_token = next(t for t, b in app.fake.bots.items() if b["id"] == CLONE_ID)
    assert photo["caption"] == "Última hora" and app.fake.calls_of("getFile")
    assert any(c.token == clone_token for c in app.fake.messages_to(CLONE_CHANNEL))

    async def remembered() -> bool:
        async with app.db() as s:
            p = await s.get(Post, clone_post.id)
            return p is not None and str(CLONE_ID) in (p.media or {})

    await app.wait_for(remembered)

    # 12. Leaving the clone's network goes back to the main bot's own one.
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Dejar de gestionar @clon_series_bot")
    async with app.db() as s:
        bu = await s.get(BotUser, (MAIN_BOT_ID, SUPER_ID))
        assert bu is not None and bu.ws_bot_id is None
    assert "Gestionando" not in app.last_text(SUPER_ID)


def test_every_linked_screen_exists() -> None:
    """Every ``screen="…"`` / ``open_screen("…")`` written in the code is registered by some module."""
    import app.bot.routers as routers
    from app.ui import screens

    for info in pkgutil.iter_modules(routers.__path__):
        importlib.import_module(f"app.bot.routers.{info.name}")
    pattern = re.compile(r'(?:screen=|open_screen\(|cancel_screen=)\s*"([a-z_]+)"')
    names: set[str] = set()
    for path in Path(routers.__file__).resolve().parents[2].rglob("*.py"):
        names |= set(pattern.findall(path.read_text(encoding="utf-8")))
    names.discard("name")  # the placeholder of the docstrings
    missing = sorted(n for n in names if not screens.has_screen(n))
    assert not missing, f"screens linked but never registered: {missing}"
