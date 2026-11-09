"""Start module: the 🖼 bot image (👑 › 🖼 Imagen del bot) on top of the home: in a main bot for everyone, in a clone
for its admins (not for its visitors). A button on that photo only changes its caption; another photo is replaced."""
from __future__ import annotations

from typing import Any

from app.bot.routers.start import StCB
from app.services import brand
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App

CLONE_ID = 6_400_000_001
IMAGE = "BOTIMG"


async def put_image(app: App) -> None:
    app.fake.files[IMAGE] = b"\xff\xd8JPEG-BOT"
    async with app.db() as s:
        await brand.set_photo(s, brand.BOT, MAIN_BOT_ID, IMAGE)


def on_a_photo(app: App, user_id: int, data: str, file_id: str, bot_id: int = MAIN_BOT_ID) -> dict[str, Any]:
    """A button press on a panel that is the photo ``file_id``."""
    update = app.callback_update(user_id, data, 77, bot_id=bot_id)
    message = update["callback_query"]["message"]
    del message["text"]
    message["photo"] = [{"file_id": file_id, "file_unique_id": f"u{file_id}", "width": 10, "height": 10}]
    message["caption"] = "panel"
    return update


async def test_the_main_bot_home_shows_the_image_to_visitors(app: App) -> None:
    await put_image(app)
    await app.send(USER_ID, "/start")
    call = app.last_panel(USER_ID)
    assert call.method == "sendPhoto" and call.params["photo"] == IMAGE
    assert call.params["caption"].startswith("👋 <b>¡Hola, Pepe!</b> Te damos la bienvenida a <b>eMesh</b>.")
    assert any("Crear mi bot" in b["text"] for b in app.buttons(call))


async def test_without_an_image_the_home_is_text(app: App) -> None:
    await app.send(USER_ID, "/start")
    assert app.last_panel(USER_ID).method == "sendMessage"


async def test_the_admins_home_shows_it_and_a_button_there_only_edits_the_caption(app: App) -> None:
    await put_image(app)
    await app.send(SUPER_ID, "/start")
    call = app.last_panel(SUPER_ID)
    assert call.method == "sendPhoto" and "Tu red de distribución" in call.params["caption"]
    await app.feed(on_a_photo(app, SUPER_ID, StCB(action="pause").pack(), IMAGE))
    call = app.last_panel(SUPER_ID)
    assert call.method == "editMessageCaption" and "La distribución está pausada" in call.params["caption"]


async def test_another_photo_is_replaced_by_the_image(app: App) -> None:
    await put_image(app)
    await app.send(SUPER_ID, "/start")
    await app.feed(on_a_photo(app, SUPER_ID, StCB(action="pause").pack(), "TZPHOTO"))  # e.g. the timezone menu
    call = app.last_panel(SUPER_ID)
    assert call.method == "sendPhoto" and call.params["photo"] == IMAGE


async def test_a_clone_shows_it_to_its_admins_only(app: App) -> None:
    from app.db.models import Bot as BotRecord

    await app.add_clone(CLONE_ID, "clon_cine_bot", OWNER2_ID)
    async with app.db() as s:
        (await s.get(BotRecord, CLONE_ID)).timezone_set = True  # its owner already chose the network's zone
    await put_image(app)
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    call = app.last_panel(OWNER2_ID)
    assert call.method == "sendPhoto" and "Tu red de distribución" in call.params["caption"]
    # The clone had no file id of it: uploaded once, then its own one is used.
    async with app.db() as s:
        ids = await brand.photo_ids(s, brand.BOT)
    assert ids[str(MAIN_BOT_ID)] == IMAGE and ids.get(str(CLONE_ID))
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    assert app.last_panel(OWNER2_ID).params["photo"] == ids[str(CLONE_ID)]

    await app.send(USER_ID, "/start", bot_id=CLONE_ID)  # a visitor of the clone: its own welcome, no image
    assert app.last_panel(USER_ID).method == "sendMessage"


async def test_an_image_telegram_refuses_is_left_out(app: App) -> None:
    await put_image(app)
    app.fake.fail("sendPhoto", description="Bad Request: wrong file identifier/HTTP URL specified")
    await app.send(USER_ID, "/start")
    call = app.last_panel(USER_ID)
    assert call.method == "sendMessage" and call.params["text"].startswith("👋 <b>¡Hola, Pepe!</b>")
