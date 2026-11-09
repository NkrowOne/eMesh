"""Start module: the photo of the 🗺 timezone menu. One image for the whole platform (services/brand.py), chosen by a
super admin in the picker itself and shown on every step of the picker, in every bot."""
from __future__ import annotations

import pytest

from app.bot.routers.timezone import TzCB
from app.services import brand
from app.ui import common
from app.ui.callbacks import InputCancelCB
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_start_helpers import (
    CLONE_ID,
    CLONE_USERNAME,
    add_clone,
    denied,
    force_state,
    fsm_state,
    get_bu,
    has_button,
    last_answer,
    manage,
)

PHOTO = b"\xff\xd8JPEG-TZ-MENU"
PROMPT = "🖼 Envía la <b>foto</b> que se verá al abrir este menú, en todos los bots."


async def open_timezone(app: App, user_id: int, bot_id: int = MAIN_BOT_ID) -> None:
    await app.send(user_id, "/start", bot_id=bot_id)
    await app.click(user_id, "Ajustes", bot_id=bot_id)
    await app.click(user_id, "Zona horaria", bot_id=bot_id)


async def stored(app: App) -> dict[str, str]:
    async with app.db() as s:
        return await brand.photo_ids(s, brand.TZ)


async def put_photo(app: App, file_id: str = "TZPHOTO") -> None:
    app.fake.files[file_id] = PHOTO
    async with app.db() as s:
        await brand.set_photo(s, brand.TZ, MAIN_BOT_ID, file_id)


def photo_panel(app: App, user_id: int, file_id: str = "TZPHOTO") -> bool:
    call = app.last_panel(user_id)
    return call.method == "sendPhoto" and call.params["photo"] == file_id


def on_a_photo(app: App, user_id: int, data: str, message_id: int, file_id: str = "TZPHOTO") -> dict:
    """A button press on a panel that is the photo ``file_id`` (the fake's callbacks come from text panels)."""
    update = app.callback_update(user_id, data, message_id)
    message = update["callback_query"]["message"]
    del message["text"]
    message["photo"] = [{"file_id": file_id, "file_unique_id": f"u{file_id}", "width": 10, "height": 10}]
    message["caption"] = "panel"
    return update


async def test_a_super_admin_sets_changes_and_removes_the_photo(app: App) -> None:
    await open_timezone(app, SUPER_ID)
    assert has_button(app, SUPER_ID, "🖼 Poner imagen") and not has_button(app, SUPER_ID, "Quitar imagen")
    await app.click(SUPER_ID, "Poner imagen")
    assert await fsm_state(app, SUPER_ID) == "StartTimezoneFSM:photo"
    assert app.last_text(SUPER_ID) == PROMPT and app.last_panel(SUPER_ID).method == "sendMessage"
    await app.send(SUPER_ID, "no es una foto")
    assert app.last_text(SUPER_ID) == f"⚠️ Eso no es una foto.\n\n{PROMPT}"
    await app.send(SUPER_ID, None, photo="TZPHOTO")
    assert await stored(app) == {str(MAIN_BOT_ID): "TZPHOTO"}  # with the file id of the bot that received it
    assert await fsm_state(app, SUPER_ID) is None
    assert photo_panel(app, SUPER_ID)
    assert app.last_text(SUPER_ID).startswith("✅ Imagen guardada.\n\n🗺 <b>Zona horaria</b>")
    assert has_button(app, SUPER_ID, "🖼 Cambiar imagen") and has_button(app, SUPER_ID, "🗑 Quitar imagen")
    # Changing it: the prompt shows the current one.
    await app.click(SUPER_ID, "Cambiar imagen")
    assert photo_panel(app, SUPER_ID) and app.last_text(SUPER_ID) == PROMPT
    await app.send(SUPER_ID, None, photo="TZ2")
    assert await stored(app) == {str(MAIN_BOT_ID): "TZ2"}
    assert photo_panel(app, SUPER_ID, "TZ2")
    # Removing it.
    await app.click(SUPER_ID, "Quitar imagen")
    assert await stored(app) == {}
    assert last_answer(app)["text"] == "🗑 Imagen quitada."
    assert app.last_panel(SUPER_ID).method != "sendPhoto"
    assert has_button(app, SUPER_ID, "Poner imagen") and not has_button(app, SUPER_ID, "Quitar imagen")


