"""Clones module: 🤖 Crear mi bot (policy, limits, Managed Bots link), the token flow, the managed_bot update,
🤖 Mis bots and the DM about an invalid token."""
from __future__ import annotations

import json
import logging
from urllib.parse import unquote

import pytest
from aiogram.exceptions import TelegramUnauthorizedError

from app.bot.routers.clone import CloneCB
from app.bot.routers.panel import PanelCB
from app.db.models import Bot as BotRecord
from app.db.models import BotStatus
from app.services import clones, limits
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, MAIN_BOT_USERNAME, OWNER2_ID, SUPER_ID, USER_ID, App

CLONE_ID = 6_100_000_201
CLONE_USERNAME = "pepe_cine_bot"


def answer_text(app: App) -> str:
    call = app.fake.last("answerCallbackQuery")
    return str(call.params.get("text", "")) if call else ""


def button_texts(app: App, chat_id: int) -> list[str]:
    return [b["text"] for b in app.buttons(app.last_panel(chat_id))]


def dms(app: App, chat_id: int) -> list[str]:
    """Texts sent by the main bot to a private chat."""
    return [str(c.params.get("text", "")) for c in app.fake.calls_of("sendMessage", chat_id=chat_id)
            if c.token == app.settings.BOT_TOKEN]


async def get_bot(app: App, bot_id: int) -> BotRecord | None:
    async with app.db() as s:
        return await s.get(BotRecord, bot_id)


async def set_policy(app: App, policy: str = "open", max_clones: int | None = None) -> None:
    async with app.db() as s:
        p = await limits.platform(s, app.settings)
        p.clone_policy = policy
        if max_clones is not None:
            p.max_clones = max_clones
        await limits.save_platform(s, p)


async def open_clone(app: App, user_id: int = USER_ID) -> str:
    await app.send(user_id, "/start")
    await app.press(user_id, MenuCB(screen="clone").pack())
    return app.last_text(user_id)


def managed_update(app: App, user_id: int, bot_id: int) -> dict:
    return {"update_id": app.fake.new_update_id(),
            "managed_bot": {"user": app.fake.users[user_id], "bot": app.bot_user_json(bot_id)}}


# ----------------------------------------------------------------- clone screen
def test_token_bot_id() -> None:
    assert clones.token_bot_id(" 123456:AAH-x_y9 ") == 123456
    for bad in ("hola", "123456", "123:", ":abc", "abc:def", "123:abc def", "123:abc:def"):
        assert clones.token_bot_id(bad) is None, bad


def test_suggest_username() -> None:
    assert clones.suggest_username("pepe", "Pepe", 1) == "pepe_mesh_bot"
    assert clones.suggest_username(None, "José María", 1) == "Jose_Maria_mesh_bot"
    assert clones.suggest_username(None, "🔥", 42) == "u42_mesh_bot"


async def test_clone_screen_open_policy(app: App) -> None:
    text = await open_clone(app)
    assert "Crea tu propio bot" in text and "Tus bots: <b>0</b>/3" in text
    assert "pendiente" not in text and "🔒" not in text
    create, _ = app.find_button(USER_ID, "Crear bot")
    assert unquote(create["url"]) == f"https://t.me/newbot/{MAIN_BOT_USERNAME}/pepe_mesh_bot?name=Red de Pepe"
    assert app.find_button(USER_ID, "Usar token")[0]["callback_data"] == CloneCB(action="token").pack()
    assert app.find_button(USER_ID, "Mis bots (0)")[0]["callback_data"] == MenuCB(screen="mybots").pack()
    assert app.find_button(USER_ID, "Regresar")[0]["callback_data"] == MenuCB(screen="home").pack()


async def test_clone_screen_approval_policy(app: App) -> None:
    await set_policy(app, "approval")
    text = await open_clone(app)
    assert "Tu bot quedará pendiente hasta que la administración lo apruebe" in text
    assert any("Crear bot" in b for b in button_texts(app, USER_ID))
    assert any("Usar token" in b for b in button_texts(app, USER_ID))
    # super admins don't need an approval
    assert "pendiente" not in await open_clone(app, SUPER_ID)


async def test_clone_screen_closed_policy(app: App) -> None:
    await set_policy(app, "closed")
    text = await open_clone(app)
    assert "Ahora mismo no se pueden crear bots nuevos" in text
    assert not any("Crear bot" in b or "Usar token" in b for b in button_texts(app, USER_ID))
    await app.press(USER_ID, CloneCB(action="token").pack())  # forged / stale button
    assert "no se pueden crear bots nuevos" in answer_text(app)
    # super admins still can
    text = await open_clone(app, SUPER_ID)
    assert "no se pueden crear" not in text and "Tus bots: <b>0</b>/∞" in text
    assert any("Crear bot" in b for b in button_texts(app, SUPER_ID))


