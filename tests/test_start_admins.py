"""Start module: /admin and /deladmin (owner only), in the main bot, in a clone and while managing a clone."""
from __future__ import annotations

from app.db.models import BotUser, Role
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_start_helpers import (
    CLONE_ID,
    CLONE_USERNAME,
    NO_PERMISSION,
    add_clone,
    callback_of,
    dms_to,
    get_bu,
    has_button,
    make_admin,
    manage,
)

NOT_FOUND = "⚠️ No se ha encontrado a esa persona. Antes debe abrir @{bot} y pulsar /start."


async def role_of(app: App, user_id: int, bot_id: int = MAIN_BOT_ID) -> str:
    return (await get_bu(app, user_id, bot_id)).role


async def started(app: App, user_id: int, bot_id: int = MAIN_BOT_ID) -> None:
    await app.send(user_id, "/start", bot_id=bot_id)


async def test_admin_command_promotes_and_notifies(app: App) -> None:
    await started(app, USER_ID)
    await app.send(SUPER_ID, "/admin @pepe")
    assert app.last_text(SUPER_ID) == "✅ @pepe ahora es admin."
    assert callback_of(app, SUPER_ID, "Ver admins") == MenuCB(screen="admins").pack()
    assert await role_of(app, USER_ID) == Role.ADMIN
    assert dms_to(app, USER_ID)[-1] == ("🔰 <b>Ahora eres admin de @emesh_test_bot</b>\n\nYa puedes gestionar su red "
                                        "de distribución. Pulsa /start para ver el panel.")
    assert has_button(app, USER_ID, "Menú principal")
    await app.click(USER_ID, "Menú principal")  # the new admin gets the network's home
    assert "Tu red de distribución" in app.last_text(USER_ID) and has_button(app, USER_ID, "Pausar todo")


async def test_admin_command_accepts_ids_and_ignores_case(app: App) -> None:
    await started(app, USER_ID)
    await app.send(SUPER_ID, f"/admin {USER_ID}")
    assert await role_of(app, USER_ID) == Role.ADMIN
    await app.send(SUPER_ID, f"/deladmin {USER_ID}")
    assert await role_of(app, USER_ID) == Role.USER
    assert app.last_text(SUPER_ID) == "✅ @pepe ya no es admin."
    assert dms_to(app, USER_ID)[-1] == "ℹ️ Ya no eres admin de @emesh_test_bot."
    await app.send(SUPER_ID, "/admin @PEPE extra words are ignored")
    assert await role_of(app, USER_ID) == Role.ADMIN


async def test_admin_command_errors(app: App) -> None:
    await started(app, USER_ID)
    app.fake.add_user(999, "Ghost", "ghost")  # exists on Telegram but never started the bot
    not_found = NOT_FOUND.format(bot="emesh_test_bot")
    cases = {
        "/admin": "ℹ️ Uso: <code>/admin @usuario</code> o <code>/admin ID</code>",
        "/deladmin": "ℹ️ Uso: <code>/deladmin @usuario</code> o <code>/deladmin ID</code>",
        "/admin @ghost": not_found,
        "/admin 999": not_found,
        "/admin @": not_found,
        f"/admin {SUPER_ID}": "⚠️ No puedes cambiar tu propio rol.",
        "/deladmin @pepe": "ℹ️ @pepe no es admin.",
    }
    for command, reply in cases.items():
        await app.send(SUPER_ID, command)
        assert app.last_text(SUPER_ID) == reply, command
    assert await role_of(app, USER_ID) == Role.USER
    await app.send(SUPER_ID, "/admin @pepe")
    await app.send(SUPER_ID, "/admin @pepe")
    assert app.last_text(SUPER_ID) == "ℹ️ @pepe ya es admin."


async def test_admin_command_refuses_owners_super_admins_and_banned_users(app: App) -> None:
    await add_clone(app)
    await started(app, SUPER_ID, CLONE_ID)
    await started(app, USER_ID, CLONE_ID)
    await app.send(OWNER2_ID, f"/admin {SUPER_ID}", bot_id=CLONE_ID)  # super admins have every right already
    assert "ya tiene todos los permisos" in app.last_text(OWNER2_ID)
    await app.send(SUPER_ID, f"/admin {OWNER2_ID}", bot_id=CLONE_ID)  # and so does the owner
    assert "ya tiene todos los permisos" in app.last_text(SUPER_ID)
    async with app.db() as s:
        bu = await s.get(BotUser, (CLONE_ID, USER_ID))
        assert bu is not None
        bu.is_banned = True
    await app.send(OWNER2_ID, "/admin @pepe", bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID) == "⚠️ Esa persona está bloqueada en este bot."
    assert await role_of(app, USER_ID, CLONE_ID) == Role.USER
    assert await role_of(app, SUPER_ID, CLONE_ID) == Role.USER


async def test_only_owners_manage_admins(app: App) -> None:
    await started(app, OWNER2_ID)
    await make_admin(app, USER_ID)
    for command in ("/admin @owner2", "/deladmin @pepe", f"/admin {OWNER2_ID}"):
        await app.send(USER_ID, command)  # an admin
        assert app.last_text(USER_ID) == NO_PERMISSION, command
        await app.send(OWNER2_ID, command)  # a regular user
        assert app.last_text(OWNER2_ID) == NO_PERMISSION, command
    assert await role_of(app, USER_ID) == Role.ADMIN and await role_of(app, OWNER2_ID) == Role.USER


async def test_clone_owner_manages_the_admins_of_the_clone(app: App) -> None:
    await add_clone(app)
    await started(app, USER_ID, CLONE_ID)
    await app.send(OWNER2_ID, "/admin @pepe", bot_id=CLONE_ID)
    assert await role_of(app, USER_ID, CLONE_ID) == Role.ADMIN
    assert dms_to(app, USER_ID, CLONE_ID)[-1].startswith(f"🔰 <b>Ahora eres admin de @{CLONE_USERNAME}</b>")
    await started(app, USER_ID)
    assert await role_of(app, USER_ID) == Role.USER  # only in that bot


async def test_admin_command_while_managing_a_clone(app: App) -> None:
    await add_clone(app)
    await started(app, USER_ID)  # a user of the main bot only
    await manage(app, SUPER_ID, CLONE_ID)
    await app.send(SUPER_ID, "/admin @pepe")
    assert app.last_text(SUPER_ID) == (f"🛠 Gestionando <b>@{CLONE_USERNAME}</b>\n\n"
                                       + NOT_FOUND.format(bot=CLONE_USERNAME))
    await started(app, USER_ID, CLONE_ID)
    await app.send(SUPER_ID, "/admin @pepe")
    assert await role_of(app, USER_ID, CLONE_ID) == Role.ADMIN
    assert await role_of(app, USER_ID) == Role.USER
    assert dms_to(app, USER_ID, CLONE_ID)[-1].startswith(f"🔰 <b>Ahora eres admin de @{CLONE_USERNAME}</b>")


async def test_admin_command_says_when_the_new_admin_could_not_be_told(app: App) -> None:
    await started(app, USER_ID)
    app.fake.blocked.add((MAIN_BOT_ID, USER_ID))
    await app.send(SUPER_ID, "/admin @pepe")
    assert app.last_text(SUPER_ID) == "✅ @pepe ahora es admin.\n⚠️ No se le ha podido avisar por mensaje privado."
    assert await role_of(app, USER_ID) == Role.ADMIN
