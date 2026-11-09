"""Clones module: 👑 › 🖼 Imagen del bot (the profile photo of the main bots, set by a super admin) and the clones
that get it: every clone without a photo of its own when it changes, a new clone as soon as it runs, a pending one
when it is approved; plus the line about it on the clone screen."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiogram.fsm.storage.base import StorageKey

from app.bot.routers import panel
from app.bot.routers.panel import PanelCB, PanelFSM
from app.services import brand
from app.ui.callbacks import MenuCB
from tests.conftest import MAIN_BOT_ID, MAIN_BOT_USERNAME, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_clone import managed_update, open_clone, set_policy

CLONE_ID = 6_300_000_001
CLONE2_ID = 6_300_000_002
CLONE3_ID = 6_300_000_003
CLONE_USERNAME = "pepe_cine_bot"
PHOTO = b"\xff\xd8JPEG-PLATFORM"
FILE_ID = "AgADbrand"
ASK = "🖼 Envía la <b>foto</b> del bot (como foto, no como archivo)."


@pytest.fixture(autouse=True)
def _no_photo_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts without an image on its way to the clones (a job of another test's event loop)."""
    monkeypatch.setattr(panel, "_photo_job", None)


def answer_text(app: App) -> str:
    call = app.fake.last("answerCallbackQuery")
    return str(call.params.get("text", "")) if call else ""


def button_texts(app: App, chat_id: int = SUPER_ID) -> list[str]:
    return [b["text"] for b in app.buttons(app.last_panel(chat_id))]


def dms(app: App, chat_id: int) -> list[str]:
    """Texts sent by the main bot to a private chat."""
    return [str(c.params.get("text", "")) for c in app.fake.calls_of("sendMessage", chat_id=chat_id)
            if c.token == app.settings.BOT_TOKEN]


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


async def idle(app: App) -> None:
    """The background work of the platform images is over."""
    await app.wait_for(lambda: not brand._tasks)  # noqa: SLF001


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
    assert text == (
        "🖼 <b>Imagen del bot</b>\n\n"
        f"Sale arriba del mensaje de inicio de @{MAIN_BOT_USERNAME} y es su foto de perfil.\n"
        "   └ Los clones también la llevan: en el inicio de sus admins y como foto de perfil, si no tienen una "
        "propia.\n\n"
        "📌 Ahora no hay ninguna imagen."
    )
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
    assert text.startswith("🖼 <b>Imagen del bot</b>") and "Ahora no hay" not in text
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
async def test_setting_the_image(app: App) -> None:
    await open_photo(app)
    await app.click(SUPER_ID, "Poner imagen")
    assert app.last_text(SUPER_ID) == f"{ASK}\n   └ Mejor cuadrada: Telegram la recorta en un círculo."
    assert app.find_button(SUPER_ID, "Cancelar")

    await app.send(SUPER_ID, "aquí va")
    not_a_photo = "⚠️ Eso no es una foto. Envíala como foto, no como archivo."
    assert app.last_text(SUPER_ID).startswith(f"{not_a_photo}\n\n{ASK}")
    await app.feed(app.message_update(SUPER_ID, video="AgADvideo"))
    assert app.last_text(SUPER_ID).startswith(not_a_photo)
    assert not app.fake.calls_of("setMyProfilePhoto")

    app.fake.files[FILE_ID] = PHOTO
    await send_photo(app)
    assert app.fake.profile_uploads[MAIN_BOT_ID] == PHOTO
    assert await stored(app) == {str(MAIN_BOT_ID): FILE_ID}
    assert await app.storage.get_state(key(SUPER_ID)) is None
    panel = app.last_panel(SUPER_ID)
    assert panel.method == "sendPhoto" and panel.params["photo"] == FILE_ID
    assert panel.params["caption"].startswith(
        f"✅ Imagen puesta en @{MAIN_BOT_USERNAME}.\n\n🖼 <b>Imagen del bot</b>")
    assert "se actualizan ahora" not in panel.params["caption"]  # there are no clones: no job
    assert not brand._tasks  # noqa: SLF001
    assert button_texts(app) == ["🖼 Cambiar imagen", "🔙 Regresar"]

    # a command still works while the photo is asked
    await app.click(SUPER_ID, "Cambiar imagen")
    await app.send(SUPER_ID, "/start")
    assert await app.storage.get_state(key(SUPER_ID)) is None
    assert "Tu red de distribución" in app.last_text(SUPER_ID)
    assert len(app.fake.calls_of("setMyProfilePhoto")) == 1