async def test_clone_screen_limit_reached(app: App) -> None:
    await set_policy(app, max_clones=1)
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    text = await open_clone(app)
    assert "Tus bots: <b>1</b>/1" in text and "Has llegado al máximo de bots" in text
    buttons = button_texts(app, USER_ID)
    assert not any("Crear bot" in b for b in buttons)  # the managed link always creates a new bot
    assert any("Usar token" in b for b in buttons)  # ... a token can still re-connect one of theirs
    assert "si el token de uno de tus bots ha cambiado" in text
    assert any("Mis bots (1)" in b for b in buttons)


async def test_clone_screen_without_bot_management_mode(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clones, "_can_manage", {})
    app.fake.bots[app.settings.BOT_TOKEN]["can_manage_bots"] = False
    text = await open_clone(app)
    assert "✨ <b>Crear bot</b>" not in text
    assert not any("Crear bot" in b for b in button_texts(app, USER_ID))
    assert any("Usar token" in b for b in button_texts(app, USER_ID))


async def test_clone_screens_in_a_clone_point_to_the_main_bot(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    for name in ("clone", "mybots"):
        await app.press(USER_ID, MenuCB(screen=name).pack(), bot_id=CLONE_ID)
        button, _ = app.find_button(USER_ID, f"@{MAIN_BOT_USERNAME}")
        assert button["url"] == f"https://t.me/{MAIN_BOT_USERNAME}?start=clone"
    await app.press(USER_ID, CloneCB(action="token").pack(), bot_id=CLONE_ID)
    assert "permiso" in answer_text(app)


# ------------------------------------------------------------------- token flow
async def test_token_flow(app: App, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    clone_token = app.fake.add_bot(CLONE_ID, CLONE_USERNAME, first_name="Pepe Cine")
    await open_clone(app)
    await app.click(USER_ID, "Usar token")
    assert "Pégalo aquí" in app.last_text(USER_ID)

    await app.send(USER_ID, "hola que tal")
    assert "no parece un token" in app.last_text(USER_ID)
    await app.send(USER_ID, f"{CLONE_ID}:con espacios")  # aiogram itself would refuse it with an exception
    assert "no parece un token" in app.last_text(USER_ID)
    await app.send(USER_ID, f"{CLONE_ID + 1}:WRONG")
    assert "no es válido o se ha revocado" in app.last_text(USER_ID)
    await app.send(USER_ID, app.settings.BOT_TOKEN)
    assert "token del bot de la plataforma" in app.last_text(USER_ID)
    await app.send(USER_ID, None, photo="AgADphoto", caption="mi token")  # type: ignore[arg-type]
    assert "Envía el token como texto" in app.last_text(USER_ID)
    assert await get_bot(app, CLONE_ID) is None

    await app.send(USER_ID, clone_token)
    assert f"¡Tu bot @{CLONE_USERNAME} está listo!" in app.last_text(USER_ID)
    assert app.find_button(USER_ID, f"Abrir @{CLONE_USERNAME}")[0]["url"] == f"https://t.me/{CLONE_USERNAME}"
    rec = await get_bot(app, CLONE_ID)
    assert rec is not None and rec.owner_id == USER_ID and not rec.managed and rec.status == BotStatus.ACTIVE
    assert app.manager.is_running(CLONE_ID)
    notice = next(t for t in dms(app, SUPER_ID) if "Nuevo clon" in t)
    assert f"@{CLONE_USERNAME}" in notice and "Token de @BotFather" in notice and "Pendiente" not in notice
    # every message sent while the token was asked was deleted at once (the bot's own replaced prompts aside)
    bot_messages = {c.result["message_id"] for c in app.fake.calls if isinstance(c.result, dict)
                    and "message_id" in c.result}
    deleted = {c.params["message_id"] for c in app.fake.calls_of("deleteMessage", chat_id=USER_ID)}
    assert len(deleted - bot_messages) == 6
    # the token never shows up: not in any text sent by the bots, not in the logs
    assert all(clone_token not in json.dumps(c.params, ensure_ascii=False) for c in app.fake.calls)
    assert not [r for r in caplog.records
                if r.name.startswith(("app", "aiogram")) and clone_token in r.getMessage()]

    # the flow is over: another message isn't taken as a token
    deletes = len(app.fake.calls_of("deleteMessage"))
    await app.send(USER_ID, clone_token)
    assert len(app.fake.calls_of("deleteMessage")) == deletes

    # someone else can't take it
    await open_clone(app, OWNER2_ID)
    await app.click(OWNER2_ID, "Usar token")
    await app.send(OWNER2_ID, clone_token)
    assert "ya lo ha conectado otra persona" in app.last_text(OWNER2_ID)
    assert (await get_bot(app, CLONE_ID)).owner_id == USER_ID


async def test_token_flow_limit(app: App) -> None:
    await set_policy(app, max_clones=1)
    first = app.fake.add_bot(CLONE_ID, CLONE_USERNAME)
    second = app.fake.add_bot(CLONE_ID + 1, "pepe_series_bot")
    await open_clone(app)
    await app.click(USER_ID, "Usar token")
    await app.send(USER_ID, first)
    assert "está listo" in app.last_text(USER_ID)

    await open_clone(app)
    await app.click(USER_ID, "Usar token")  # still offered: it re-connects one of the user's bots
    await app.send(USER_ID, second)
    assert "Ya tienes el máximo de 1 bots" in app.last_text(USER_ID)
    assert await get_bot(app, CLONE_ID + 1) is None
    deletes = len(app.fake.calls_of("deleteMessage"))
    await app.send(USER_ID, second)  # the flow ended with the limit
    assert len(app.fake.calls_of("deleteMessage")) == deletes

    # re-connecting a bot the user already has doesn't count against the limit; super admins are unlimited
    async with app.db() as s:
        rec, is_new = await clones.connect_clone(app.manager, s, app.settings, first, USER_ID)
        assert rec.id == CLONE_ID and not is_new
        rec, is_new = await clones.connect_clone(app.manager, s, app.settings, second, SUPER_ID)
        assert rec.owner_id == SUPER_ID and is_new


async def test_token_flow_with_approval(app: App) -> None:
    await set_policy(app, "approval")
    token = app.fake.add_bot(CLONE_ID, CLONE_USERNAME)
    await open_clone(app)
    await app.click(USER_ID, "Usar token")
    await app.send(USER_ID, token)
    assert "pendiente de aprobación" in app.last_text(USER_ID)
    rec = await get_bot(app, CLONE_ID)
    assert rec.status == BotStatus.PENDING and not app.manager.is_running(CLONE_ID)
    notice = next(t for t in dms(app, SUPER_ID) if "Nuevo clon" in t)
    assert "Pendiente de aprobación" in notice
    assert app.find_button(SUPER_ID, "Aprobar")[0]["callback_data"] == PanelCB(action="ok", id=CLONE_ID).pack()

    # sending its token again doesn't skip the approval
    async with app.db() as s:
        rec, is_new = await clones.connect_clone(app.manager, s, app.settings, token, USER_ID)
    assert rec.status == BotStatus.PENDING and not is_new and not app.manager.is_running(CLONE_ID)


async def test_reconnecting_an_approved_bot_needs_no_new_approval(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    await set_policy(app, "approval")
    token = app.fake.add_bot(CLONE_ID, CLONE_USERNAME)
    async with app.db() as s:
        rec, is_new = await clones.connect_clone(app.manager, s, app.settings, token, USER_ID)
    assert rec.status == BotStatus.ACTIVE and not is_new and app.manager.is_running(CLONE_ID)
    # ... and a closed platform still lets owners re-connect their own bots, but not add new ones
    await set_policy(app, "closed")
    async with app.db() as s:
        rec, _ = await clones.connect_clone(app.manager, s, app.settings, token, USER_ID)
        assert rec.status == BotStatus.ACTIVE
        other = app.fake.add_bot(CLONE_ID + 1, "pepe_series_bot")
        with pytest.raises(clones.BotTokenError, match="closed"):
            await clones.connect_clone(app.manager, s, app.settings, other, USER_ID)


# ------------------------------------------------------------------ Managed Bots
async def test_managed_bot_open_policy(app: App) -> None:
    new_id = 6_100_000_777
    token = app.fake.add_bot(new_id, "pepe_mesh_bot", first_name="Red de Pepe")
    app.fake.managed_tokens[new_id] = token
    # the creator never wrote to the main bot before: the update works anyway
    await app.feed(managed_update(app, USER_ID, new_id))

    assert app.fake.calls_of("getManagedBotToken", user_id=new_id)
    rec = await get_bot(app, new_id)
    assert rec is not None and rec.owner_id == USER_ID and rec.managed and rec.status == BotStatus.ACTIVE
    assert app.manager.is_running(new_id)
    dm = app.fake.last("sendMessage", chat_id=USER_ID)
    assert dm.token == app.settings.BOT_TOKEN
    assert dm.params["text"] == "✅ ¡Tu bot @pepe_mesh_bot está listo! Ábrelo y pulsa /start."
    assert dm.params["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://t.me/pepe_mesh_bot"
    notice = app.fake.last("sendMessage", chat_id=SUPER_ID)
    assert "Nuevo clon" in notice.params["text"] and "Creado con Telegram" in notice.params["text"]
    assert "reply_markup" not in notice.params  # nothing to decide


async def test_managed_bot_with_approval_then_approved(app: App) -> None:
    await set_policy(app, "approval")
    await app.send(SUPER_ID, "/start")
    await app.send(USER_ID, "/start")
    new_id = 6_100_000_778
    app.fake.managed_tokens[new_id] = app.fake.add_bot(new_id, "pepe_mesh_bot")
    await app.feed(managed_update(app, USER_ID, new_id))

    rec = await get_bot(app, new_id)
    assert rec.status == BotStatus.PENDING and rec.managed and not app.manager.is_running(new_id)
    assert "pendiente de aprobación" in dms(app, USER_ID)[-1]
    notice = dms(app, SUPER_ID)[-1]
    assert "Nuevo clon" in notice and "Pendiente de aprobación" in notice
    assert app.find_button(SUPER_ID, "Rechazar")[0]["style"] == "danger"

    await app.click(SUPER_ID, "Aprobar")  # straight from the notice
    rec = await get_bot(app, new_id)
    assert rec.status == BotStatus.ACTIVE and app.manager.is_running(new_id)
    assert "Bot aprobado" in answer_text(app)
    assert "se ha aprobado" in dms(app, USER_ID)[-1]
    assert app.find_button(USER_ID, "Abrir @pepe_mesh_bot")[0]["url"] == "https://t.me/pepe_mesh_bot"
    assert "📌 Estado: ✅ Activo" in app.last_text(SUPER_ID)  # the notice turned into the bot's page

    # a second tap (or another super admin's notice) changes nothing
    await app.press(SUPER_ID, PanelCB(action="no", id=new_id).pack())
    assert "ya no está pendiente" in answer_text(app)
    assert (await get_bot(app, new_id)).status == BotStatus.ACTIVE


async def test_managed_bot_with_approval_then_rejected(app: App) -> None:
    await set_policy(app, "approval")
    await app.send(USER_ID, "/start")
    new_id = 6_100_000_779
    token = app.fake.add_bot(new_id, "pepe_mesh_bot")
    app.fake.managed_tokens[new_id] = token
    await app.feed(managed_update(app, USER_ID, new_id))

    await app.click(SUPER_ID, "Rechazar")
    rec = await get_bot(app, new_id)
    assert (rec.status, rec.status_reason) == (BotStatus.DISABLED, clones.REASON_ADMIN)
    assert not app.manager.is_running(new_id)
    assert "no se ha aprobado" in dms(app, USER_ID)[-1]
    await app.press(USER_ID, MenuCB(screen="mybots").pack())
    assert "🔒 Desactivado por la administración" in app.last_text(USER_ID)
    # the owner can't bring it back with its token
    async with app.db() as s:
        with pytest.raises(clones.BotTokenError, match="admin_locked"):
            await clones.connect_clone(app.manager, s, app.settings, token, USER_ID)


async def test_managed_bot_closed_policy(app: App) -> None:
    await set_policy(app, "closed")
    new_id = 6_100_000_780
    app.fake.managed_tokens[new_id] = app.fake.add_bot(new_id, "pepe_mesh_bot")
    await app.send(USER_ID, "/start")
    await app.feed(managed_update(app, USER_ID, new_id))
    assert await get_bot(app, new_id) is None
    text = dms(app, USER_ID)[-1]
    assert "@pepe_mesh_bot" in text and "no se pueden crear bots nuevos" in text


async def test_managed_bot_over_the_limit_is_not_connected(app: App) -> None:
    await set_policy(app, max_clones=1)
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    new_id = 6_100_000_781
    app.fake.managed_tokens[new_id] = app.fake.add_bot(new_id, "pepe_extra_bot")
    await app.send(USER_ID, "/start")
    await app.feed(managed_update(app, USER_ID, new_id))
    assert await get_bot(app, new_id) is None
    assert "máximo de 1 bots" in dms(app, USER_ID)[-1]


async def test_managed_bot_update_ignored_by_clones(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    new_id = 6_100_000_782
    app.fake.managed_tokens[new_id] = app.fake.add_bot(new_id, "pepe_other_bot")
    await app.feed(managed_update(app, USER_ID, new_id), bot_id=CLONE_ID)
    assert not app.fake.calls_of("getManagedBotToken")
    assert await get_bot(app, new_id) is None


async def test_managed_bot_new_token_keeps_a_paused_bot_stopped(app: App) -> None:
    new_id = 6_100_000_783
    old_token = app.fake.add_bot(new_id, "pepe_paused_bot")
    app.fake.managed_tokens[new_id] = old_token
    await app.send(USER_ID, "/start")
    await app.feed(managed_update(app, USER_ID, new_id))
    await app.manager.disable_bot(new_id, reason=clones.REASON_OWNER)

    new_token = f"{new_id}:ROTATED"
    app.fake.bots[new_token] = app.fake.bots.pop(old_token)  # the token was replaced in Telegram
    app.fake.managed_tokens[new_id] = new_token
    await app.feed(managed_update(app, USER_ID, new_id))
    rec = await get_bot(app, new_id)
    assert rec.status == BotStatus.DISABLED and not app.manager.is_running(new_id)
    assert app.manager.cipher.decrypt(rec.token_enc) == new_token

    await app.press(USER_ID, MenuCB(screen="mybots").pack())
    await app.click(USER_ID, "▶️ Activar")
    assert (await get_bot(app, new_id)).status == BotStatus.ACTIVE and app.manager.is_running(new_id)


# ---------------------------------------------------------------------- Mis bots
async def test_mybots_pause_resume_and_disconnect(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    await app.send(USER_ID, "/start")
    await app.press(USER_ID, MenuCB(screen="mybots").pack())
    assert f"1. @{CLONE_USERNAME} · ✅ Activo" in app.last_text(USER_ID)
    assert "(1/3)" in app.last_text(USER_ID)

    await app.click(USER_ID, "Pausar")
    rec = await get_bot(app, CLONE_ID)
    assert (rec.status, rec.status_reason) == (BotStatus.DISABLED, clones.REASON_OWNER)
    assert not app.manager.is_running(CLONE_ID)
    assert "⏸ Pausado" in app.last_text(USER_ID) and "Bot pausado" in answer_text(app)

    await app.click(USER_ID, "▶️ Activar")
    assert (await get_bot(app, CLONE_ID)).status == BotStatus.ACTIVE and app.manager.is_running(CLONE_ID)
    assert "✅ Activo" in app.last_text(USER_ID)

    await app.click(USER_ID, "Desconectar")
    assert "¿Desconectar @pepe_cine_bot?" in app.last_text(USER_ID)
    await app.click(USER_ID, "Sí, desconectar")
    rec = await get_bot(app, CLONE_ID)
    assert (rec.status, rec.status_reason) == (BotStatus.DISABLED, clones.REASON_REMOVED)
    assert not app.manager.is_running(CLONE_ID)
    assert "Aún no tienes bots" in app.last_text(USER_ID)
    async with app.db() as s:
        assert await clones.count_user_bots(s, USER_ID) == 0
    # a stale button of the disconnected bot does nothing
    await app.press(USER_ID, CloneCB(action="resume", id=CLONE_ID).pack())
    assert "Ya no existe" in answer_text(app)
    assert (await get_bot(app, CLONE_ID)).status_reason == clones.REASON_REMOVED


async def test_admin_locked_bot_cant_be_resumed_by_its_owner(app: App) -> None:
    token = app.fake.add_bot(CLONE_ID, CLONE_USERNAME)
    await app.manager.add_bot(token, USER_ID)
    await app.manager.disable_bot(CLONE_ID, reason=clones.REASON_ADMIN)
    await app.send(USER_ID, "/start")
    await app.press(USER_ID, MenuCB(screen="mybots").pack())
    assert "🔒 Desactivado por la administración" in app.last_text(USER_ID)
    assert not any("Activar" in b or "Desconectar" in b for b in button_texts(app, USER_ID))

    for action in ("resume", "remove", "remove_ok"):  # forged / stale buttons
        await app.press(USER_ID, CloneCB(action=action, id=CLONE_ID).pack())
        assert "administración ha desactivado" in answer_text(app)
    rec = await get_bot(app, CLONE_ID)
    assert (rec.status, rec.status_reason) == (BotStatus.DISABLED, clones.REASON_ADMIN)
    assert not app.manager.is_running(CLONE_ID)

    # ... and its token doesn't bring it back either
    await open_clone(app)
    await app.click(USER_ID, "Usar token")
    await app.send(USER_ID, token)
    assert "administración ha desactivado ese bot" in app.last_text(USER_ID)
    assert (await get_bot(app, CLONE_ID)).status == BotStatus.DISABLED
    assert not app.manager.is_running(CLONE_ID)


async def test_owner_cant_touch_another_owners_bot(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    await app.send(OWNER2_ID, "/start")
    for action in ("pause", "remove", "remove_ok"):
        await app.press(OWNER2_ID, CloneCB(action=action, id=CLONE_ID).pack())
        assert "permiso" in answer_text(app)
    rec = await get_bot(app, CLONE_ID)
    assert rec.status == BotStatus.ACTIVE and app.manager.is_running(CLONE_ID)
    # not even a super admin acts on someone else's bot from "Mis bots" (the 👑 panel is the place)
    await app.press(SUPER_ID, CloneCB(action="pause", id=CLONE_ID).pack())
    assert "permiso" in answer_text(app) and app.manager.is_running(CLONE_ID)
    # the main bot is never "one of my bots"
    await app.press(SUPER_ID, CloneCB(action="remove_ok", id=MAIN_BOT_ID).pack())
    assert "permiso" in answer_text(app) and app.manager.is_running(MAIN_BOT_ID)


async def test_pending_bot_can_be_withdrawn(app: App) -> None:
    await set_policy(app, "approval")
    await app.manager.add_bot(app.fake.add_bot(CLONE_ID, CLONE_USERNAME), USER_ID, pending=True)
    await app.send(USER_ID, "/start")
    await app.press(USER_ID, MenuCB(screen="mybots").pack())
    text = app.last_text(USER_ID)
    assert "⏳ Pendiente de aprobación" in text and "se pondrá en marcha cuando la administración" in text
    assert not any("Pausar" in b or "Activar" in b for b in button_texts(app, USER_ID))
    await app.press(USER_ID, CloneCB(action="resume", id=CLONE_ID).pack())  # forged: it stays pending
    assert (await get_bot(app, CLONE_ID)).status == BotStatus.PENDING

    await app.click(USER_ID, "Desconectar")
    assert "¿Retirar @pepe_cine_bot?" in app.last_text(USER_ID)
    await app.click(USER_ID, "Sí, desconectar")
    assert await get_bot(app, CLONE_ID) is None  # it never ran: a new connection asks for approval again
    assert "Solicitud retirada" in answer_text(app)
    assert "Aún no tienes bots" in app.last_text(USER_ID)


# ---------------------------------------------------------------- invalid token
async def test_invalid_token_dm_through_the_main_bot(app: App) -> None:
    clones.install(app.manager, app.sm, app.settings)
    clones.install(app.manager, app.sm, app.settings)  # registered once
    assert sum(isinstance(cb, clones._InvalidTokenNotice) for cb in app.manager.on_bot_invalid) == 1

    token = app.fake.add_bot(CLONE_ID, CLONE_USERNAME)
    await app.manager.add_bot(token, USER_ID)
    await app.send(USER_ID, "/start")
    clone_bot = app.manager.get(CLONE_ID)
    app.fake.bots.pop(token)  # revoked in @BotFather: Telegram answers 401
    with pytest.raises(TelegramUnauthorizedError):
        await clone_bot.send_message(USER_ID, "hola")

    await app.wait_for(lambda: any("ya no es válido" in t for t in dms(app, USER_ID)))
    dm = next(t for t in dms(app, USER_ID) if "ya no es válido" in t)
    assert f"@{CLONE_USERNAME}" in dm and "Usar token" in dm
    assert app.find_button(USER_ID, "Conectarlo de nuevo")[0]["callback_data"] == MenuCB(screen="clone").pack()
    rec = await get_bot(app, CLONE_ID)
    assert rec.status == BotStatus.INVALID and not app.manager.is_running(CLONE_ID)
    assert len([t for t in dms(app, USER_ID) if "ya no es válido" in t]) == 1

    await app.press(USER_ID, MenuCB(screen="mybots").pack())
    text = app.last_text(USER_ID)
    assert "❌ Token no válido" in text and "conéctalo de nuevo con «🔑 Usar token»" in text
