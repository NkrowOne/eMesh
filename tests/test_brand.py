"""🖼 Platform images (services/brand.py): per bot file ids, the profile photo of the main bots and of the clones
without a photo of their own."""
from __future__ import annotations

from aiogram.types import BufferedInputFile

from app.services import brand, kv
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, App

CLONE_ID = 7_000_000_001
CLONE2_ID = 7_000_000_002
PHOTO = b"\xff\xd8JPEG-PLATFORM"


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


async def test_the_main_bots_get_the_profile_photo(app: App) -> None:
    assert await brand.set_main_photos(app.manager, PHOTO) == 1
    assert app.fake.profile_uploads[MAIN_BOT_ID] == PHOTO
    assert MAIN_BOT_ID in app.fake.profile_photos


async def test_a_clone_gets_the_image_unless_it_has_its_own(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    await app.add_clone(CLONE2_ID, "clon2_bot", OWNER2_ID)
    app.fake.profile_photos[CLONE2_ID] = "owner_photo"  # its owner put one in @BotFather
    await put_photo(app, brand.BOT)
    assert await brand.give_to_clone(app.manager, app.sm, CLONE_ID) == "set"
    assert app.fake.profile_uploads[CLONE_ID] == PHOTO
    assert await brand.give_to_clone(app.manager, app.sm, CLONE2_ID) == "own"
    assert CLONE2_ID not in app.fake.profile_uploads
    assert await brand.give_to_clone(app.manager, app.sm, MAIN_BOT_ID) == "none"
    async with app.db() as s:
        assert await kv.get(s, f"photo:bot:{CLONE_ID}") == app.fake.profile_photos[CLONE_ID]


async def test_a_new_image_reaches_the_clones_that_still_follow_the_platform(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    await app.add_clone(CLONE2_ID, "clon2_bot", OWNER2_ID)
    await put_photo(app, brand.BOT)
    assert await brand.give_to_clones(app.manager, app.sm, PHOTO) == brand.Given(set=2)
    app.fake.profile_photos[CLONE2_ID] = "owner_photo"  # later its owner changed it
    newer = b"\xff\xd8JPEG-NEWER"
    assert await brand.give_to_clones(app.manager, app.sm, newer) == brand.Given(set=1, own=1)
    assert app.fake.profile_uploads[CLONE_ID] == newer
    assert app.fake.profile_uploads[CLONE2_ID] == PHOTO


async def test_a_refused_photo_counts_as_failed(app: App) -> None:
    await app.add_clone(CLONE_ID, "clon_bot", OWNER2_ID)
    app.fake.fail("setMyProfilePhoto", description="Bad Request: PHOTO_INVALID_DIMENSIONS")
    assert await brand.give_to_clones(app.manager, app.sm, PHOTO) == brand.Given(failed=1)
