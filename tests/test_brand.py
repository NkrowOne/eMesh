"""🖼 Platform images (services/brand.py): per bot file ids; and the clones' profile photo, the eMesh logo bundled
with the app, given to every clone without a photo of its own."""
from __future__ import annotations

import hashlib

from aiogram.types import BufferedInputFile

from app.db.models import Bot as BotRecord
from app.db.models import BotStatus
from app.services import brand, kv
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, App

CLONE_ID = 7_000_000_001
CLONE2_ID = 7_000_000_002
CLONE3_ID = 7_000_000_003
PHOTO = b"\xff\xd8JPEG-PLATFORM"
AVATAR = brand.AVATAR_FILE.read_bytes()
MARK = f"asset:{hashlib.sha1(AVATAR).hexdigest()}"


async def stored(app: App, name: str) -> dict[str, str]:
    async with app.db() as s:
        return await brand.photo_ids(s, name)


async def put_photo(app: App, name: str = brand.TZ, file_id: str = "main_photo") -> None:
    app.fake.files[file_id] = PHOTO
    async with app.db() as s:
        await brand.set_photo(s, name, MAIN_BOT_ID, file_id)


async def test_no_image_means_no_photo(app: App) -> None:
    async with app.db() as s:
        assert await brand.photo_for(s, app.main_bot, brand.TZ, app.manager) is None
        assert not await brand.has_photo(s, brand.TZ)


