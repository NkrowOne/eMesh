"""Clones module: 👑 › 🖼 Imagen del bot (set by a super admin): only the photo on top of the home, in the main bots
and the clones. It changes no profile photo (the clones' one is the eMesh logo: tests/test_clone_avatar.py)."""
from __future__ import annotations

from aiogram.fsm.storage.base import StorageKey

from app.bot.routers.panel import PanelCB, PanelFSM
from app.services import brand
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, MAIN_BOT_USERNAME, OWNER2_ID, SUPER_ID, USER_ID, App

CLONE_ID = 6_300_000_001
CLONE2_ID = 6_300_000_002
CLONE_USERNAME = "pepe_cine_bot"
PHOTO = b"\xff\xd8JPEG-PLATFORM"
FILE_ID = "AgADbrand"
ASK = "🖼 Envía la <b>foto</b> que saldrá arriba del inicio (como foto, no como archivo)."
SCREEN = (
    "🖼 <b>Imagen del bot</b>\n\n"
    f"Sale arriba del mensaje de inicio de @{MAIN_BOT_USERNAME} y, en los clones, arriba del inicio de sus admins.\n"
    "   └ No cambia ninguna foto de perfil: la de los clones es siempre el logo de eMesh."
)


def answer_text(app: App) -> str:
    call = app.fake.last("answerCallbackQuery")
    return str(call.params.get("text", "")) if call else ""


def button_texts(app: App, chat_id: int = SUPER_ID) -> list[str]:
    return [b["text"] for b in app.buttons(app.last_panel(chat_id))]


def key(user_id: int, bot_id: int = MAIN_BOT_ID) -> StorageKey:
    return StorageKey(bot_id=bot_id, chat_id=user_id, user_id=user_id)


async def put_image(app: App, bot_id: int = MAIN_BOT_ID, file_id: str = FILE_ID) -> None:
    """An image already set (``file_id`` of the bot ``bot_id``)."""
    app.fake.files[file_id] = PHOTO
    async with app.db() as s:
        await brand.set_photo(s, brand.BOT, bot_id, file_id)


async def stored(app: App) -> dict[str, str]:
    async with app.db() as s:
        return await brand.photo_ids(s, brand.BOT)


async def open_photo(app: App) -> str:
    await app.send(SUPER_ID, "/start")
    await app.press(SUPER_ID, MenuCB(screen="panel").pack())
    await app.click(SUPER_ID, "Imagen del bot")
    return app.last_text(SUPER_ID)


async def send_photo(app: App, user_id: int = SUPER_ID, file_id: str = FILE_ID, bot_id: int = MAIN_BOT_ID) -> None:
    await app.feed(app.message_update(user_id, photo=file_id), bot_id)


# ------------------------------------------------------------------------ screen
async def test_the_screen_without_an_image(app: App) -> None:
    await app.send(SUPER_ID, "/start")
    await app.press(SUPER_ID, MenuCB(screen="panel").pack())
    button, _ = app.find_button(SUPER_ID, "🖼 Imagen del bot")
    assert button["callback_data"] == MenuCB(screen="panel_photo").pack()

    await app.press(SUPER_ID, button["callback_data"])
    text = app.last_text(SUPER_ID)
    assert text == f"{SCREEN}\n\n📌 Ahora no hay ninguna imagen."
    assert button_texts(app) == ["🖼 Poner imagen", "🔙 Regresar"]  # nothing to delete
    put, _ = app.find_button(SUPER_ID, "Poner imagen")
    assert put["style"] == "primary" and put["callback_data"] == PanelCB(action="photo").pack()
    assert app.find_button(SUPER_ID, "Regresar")[0]["callback_data"] == MenuCB(screen="panel").pack()
    assert not app.fake.calls_of("sendPhoto")


async def test_the_screen_shows_the_image_on_top(app: App) -> None:
    await put_image(app)
    text = await open_photo(app)
    panel = app.last_panel(SUPER_ID)
    assert panel.method == "sendPhoto" and panel.params["photo"] == FILE_ID
    assert text == SCREEN
    assert button_texts(app) == ["🖼 Cambiar imagen", "🔙 Regresar"]


async def test_an_image_telegram_refuses_is_left_out(app: App) -> None:
    await put_image(app)
    await app.send(SUPER_ID, "/start")
    await app.press(SUPER_ID, MenuCB(screen="panel").pack())
    app.fake.fail("sendPhoto", description="Bad Request: wrong file identifier/HTTP URL specified")
    await app.click(SUPER_ID, "Imagen del bot")
    panel = app.last_panel(SUPER_ID)
    assert panel.method == "sendMessage" and "🖼 <b>Imagen del bot</b>" in panel.params["text"]
    assert button_texts(app) == ["🖼 Cambiar imagen", "🔙 Regresar"]