async def test_a_photo_that_cant_be_used_stores_nothing(app: App) -> None:
    await open_photo(app)
    await app.click(SUPER_ID, "Poner imagen")
    app.fake.fail("getFile")
    await send_photo(app)
    assert app.last_text(SUPER_ID).startswith(f"⚠️ No se ha podido leer la foto. Prueba con otra.\n\n{ASK}")

    app.fake.fail("setMyProfilePhoto", description="Bad Request: PHOTO_INVALID_DIMENSIONS")
    await send_photo(app)
    assert app.last_text(SUPER_ID).startswith(
        f"⚠️ Telegram no ha aceptado la foto (Bad Request: PHOTO_INVALID_DIMENSIONS). Prueba con otra.\n\n{ASK}")
    assert await stored(app) == {} and MAIN_BOT_ID not in app.fake.profile_uploads
    assert await app.storage.get_state(key(SUPER_ID)) == PanelFSM.photo.state  # still asked


async def test_the_clones_get_the_new_image_and_a_report_follows(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_uno_bot", OWNER2_ID)
    await app.add_clone(CLONE2_ID, "clon_dos_bot", OWNER2_ID)
    await app.add_clone(CLONE3_ID, "clon_tres_bot", USER_ID)
    app.fake.profile_photos[CLONE2_ID] = "owner_photo"  # its owner put one in @BotFather
    app.fake.fail("getUserProfilePhotos", when=lambda p: p.get("user_id") == CLONE3_ID)
    await open_photo(app)
    await app.click(SUPER_ID, "Poner imagen")
    app.fake.files[FILE_ID] = PHOTO
    await send_photo(app)
    caption = app.fake.last("sendPhoto", chat_id=SUPER_ID).params["caption"]
    assert caption.startswith(f"✅ Imagen puesta en @{MAIN_BOT_USERNAME}. Los clones se actualizan ahora; se te "
                              "avisará al terminar.\n\n🖼 <b>Imagen del bot</b>")

    await app.wait_for(lambda: any("Imagen del bot puesta" in t for t in dms(app, SUPER_ID)))
    await idle(app)
    report = next(t for t in dms(app, SUPER_ID) if "Imagen del bot puesta" in t)
    assert report == ("🖼 <b>Imagen del bot puesta</b>\n🤖 Clones actualizados: <b>1</b>\n"
                      "🖼 Con foto propia (no se cambian): <b>1</b>\n⚠️ Con error: <b>1</b>")
    assert app.fake.profile_uploads[CLONE_ID] == PHOTO
    assert CLONE2_ID not in app.fake.profile_uploads and CLONE3_ID not in app.fake.profile_uploads
    assert app.fake.profile_photos[CLONE2_ID] == "owner_photo"


async def test_a_newer_image_waits_for_the_previous_one(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    """The wrong photo and right away the good one: the clones end up with the good one."""
    await app.add_clone(CLONE_ID, CLONE_USERNAME, OWNER2_ID)
    release = asyncio.Event()
    give = brand.give_to_clones
    started: list[bytes] = []

    async def slow_first(manager: Any, sm: Any, raw: bytes, source: str) -> brand.Given:
        started.append(raw)
        if len(started) == 1:
            await release.wait()  # the first image is still on its way when the second one arrives
        return await give(manager, sm, raw, source)

    monkeypatch.setattr(brand, "give_to_clones", slow_first)
    newer = b"\xff\xd8JPEG-NEWER"
    app.fake.files[FILE_ID] = PHOTO
    app.fake.files["AgADnewer"] = newer
    await open_photo(app)
    await app.click(SUPER_ID, "Poner imagen")
    await send_photo(app)
    await app.click(SUPER_ID, "Cambiar imagen")
    await send_photo(app, file_id="AgADnewer")
    assert app.fake.profile_uploads[MAIN_BOT_ID] == newer
    assert await stored(app) == {str(MAIN_BOT_ID): "AgADnewer"}
    assert started == [PHOTO]  # the newer image waits for the previous one

    release.set()
    await app.wait_for(lambda: len([t for t in dms(app, SUPER_ID) if "Imagen del bot puesta" in t]) == 2)
    await idle(app)
    assert started == [PHOTO, newer]
    assert app.fake.profile_uploads[CLONE_ID] == newer


# -------------------------------------------------------------- clones get it
async def test_a_new_clone_gets_the_image(app: App) -> None:
    await put_image(app)
    token = app.fake.add_bot(CLONE_ID, CLONE_USERNAME)
    await open_clone(app)
    await app.click(USER_ID, "Usar token")
    await app.send(USER_ID, token)
    assert "está listo" in app.last_text(USER_ID)
    await app.wait_for(lambda: app.fake.profile_uploads.get(CLONE_ID) == PHOTO)
    await idle(app)

    # ... also when it is created with Telegram (Managed Bots)
    new_id = 6_300_000_777
    app.fake.managed_tokens[new_id] = app.fake.add_bot(new_id, "pepe_mesh_bot")
    await app.feed(managed_update(app, USER_ID, new_id))
    await app.wait_for(lambda: app.fake.profile_uploads.get(new_id) == PHOTO)
    await idle(app)


async def test_a_new_clone_without_an_image_starts_no_job(app: App) -> None:
    token = app.fake.add_bot(CLONE_ID, CLONE_USERNAME)
    await open_clone(app)
    await app.click(USER_ID, "Usar token")
    await app.send(USER_ID, token)
    assert "está listo" in app.last_text(USER_ID)
    assert not brand._tasks and not app.fake.calls_of("setMyProfilePhoto")  # noqa: SLF001


async def test_a_pending_clone_gets_the_image_when_approved(app: App) -> None:
    await set_policy(app, "approval")
    await put_image(app)
    token = app.fake.add_bot(CLONE_ID, CLONE_USERNAME)
    await open_clone(app)
    await app.click(USER_ID, "Usar token")
    await app.send(USER_ID, token)
    assert "pendiente de aprobación" in app.last_text(USER_ID)
    assert not brand._tasks and CLONE_ID not in app.fake.profile_uploads  # noqa: SLF001

    await app.press(SUPER_ID, PanelCB(action="ok", id=CLONE_ID).pack())
    assert "Bot aprobado" in answer_text(app)
    assert "en un minuto lo dejas a punto" in dms(app, USER_ID)[-1]
    await app.wait_for(lambda: app.fake.profile_uploads.get(CLONE_ID) == PHOTO)
    await idle(app)


async def test_a_clone_started_again_gets_the_image_it_missed(app: App) -> None:
    """A clone that was stopped when the image changed gets it when it runs again (owner or super admin), and one
    that already shows it isn't sent it again."""
    from app.bot.routers.clone import CloneCB

    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    await app.send(USER_ID, "/start")
    await app.press(USER_ID, CloneCB(action="pause", id=CLONE_ID).pack())
    await app.wait_for(lambda: not app.manager.is_running(CLONE_ID))
    await put_image(app)  # set while it was paused: nothing reaches it
    await app.press(USER_ID, CloneCB(action="resume", id=CLONE_ID).pack())
    await app.wait_for(lambda: app.fake.profile_uploads.get(CLONE_ID) == PHOTO)
    await idle(app)

    uploads = len(app.fake.calls_of("setMyProfilePhoto"))
    await app.press(SUPER_ID, PanelCB(action="off", id=CLONE_ID).pack())
    await app.wait_for(lambda: not app.manager.is_running(CLONE_ID))
    await app.press(SUPER_ID, PanelCB(action="on", id=CLONE_ID).pack())
    assert app.manager.is_running(CLONE_ID)
    await idle(app)
    assert len(app.fake.calls_of("setMyProfilePhoto")) == uploads  # it already shows this image


async def test_the_clone_screen_tells_new_bots_get_the_image(app: App) -> None:
    line = "🖼 Tu bot se crea con la imagen de la plataforma; puedes cambiarla cuando quieras en @BotFather."
    assert line not in await open_clone(app)
    await put_image(app)
    assert line in await open_clone(app)
    await set_policy(app, "closed")  # no new bots: nothing to tell
    assert line not in await open_clone(app)


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
