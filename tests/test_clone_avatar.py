"""Clones module: every clone's profile photo is the eMesh logo bundled with the app (app/assets/clone_avatar.jpg), not
the 👑 › 🖼 Imagen del bot: a new clone as soon as it runs (token or Managed Bots), a pending one when it is approved,
a stopped one when it runs again; plus the line about it on the clone screen. The service: tests/test_brand.py."""
from __future__ import annotations

from app.bot.routers.clone import CloneCB
from app.bot.routers.panel import PanelCB
from app.services import brand, kv
from tests.conftest import MAIN_BOT_ID, SUPER_ID, USER_ID, App
from tests.test_clone import managed_update, open_clone, set_policy

CLONE_ID = 6_500_000_001
CLONE_USERNAME = "pepe_logo_bot"
AVATAR = brand.AVATAR_FILE.read_bytes()
LINE = "🖼 Tu bot se crea con el logo de eMesh como foto; puedes cambiarla cuando quieras en @BotFather."


async def idle(app: App) -> None:
    """The background work of the profile photos is over."""
    await app.wait_for(lambda: not brand._tasks)  # noqa: SLF001


def uploads(app: App) -> int:
    return len(app.fake.calls_of("setMyProfilePhoto"))


async def put_image(app: App) -> None:
    """A platform image (👑 › 🖼 Imagen del bot): it never becomes a profile photo."""
    app.fake.files["AgADbanner"] = b"\xff\xd8JPEG-BANNER"
    async with app.db() as s:
        await brand.set_photo(s, brand.BOT, MAIN_BOT_ID, "AgADbanner")


async def connect(app: App, bot_id: int = CLONE_ID, username: str = CLONE_USERNAME) -> None:
    token = app.fake.add_bot(bot_id, username)
    await open_clone(app)
    await app.click(USER_ID, "Usar token")
    await app.send(USER_ID, token)


async def test_a_new_clone_gets_the_logo(app: App) -> None:
    await put_image(app)
    await connect(app)
    assert "está listo" in app.last_text(USER_ID)
    await app.wait_for(lambda: app.fake.profile_uploads.get(CLONE_ID) == AVATAR)
    await idle(app)
    assert MAIN_BOT_ID not in app.fake.profile_uploads

    # ... also when it is created with Telegram (Managed Bots), and with no platform image at all
    async with app.db() as s:
        await brand.clear_photo(s, brand.BOT)
    new_id = 6_500_000_777
    app.fake.managed_tokens[new_id] = app.fake.add_bot(new_id, "pepe_mesh_bot")
    await app.feed(managed_update(app, USER_ID, new_id))
    await app.wait_for(lambda: app.fake.profile_uploads.get(new_id) == AVATAR)
    await idle(app)


async def test_a_new_clone_with_a_photo_of_its_own_keeps_it(app: App) -> None:
    app.fake.profile_photos[CLONE_ID] = "owner_photo"  # its owner put one in @BotFather before connecting it
    await connect(app)
    assert "está listo" in app.last_text(USER_ID)
    await app.wait_for(lambda: app.fake.calls_of("getUserProfilePhotos", user_id=CLONE_ID))
    await idle(app)
    assert not app.fake.calls_of("setMyProfilePhoto") and app.fake.profile_photos[CLONE_ID] == "owner_photo"


async def test_a_pending_clone_gets_the_logo_when_approved(app: App) -> None:
    await set_policy(app, "approval")
    await connect(app)
    assert "pendiente de aprobación" in app.last_text(USER_ID)
    assert not brand._tasks and CLONE_ID not in app.fake.profile_uploads  # noqa: SLF001

    await app.press(SUPER_ID, PanelCB(action="ok", id=CLONE_ID).pack())
    await app.wait_for(lambda: app.fake.profile_uploads.get(CLONE_ID) == AVATAR)
    await idle(app)


async def test_a_clone_started_again_gets_the_logo_once(app: App) -> None:
    """A clone that still shows an old platform image we gave gets the logo when it runs again (owner or super
    admin), and one that already shows it isn't sent it again."""
    await app.add_clone(CLONE_ID, CLONE_USERNAME, USER_ID)
    app.fake.profile_photos[CLONE_ID] = "old_platform_uid"
    async with app.db() as s:
        await kv.put(s, f"photo:bot:{CLONE_ID}", {"uid": "old_platform_uid", "src": "AgADbanner"})
    await app.send(USER_ID, "/start")
    await app.press(USER_ID, CloneCB(action="pause", id=CLONE_ID).pack())
    await app.wait_for(lambda: not app.manager.is_running(CLONE_ID))
    await app.press(USER_ID, CloneCB(action="resume", id=CLONE_ID).pack())
    await app.wait_for(lambda: app.fake.profile_uploads.get(CLONE_ID) == AVATAR)
    await idle(app)

    done = uploads(app)
    await app.press(SUPER_ID, PanelCB(action="off", id=CLONE_ID).pack())
    await app.wait_for(lambda: not app.manager.is_running(CLONE_ID))
    await app.press(SUPER_ID, PanelCB(action="on", id=CLONE_ID).pack())
    assert app.manager.is_running(CLONE_ID)
    await idle(app)
    assert uploads(app) == done  # it already shows the logo


async def test_the_clone_screen_tells_new_bots_get_the_logo(app: App) -> None:
    assert LINE in await open_clone(app)  # with or without a platform image
    await set_policy(app, "closed")  # no new bots: nothing to tell
    assert LINE not in await open_clone(app)