async def test_only_super_admins_choose_the_photo(app: App) -> None:
    await add_clone(app)
    await open_timezone(app, OWNER2_ID, bot_id=CLONE_ID)  # the owner of a clone
    assert not has_button(app, OWNER2_ID, "imagen")
    await open_timezone(app, USER_ID)
    assert not has_button(app, USER_ID, "imagen")
    await put_photo(app)
    for user_id, bot_id in ((USER_ID, MAIN_BOT_ID), (OWNER2_ID, CLONE_ID)):
        for data in (TzCB(a="m").pack(), TzCB(a="x").pack()):  # forged buttons
            await app.press(user_id, data, bot_id=bot_id)
            assert denied(app), (user_id, data)
    await force_state(app, USER_ID, "StartTimezoneFSM:photo")  # an input nobody offered them
    await app.send(USER_ID, None, photo="EVIL")
    assert await fsm_state(app, USER_ID) is None
    assert await stored(app) == {str(MAIN_BOT_ID): "TZPHOTO"}


async def test_every_step_of_the_picker_shows_the_photo(app: App) -> None:
    await put_photo(app)
    await open_timezone(app, USER_ID)
    assert photo_panel(app, USER_ID) and app.last_text(USER_ID).startswith("🗺 <b>Zona horaria</b>")
    await app.click(USER_ID, "🌎 América")  # regions
    assert photo_panel(app, USER_ID) and "👇 Elige tu región:" in app.last_text(USER_ID)
    await app.click(USER_ID, "América del Norte")  # countries
    assert photo_panel(app, USER_ID) and "👇 Elige tu país:" in app.last_text(USER_ID)
    await app.click(USER_ID, "México")  # zones of a country with several
    assert photo_panel(app, USER_ID) and "👇 Elige tu zona horaria:" in app.last_text(USER_ID)
    for _ in range(3):
        await app.click(USER_ID, "Regresar")
    assert photo_panel(app, USER_ID) and has_button(app, USER_ID, "Escribir zona")  # back to the first screen
    await app.click(USER_ID, "Escribir zona")  # the typed zone too
    assert photo_panel(app, USER_ID) and has_button(app, USER_ID, "Cancelar")
    assert "✍️ <b>Escribir zona horaria</b>" in app.last_text(USER_ID)
    await app.send(USER_ID, "no/existe")
    assert photo_panel(app, USER_ID) and app.last_text(USER_ID).startswith("⚠️ Esa zona horaria no es válida")
    await app.send(USER_ID, "Asia/Tokyo")
    assert (await get_bu(app, USER_ID)).timezone == "Asia/Tokyo"
    assert app.last_panel(USER_ID).method == "sendMessage"  # the settings, without the photo


async def test_on_the_photo_only_the_caption_and_the_buttons_change(app: App) -> None:
    await put_photo(app)
    await open_timezone(app, USER_ID)
    sent = len(app.fake.calls_of("sendPhoto"))
    await app.feed(on_a_photo(app, USER_ID, TzCB(a="r").pack(), 77), MAIN_BOT_ID)
    call = app.last_panel(USER_ID)
    assert call.method == "editMessageCaption" and int(call.params["message_id"]) == 77
    assert call.params["caption"] == "<b>🌎 América</b>\n\n👇 Elige tu región:"
    assert len(app.fake.calls_of("sendPhoto")) == sent  # the photo is not sent again


async def test_cancel_on_the_typed_zone_turns_its_prompt_into_the_picker(app: App) -> None:
    await put_photo(app)
    await open_timezone(app, USER_ID)
    await app.click(USER_ID, "Escribir zona")
    prompt_id = int(app.fake.calls_of("sendPhoto", chat_id=USER_ID)[-1].result["message_id"])
    assert common._prompts[(MAIN_BOT_ID, USER_ID)] == prompt_id  # noqa: SLF001
    await app.feed(on_a_photo(app, USER_ID, InputCancelCB(screen="timezone").pack(), prompt_id), MAIN_BOT_ID)
    call = app.last_panel(USER_ID)
    assert call.method == "editMessageCaption" and int(call.params["message_id"]) == prompt_id
    assert call.params["caption"].startswith("🗺 <b>Zona horaria</b>")
    assert (MAIN_BOT_ID, USER_ID) not in common._prompts  # noqa: SLF001  (the prompt is the picker now)
    assert await fsm_state(app, USER_ID) is None