async def test_a_main_bot_without_its_own_file_id_uploads_the_image_once(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    await put_image(app, CLONE_ID, "clone_photo")  # only another bot has a file id of it
    await open_photo(app)
    upload = app.last_panel(SUPER_ID)
    assert upload.method == "sendPhoto" and app.fake.files[upload.params["photo"]] == PHOTO
    assert await stored(app) == {str(CLONE_ID): "clone_photo", str(MAIN_BOT_ID): upload.params["photo"]}

    await app.press(SUPER_ID, MenuCB(screen="panel_photo").pack())
    assert app.last_panel(SUPER_ID).params["photo"] == upload.params["photo"]  # its own file id now


# --------------------------------------------------------------------- set it
async def test_setting_the_image_changes_no_profile_photo(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_uno_bot", OWNER2_ID)
    await app.add_clone(CLONE2_ID, "clon_dos_bot", OWNER2_ID)
    app.fake.profile_photos[CLONE2_ID] = "owner_photo"
    await open_photo(app)
    await app.click(SUPER_ID, "Poner imagen")
    assert app.last_text(SUPER_ID) == ASK
    assert app.find_button(SUPER_ID, "Cancelar")

    await app.send(SUPER_ID, "aquí va")
    not_a_photo = "⚠️ Eso no es una foto. Envíala como foto, no como archivo."
    assert app.last_text(SUPER_ID).startswith(f"{not_a_photo}\n\n{ASK}")
    await app.feed(app.message_update(SUPER_ID, video="AgADvideo"))
    assert app.last_text(SUPER_ID).startswith(not_a_photo)

    app.fake.files[FILE_ID] = PHOTO
    await send_photo(app)
    assert await stored(app) == {str(MAIN_BOT_ID): FILE_ID}
    assert await app.storage.get_state(key(SUPER_ID)) is None
    panel = app.last_panel(SUPER_ID)
    assert panel.method == "sendPhoto" and panel.params["photo"] == FILE_ID
    assert panel.params["caption"] == f"✅ Imagen puesta.\n\n{SCREEN}"
    assert button_texts(app) == ["🖼 Cambiar imagen", "🔙 Regresar"]
    # Only stored: no profile photo changes (main bot or clones) and nothing runs in the background.
    assert not brand._tasks  # noqa: SLF001
    assert not app.fake.calls_of("setMyProfilePhoto") and not app.fake.calls_of("getUserProfilePhotos")
    assert app.fake.profile_uploads == {} and app.fake.profile_photos == {CLONE2_ID: "owner_photo"}

    # it is the photo on top of the home now
    await app.send(USER_ID, "/start")
    home = app.last_panel(USER_ID)
    assert home.method == "sendPhoto" and home.params["photo"] == FILE_ID

    # a command still works while the photo is asked
    await app.click(SUPER_ID, "Cambiar imagen")
    await app.send(SUPER_ID, "/start")
    assert await app.storage.get_state(key(SUPER_ID)) is None
    assert "Tu red de distribución" in app.last_text(SUPER_ID)
    assert await stored(app) == {str(MAIN_BOT_ID): FILE_ID}


async def test_changing_the_image(app: App) -> None:
    await put_image(app)
    await open_photo(app)
    await app.click(SUPER_ID, "Cambiar imagen")
    app.fake.files["AgADnewer"] = b"\xff\xd8JPEG-NEWER"
    await send_photo(app, file_id="AgADnewer")
    assert await stored(app) == {str(MAIN_BOT_ID): "AgADnewer"}  # the file ids of the previous one are forgotten
    assert app.last_panel(SUPER_ID).params["photo"] == "AgADnewer"
    assert not app.fake.calls_of("setMyProfilePhoto")


async def test_a_photo_that_cant_be_read_stores_nothing(app: App) -> None:
    await open_photo(app)
    await app.click(SUPER_ID, "Poner imagen")
    app.fake.fail("getFile")
    await send_photo(app)
    assert app.last_text(SUPER_ID).startswith(f"⚠️ No se ha podido leer la foto. Prueba con otra.\n\n{ASK}")
    assert await stored(app) == {}
    assert await app.storage.get_state(key(SUPER_ID)) == PanelFSM.photo.state  # still asked


# ------------------------------------------------------------------ permissions
async def test_only_super_admins_in_main_bots(app: App) -> None:
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    await app.send(USER_ID, "/start")
    await app.press(USER_ID, MenuCB(screen="panel_photo").pack())
    assert "permiso" in answer_text(app)
    await app.press(USER_ID, PanelCB(action="photo").pack())
    assert "permiso" in answer_text(app)
    assert await app.storage.get_state(key(USER_ID)) is None
    await app.storage.set_state(key(USER_ID), PanelFSM.photo)  # a forged input
    await send_photo(app, USER_ID)
    assert await app.storage.get_state(key(USER_ID)) is None

    # a super admin finds it in the main bots only
    await app.press(SUPER_ID, MenuCB(screen="panel_photo").pack(), bot_id=CLONE_ID)
    assert "permiso" in answer_text(app)
    await app.press(SUPER_ID, PanelCB(action="photo").pack(), bot_id=CLONE_ID)
    assert "permiso" in answer_text(app)
    await app.storage.set_state(key(SUPER_ID, CLONE_ID), PanelFSM.photo)
    await send_photo(app, SUPER_ID, bot_id=CLONE_ID)
    assert await app.storage.get_state(key(SUPER_ID, CLONE_ID)) is None

    assert not app.fake.calls_of("getFile") and not app.fake.calls_of("setMyProfilePhoto")
    assert await stored(app) == {}