async def test_each_bot_uses_its_own_file_id_or_downloads_it(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    await put_photo(app)
    clone = app.manager.get(CLONE_ID)
    assert clone is not None
    async with app.db() as s:
        assert await brand.photo_for(s, app.main_bot, brand.TZ, app.manager) == "main_photo"
        photo = await brand.photo_for(s, clone, brand.TZ, app.manager)
    assert isinstance(photo, BufferedInputFile) and photo.data == PHOTO
    assert brand.source_of(photo) == "main_photo"
    async with app.db() as s:
        await brand.remember(s, brand.TZ, CLONE_ID, "clone_photo", source=brand.source_of(photo))
    assert await stored(app, brand.TZ) == {str(MAIN_BOT_ID): "main_photo", str(CLONE_ID): "clone_photo"}
    async with app.db() as s:
        assert await brand.photo_for(s, clone, brand.TZ, app.manager) == "clone_photo"


async def test_an_upload_of_a_replaced_image_is_not_remembered(app: App) -> None:
    await put_photo(app)
    await put_photo(app, file_id="newer_photo")
    async with app.db() as s:
        await brand.remember(s, brand.TZ, CLONE_ID, "clone_photo", source="main_photo")
    assert await stored(app, brand.TZ) == {str(MAIN_BOT_ID): "newer_photo"}


async def given(app: App, bot_id: int) -> object:
    async with app.db() as s:
        return await kv.get(s, f"photo:bot:{bot_id}")


def uploads(app: App) -> int:
    return len(app.fake.calls_of("setMyProfilePhoto"))


def jpeg_size(raw: bytes) -> tuple[int, int]:
    """(width, height) of a JPEG, from its SOF segment."""
    i = 2
    while i < len(raw):
        marker, length = raw[i + 1], int.from_bytes(raw[i + 2:i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(raw[i + 7:i + 9], "big"), int.from_bytes(raw[i + 5:i + 7], "big")
        i += 2 + length
    raise AssertionError("no SOF segment")


def test_the_avatar_is_the_bundled_square_logo() -> None:
    raw, mark = brand.avatar()
    assert brand.AVATAR_FILE.parent.name == "assets" and brand.AVATAR_FILE.parent.parent.name == "app"
    assert raw == AVATAR and raw.startswith(b"\xff\xd8") and mark == MARK
    width, height = jpeg_size(raw)
    assert width == height  # Telegram crops profile photos into a circle


async def test_a_clone_gets_the_avatar_unless_it_has_its_own(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    await app.add_clone(CLONE2_ID, "clon2_bot", OWNER2_ID)
    app.fake.profile_photos[CLONE2_ID] = "owner_photo"  # its owner put one in @BotFather
    await put_photo(app, brand.BOT)  # the platform's image is not a profile photo
    assert await brand.give_to_clone(app.manager, app.sm, CLONE_ID) == "set"
    assert app.fake.profile_uploads[CLONE_ID] == AVATAR
    assert await brand.give_to_clone(app.manager, app.sm, CLONE2_ID) == "own"
    assert CLONE2_ID not in app.fake.profile_uploads and app.fake.profile_photos[CLONE2_ID] == "owner_photo"
    assert await brand.give_to_clone(app.manager, app.sm, MAIN_BOT_ID) == "none"
    assert MAIN_BOT_ID not in app.fake.profile_uploads
    assert await given(app, CLONE_ID) == {"uid": app.fake.profile_photos[CLONE_ID], "src": MARK}
    assert uploads(app) == 1


async def test_a_clone_without_a_platform_image_gets_it_too(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    assert await brand.give_to_clone(app.manager, app.sm, CLONE_ID) == "set"
    assert app.fake.profile_uploads[CLONE_ID] == AVATAR


async def test_a_clone_that_already_shows_the_avatar_gets_nothing_again(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    assert await brand.give_to_clone(app.manager, app.sm, CLONE_ID) == "set"
    done = uploads(app)
    assert await brand.give_to_clone(app.manager, app.sm, CLONE_ID) == "same"  # e.g. it was paused and resumed
    assert uploads(app) == done


async def test_a_clone_showing_an_old_platform_image_gets_the_avatar(app: App) -> None:
    """The platform's image was given as a profile photo before: the clone that still shows it gets the logo."""
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    app.fake.profile_photos[CLONE_ID] = "old_platform_uid"
    async with app.db() as s:
        await kv.put(s, f"photo:bot:{CLONE_ID}", {"uid": "old_platform_uid", "src": "main_photo"})
    assert await brand.give_to_clone(app.manager, app.sm, CLONE_ID) == "set"
    assert app.fake.profile_uploads[CLONE_ID] == AVATAR
    assert await given(app, CLONE_ID) == {"uid": app.fake.profile_photos[CLONE_ID], "src": MARK}


async def test_a_photo_given_but_not_read_back_counts_as_ours(app: App) -> None:
    """Right after an upload Telegram may not return the new photo yet: the clone got it from us all the same."""
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    app.fake.profile_photos[CLONE_ID] = "old_platform_uid"
    async with app.db() as s:
        await kv.put(s, f"photo:bot:{CLONE_ID}", {"uid": None, "src": "main_photo"})
    assert await brand.give_to_clone(app.manager, app.sm, CLONE_ID) == "set"
    assert app.fake.profile_uploads[CLONE_ID] == AVATAR


async def test_a_new_logo_file_is_given_again(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    app.fake.profile_photos[CLONE_ID] = "older_logo_uid"
    async with app.db() as s:
        await kv.put(s, f"photo:bot:{CLONE_ID}", {"uid": "older_logo_uid", "src": "asset:0123abcd"})
    assert await brand.give_to_clone(app.manager, app.sm, CLONE_ID) == "set"
    assert app.fake.profile_uploads[CLONE_ID] == AVATAR


async def test_a_refused_photo_counts_as_failed(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    app.fake.fail("setMyProfilePhoto", description="Bad Request: PHOTO_INVALID_DIMENSIONS")
    assert await brand.give_to_clone(app.manager, app.sm, CLONE_ID) == "failed"
    assert CLONE_ID not in app.fake.profile_uploads and await given(app, CLONE_ID) is None
    assert await brand.give_to_clone(app.manager, app.sm, CLONE_ID) == "set"  # tried again next time


async def test_the_running_clones_get_it_at_startup_once(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    await app.add_clone(CLONE2_ID, "clon2_bot", OWNER2_ID)
    await app.add_clone(CLONE3_ID, "clon3_bot", OWNER2_ID)
    app.fake.profile_photos[CLONE2_ID] = "owner_photo"
    await app.manager.disable_bot(CLONE3_ID)  # stopped: it gets it when it runs again
    async with app.db() as s:
        assert (await s.get(BotRecord, CLONE3_ID)).status == BotStatus.DISABLED
    assert await brand.give_to_running_clones(app.manager, app.sm) == {"set": 1, "own": 1}
    assert app.fake.profile_uploads == {CLONE_ID: AVATAR}  # never a main bot

    done = uploads(app)
    assert await brand.give_to_running_clones(app.manager, app.sm) == {"same": 1, "own": 1}  # the next restart
    assert uploads(app) == done


async def test_one_clone_failing_at_startup_doesnt_stop_the_others(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    await app.add_clone(CLONE2_ID, "clon2_bot", OWNER2_ID)
    app.fake.fail("getUserProfilePhotos", when=lambda p: p.get("user_id") == CLONE_ID)
    assert await brand.give_to_running_clones(app.manager, app.sm) == {"failed": 1, "set": 1}
    assert app.fake.profile_uploads == {CLONE2_ID: AVATAR}