async def test_a_clone_gets_the_photo_through_the_main_bot_and_then_uses_its_own(app: App) -> None:
    await put_photo(app)
    await add_clone(app)
    await open_timezone(app, USER_ID, bot_id=CLONE_ID)
    call = app.last_panel(USER_ID)
    assert call.method == "sendPhoto" and call.params["photo"] != "TZPHOTO"  # another bot's file id can't be used
    assert app.fake.files[call.params["photo"]] == PHOTO  # downloaded through the main bot and uploaded
    own = call.result["photo"][-1]["file_id"]
    assert await stored(app) == {str(MAIN_BOT_ID): "TZPHOTO", str(CLONE_ID): own}
    await app.click(USER_ID, "Europa", bot_id=CLONE_ID)
    assert photo_panel(app, USER_ID, own)  # from now on, its own file id


async def test_a_photo_telegram_refuses_never_breaks_the_menu(app: App) -> None:
    await put_photo(app, "STALE")
    app.fake.fail("sendPhoto", description="Bad Request: wrong file identifier specified", times=2)
    await open_timezone(app, USER_ID)
    assert app.last_text(USER_ID).startswith("🗺 <b>Zona horaria</b>")
    assert app.last_panel(USER_ID).method == "sendMessage" and has_button(app, USER_ID, "Europa")
    await app.click(USER_ID, "Escribir zona")  # the prompt too, without the photo
    assert app.last_panel(USER_ID).method == "sendMessage" and has_button(app, USER_ID, "Cancelar")
    await app.send(USER_ID, "Asia/Tokyo")
    assert (await get_bu(app, USER_ID)).timezone == "Asia/Tokyo"


async def test_the_onboarding_shows_the_photo_without_its_buttons(app: App) -> None:
    await put_photo(app)
    await add_clone(app, owner_id=SUPER_ID, timezone_set=False)  # a super admin's own new clone
    await app.send(SUPER_ID, "/start", bot_id=CLONE_ID)
    call = app.last_panel(SUPER_ID)
    assert call.method == "sendPhoto"
    assert call.params["caption"].startswith("👋 <b>¡Te damos la bienvenida a tu bot!</b>")
    assert not has_button(app, SUPER_ID, "imagen") and not has_button(app, SUPER_ID, "Regresar")


@pytest.mark.ask_timezone
async def test_the_first_visit_question_shows_the_photo(app: App) -> None:
    await put_photo(app)
    await app.send(USER_ID, "/start")
    assert photo_panel(app, USER_ID) and app.last_text(USER_ID).startswith("👋 <b>¡Hola!</b> Antes de empezar")
    assert not has_button(app, USER_ID, "imagen")


async def test_while_managing_a_clone_the_photo_belongs_to_the_bot_that_received_it(app: App) -> None:
    await add_clone(app)
    await manage(app, SUPER_ID, CLONE_ID)
    await open_timezone(app, SUPER_ID)
    await app.click(SUPER_ID, "Poner imagen")
    await app.send(SUPER_ID, None, photo="WSPHOTO")
    assert await stored(app) == {str(MAIN_BOT_ID): "WSPHOTO"}  # the main bot received it
    assert photo_panel(app, SUPER_ID, "WSPHOTO")
    banner = f"🛠 Gestionando <b>@{CLONE_USERNAME}</b>\n\n"
    assert app.last_text(SUPER_ID).startswith(f"{banner}✅ Imagen guardada.")
    # On the photo, the caption keeps the banner too.
    await app.feed(on_a_photo(app, SUPER_ID, TzCB(a="r").pack(), 88, "WSPHOTO"), MAIN_BOT_ID)
    call = app.last_panel(SUPER_ID)
    assert call.method == "editMessageCaption" and call.params["caption"].startswith(f"{banner}<b>🌎 América</b>")


async def test_the_photo_buttons_in_english(app: App) -> None:
    app.fake.users[SUPER_ID]["language_code"] = "en"
    await app.send(SUPER_ID, "/start")
    await app.click(SUPER_ID, "Settings")
    await app.click(SUPER_ID, "Timezone")
    assert has_button(app, SUPER_ID, "🖼 Set image")
    await app.click(SUPER_ID, "Set image")
    assert app.last_text(SUPER_ID) == ("🖼 Send the <b>photo</b> that will be shown when this menu is opened, in "
                                       "every bot.")
    await app.send(SUPER_ID, "text")
    assert app.last_text(SUPER_ID).startswith("⚠️ That isn't a photo.")
