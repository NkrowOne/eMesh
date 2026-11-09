"""Start module: a timezone is asked once in the whole ecosystem (services/zones.py). A zone the person already chose in
eMesh (their own in any bot, a clone of theirs) or in eButtons (its tables in eMesh's database or in the one of
EBUTTONS_DATABASE_URL) is reused: users aren't asked on their first visit, and the owner of a new clone gets it as
the network's zone."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import BotUser
from app.services import zones
from tests.conftest import MAIN_BOT_ID, OWNER2_ID, SUPER_ID, USER_ID, App
from tests.test_start_helpers import CLONE_ID, add_clone, edit_bot, get_bot, get_bu

EB_SCHEMA = (
    "CREATE TABLE eb_bots (id BIGINT PRIMARY KEY, owner_id BIGINT NOT NULL, is_main BOOLEAN NOT NULL, "
    "timezone VARCHAR(64) NOT NULL, timezone_set BOOLEAN NOT NULL)",
    "CREATE TABLE eb_bot_users (bot_id BIGINT NOT NULL, user_id BIGINT NOT NULL, timezone VARCHAR(64), "
    "last_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (bot_id, user_id))",
)
EB_DROP = ("DROP TABLE IF EXISTS eb_bot_users", "DROP TABLE IF EXISTS eb_bots")
WELCOME_QUESTION = "👋 <b>¡Hola!</b> Antes de empezar, elige tu <b>zona horaria</b>"
ONBOARDING = "👋 <b>¡Te damos la bienvenida a tu bot!</b>\nYa funciona; déjalo listo en un minuto:\n"
OTHER_CLONE_ID = 7_000_000_002


@pytest.fixture(autouse=True)
async def _fresh_checks() -> AsyncIterator[None]:
    """The check of the eButtons tables is remembered in memory: every test starts (and ends) without it."""
    await zones.reset()
    yield
    await zones.reset()


async def run_sql(engine: AsyncEngine, *statements: str) -> None:
    async with engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))


@pytest.fixture
async def eb(app: App) -> AsyncIterator[AsyncEngine]:
    """eButtons' tables in eMesh's database. Dropped at the end: a PostgreSQL test database is kept between tests."""
    await run_sql(app.engine, *EB_DROP, *EB_SCHEMA)
    try:
        yield app.engine
    finally:
        await run_sql(app.engine, *EB_DROP)


@pytest.fixture
async def broken_eb(app: App) -> AsyncIterator[None]:
    """An eb_bot_users table that can't be read as eButtons' (no timezone column): its query fails."""
    await run_sql(app.engine, *EB_DROP, "CREATE TABLE eb_bot_users (bot_id BIGINT, user_id BIGINT)")
    try:
        yield
    finally:
        await run_sql(app.engine, *EB_DROP)


def sql(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


async def eb_user(engine: AsyncEngine, bot_id: int, user_id: int, zone: str | None,
                  seen: str = "2026-11-01 10:00:00") -> None:
    await run_sql(engine, "INSERT INTO eb_bot_users (bot_id, user_id, timezone, last_seen_at) "
                          f"VALUES ({bot_id}, {user_id}, {sql(zone)}, '{seen}')")


async def eb_bot(engine: AsyncEngine, bot_id: int, owner_id: int, zone: str, *, main: bool = False,
                 chosen: bool = True) -> None:
    await run_sql(engine, "INSERT INTO eb_bots (id, owner_id, is_main, timezone, timezone_set) "
                          f"VALUES ({bot_id}, {owner_id}, {str(main).lower()}, {sql(zone)}, {str(chosen).lower()})")


async def known(app: App, user_id: int) -> str | None:
    async with app.db() as s:
        return await zones.known_zone(s, app.settings, user_id)


async def own_zone(app: App, user_id: int, bot_id: int, zone: str | None, *, hours_ago: int = 1) -> None:
    """The user's own zone in a bot they started (their row is created by /start)."""
    async with app.db() as s:
        bu = await s.get(BotUser, (bot_id, user_id))
        if bu is None:
            raise AssertionError(f"user {user_id} never started bot {bot_id}")
        bu.timezone = zone
        bu.last_seen_at = utcnow() - timedelta(hours=hours_ago)


async def clone_zone(app: App, bot_id: int, zone: str, *, chosen: bool = True) -> None:
    async with edit_bot(app, bot_id) as rec:
        rec.timezone, rec.timezone_set = zone, chosen


def local(app_rec: BotRecord) -> str:
    assert app_rec.rot_next_at is not None
    return app_rec.rot_next_at.astimezone(ZoneInfo(app_rec.timezone)).strftime("%H:%M")


# ------------------------------------------------------------------------------------------ known_zone
async def test_nothing_known(app: App) -> None:
    await app.send(USER_ID, "/start")
    assert await known(app, USER_ID) is None  # no zone of their own and no eButtons tables in the database


async def test_their_own_zone_in_any_bot_the_most_recently_seen_first(app: App) -> None:
    await add_clone(app)
    await app.send(USER_ID, "/start")
    await app.send(USER_ID, "/start", bot_id=CLONE_ID)
    await own_zone(app, USER_ID, MAIN_BOT_ID, "America/Bogota", hours_ago=48)
    await own_zone(app, USER_ID, CLONE_ID, "Asia/Tokyo", hours_ago=2)
    assert await known(app, USER_ID) == "Asia/Tokyo"
    await own_zone(app, USER_ID, CLONE_ID, "Mars/Olympus", hours_ago=1)  # a zone that doesn't exist any more
    assert await known(app, USER_ID) == "America/Bogota"
    await own_zone(app, USER_ID, CLONE_ID, "", hours_ago=1)
    assert await known(app, USER_ID) == "America/Bogota"
    await own_zone(app, USER_ID, MAIN_BOT_ID, "europe/lisbon")
    assert await known(app, USER_ID) == "Europe/Lisbon"  # in its canonical spelling


async def test_the_zone_of_a_clone_of_theirs_but_never_of_a_main_bot(app: App) -> None:
    await add_clone(app)  # owned by OWNER2
    await clone_zone(app, CLONE_ID, "Europe/Lisbon")
    assert await known(app, OWNER2_ID) == "Europe/Lisbon"
    await clone_zone(app, CLONE_ID, "Europe/Lisbon", chosen=False)  # nobody chose it yet
    assert await known(app, OWNER2_ID) is None
    # Main bots get the default zone at startup: their owner never chose it.
    rec = await get_bot(app)
    assert rec.timezone_set and rec.owner_id == SUPER_ID
    assert await known(app, SUPER_ID) is None
    # Their own zone comes first.
    await clone_zone(app, CLONE_ID, "Europe/Lisbon")
    await app.send(OWNER2_ID, "/start")
    await own_zone(app, OWNER2_ID, MAIN_BOT_ID, "Asia/Seoul")
    assert await known(app, OWNER2_ID) == "Asia/Seoul"


async def test_zones_chosen_in_ebuttons(app: App, eb: AsyncEngine) -> None:
    await eb_user(eb, 1, USER_ID, "America/Bogota", seen="2026-10-01 10:00:00")
    await eb_user(eb, 2, USER_ID, "Europe/Paris", seen="2026-11-01 10:00:00")
    await eb_user(eb, 3, USER_ID, "Not/AZone", seen="2026-11-05 10:00:00")
    await eb_user(eb, 4, USER_ID, "", seen="2026-11-06 10:00:00")
    await eb_user(eb, 5, USER_ID, None, seen="2026-11-07 10:00:00")
    await eb_user(eb, 1, 999, "Asia/Tokyo")  # someone else
    assert await known(app, USER_ID) == "Europe/Paris"  # the most recently seen valid one
    # The bots they own in eButtons: never a main bot, only a zone its owner chose.
    await eb_bot(eb, 10, OWNER2_ID, "Asia/Tokyo", main=True)
    await eb_bot(eb, 11, OWNER2_ID, "Asia/Dubai", chosen=False)
    assert await known(app, OWNER2_ID) is None
    await eb_bot(eb, 12, OWNER2_ID, "America/Lima")
    assert await known(app, OWNER2_ID) == "America/Lima"
    await eb_user(eb, 1, OWNER2_ID, "Africa/Cairo")  # their own zone comes first
    assert await known(app, OWNER2_ID) == "Africa/Cairo"
    # eButtons rules: its zone comes before the one chosen in eMesh.
    await app.send(USER_ID, "/start")
    await own_zone(app, USER_ID, MAIN_BOT_ID, "Asia/Kolkata")
    assert await known(app, USER_ID) == "Europe/Paris"


async def test_ebuttons_in_a_database_of_its_own(app: App, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'ebuttons.db'}"
    engine = create_async_engine(url)
    try:
        await run_sql(engine, *EB_SCHEMA)
        await eb_user(engine, 1, USER_ID, "Africa/Cairo")
        await eb_bot(engine, 2, OWNER2_ID, "Asia/Manila")
    finally:
        await engine.dispose()
    assert await known(app, USER_ID) is None  # eMesh's database has no eButtons tables
    await zones.reset()
    monkeypatch.setattr(app.settings, "EBUTTONS_DATABASE_URL", url)
    assert await known(app, USER_ID) == "Africa/Cairo"
    assert await known(app, OWNER2_ID) == "Asia/Manila"
    assert await known(app, SUPER_ID) is None


async def test_the_check_of_the_ebuttons_tables_is_remembered(app: App, eb: AsyncEngine,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    checks: list[int] = []
    real = zones._existing_tables  # noqa: SLF001

    def counting(conn: object) -> frozenset[str]:
        checks.append(1)
        return real(conn)  # type: ignore[arg-type]

    monkeypatch.setattr(zones, "_existing_tables", counting)
    await eb_user(eb, 1, USER_ID, "Asia/Seoul")
    assert await known(app, USER_ID) == "Asia/Seoul"
    assert await known(app, OWNER2_ID) is None
    assert len(checks) == 1
    await zones.reset()
    assert await known(app, USER_ID) == "Asia/Seoul"
    assert len(checks) == 2


async def test_a_database_that_fails_is_not_tried_again_at_once(app: App, tmp_path, monkeypatch: pytest.MonkeyPatch,
                                                                caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(app.settings, "EBUTTONS_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/no/such/dir/eb.db")
    with caplog.at_level(logging.WARNING, logger="app.services.zones"):
        assert await known(app, USER_ID) is None
        assert await known(app, OWNER2_ID) is None
    assert len([r for r in caplog.records if "could not be read" in r.getMessage()]) == 1
    monkeypatch.setattr(app.settings, "EBUTTONS_DATABASE_URL", "not a database url")
    assert await known(app, USER_ID) is None  # a wrong setting never raises either


async def test_a_failing_ebuttons_query_never_touches_the_callers_transaction(app: App, broken_eb: None,
                                                                             caplog: pytest.LogCaptureFixture) -> None:
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        assert rec is not None
        rec.support_username = "ayuda_bot"  # a pending change of the caller
        await s.flush()
        assert await zones.known_zone(s, app.settings, USER_ID) is None
        rec.min_members = 7  # the session goes on as if nothing happened
    rec = await get_bot(app)
    assert (rec.support_username, rec.min_members) == ("ayuda_bot", 7)
    assert "could not be read" in caplog.text


def test_the_ebuttons_database_url_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EBUTTONS_DATABASE_URL", raising=False)
    base = {"_env_file": None, "BOT_TOKEN": "1:x"}
    assert Settings(**base).EBUTTONS_DATABASE_URL == ""  # type: ignore[arg-type]  (the same database as eMesh)
    for given, expected in (("postgres://u:p@h:5432/eb", "postgresql+asyncpg://u:p@h:5432/eb"),
                            ("postgresql://u:p@h/eb", "postgresql+asyncpg://u:p@h/eb"),
                            ("sqlite+aiosqlite:///eb.db", "sqlite+aiosqlite:///eb.db")):
        assert Settings(**base, EBUTTONS_DATABASE_URL=given).EBUTTONS_DATABASE_URL == expected  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------ users' first visit
@pytest.mark.ask_timezone
async def test_a_zone_chosen_in_any_bot_is_reused(app: App) -> None:
    await add_clone(app)
    await clone_zone(app, CLONE_ID, "Europe/Lisbon")  # chosen by its owner (OWNER2)
    await app.send(USER_ID, "/start")
    assert app.last_text(USER_ID).startswith(WELCOME_QUESTION)
    await app.click(USER_ID, "🌎 América")
    await app.click(USER_ID, "América del Sur")
    await app.click(USER_ID, "Colombia")
    # The same person in a clone: not asked again, the zone is copied.
    await app.send(USER_ID, "/start", bot_id=CLONE_ID)
    assert not app.last_text(USER_ID).startswith(WELCOME_QUESTION)
    assert (await get_bu(app, USER_ID, CLONE_ID)).timezone == "America/Bogota"
    # The owner of a clone already chose its zone: it is theirs in the main bot.
    await app.send(OWNER2_ID, "/start")
    assert app.last_text(OWNER2_ID).startswith("👋 <b>¡Hola, Owner2!</b>")
    assert (await get_bu(app, OWNER2_ID)).timezone == "Europe/Lisbon"


@pytest.mark.ask_timezone
async def test_users_are_not_asked_a_zone_they_chose_in_ebuttons(app: App, eb: AsyncEngine) -> None:
    await eb_user(eb, 1, USER_ID, "America/Bogota")
    await app.send(USER_ID, "/start join")  # nor before the join screen
    assert not app.last_text(USER_ID).startswith(WELCOME_QUESTION)
    assert (await get_bu(app, USER_ID)).timezone == "America/Bogota"  # stored silently
    await eb_bot(eb, 2, OWNER2_ID, "Asia/Tokyo")
    await app.send(OWNER2_ID, "/start")
    assert app.last_text(OWNER2_ID).startswith("👋 <b>¡Hola, Owner2!</b>")
    assert (await get_bu(app, OWNER2_ID)).timezone == "Asia/Tokyo"


@pytest.mark.ask_timezone
async def test_a_failing_ebuttons_query_never_breaks_the_update(app: App, broken_eb: None,
                                                               caplog: pytest.LogCaptureFixture) -> None:
    await app.send(USER_ID, "/start")
    assert app.last_text(USER_ID).startswith(WELCOME_QUESTION)  # asked, as if nothing were known
    assert "could not be read" in caplog.text
    await app.click(USER_ID, "Europa")
    await app.click(USER_ID, "Francia")
    assert (await get_bu(app, USER_ID)).timezone == "Europe/Paris"
    assert app.last_text(USER_ID).startswith("✅ Tu zona horaria: <b>Europe/Paris</b>.")


@pytest.mark.ask_timezone
async def test_the_zone_an_owner_chooses_in_the_onboarding_is_reused_elsewhere(app: App) -> None:
    await add_clone(app, timezone_set=False)
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID).startswith(ONBOARDING)
    await app.click(OWNER2_ID, "Europa", bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "España", bot_id=CLONE_ID)
    await app.click(OWNER2_ID, "Islas Canarias", bot_id=CLONE_ID)
    await app.send(OWNER2_ID, "/start")  # the main bot, as a visitor: not asked
    assert app.last_text(OWNER2_ID).startswith("👋 <b>¡Hola, Owner2!</b>")
    assert (await get_bu(app, OWNER2_ID)).timezone == "Atlantic/Canary"


# ------------------------------------------------------------------------------------ owners of new clones
async def test_a_new_clone_takes_the_zone_its_owner_already_chose(app: App) -> None:
    await app.send(OWNER2_ID, "/start")
    await own_zone(app, OWNER2_ID, MAIN_BOT_ID, "America/Bogota")  # chosen as a visitor of the main bot
    await add_clone(app, timezone_set=False, setup_done=False)  # a brand new clone
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    rec = await get_bot(app, CLONE_ID)
    assert (rec.timezone, rec.timezone_set) == ("America/Bogota", True)
    assert rec.rot_next_at is not None and rec.rot_next_at > utcnow()
    assert local(rec) == "12:00"  # the next turn is recalculated in the network's zone
    assert (await get_bu(app, OWNER2_ID, CLONE_ID)).timezone == "America/Bogota"
    # Not asked: the setup wizard comes at once, with a welcome and the zone it took.
    assert app.last_text(OWNER2_ID).startswith(
        "👋 <b>¡Te damos la bienvenida a tu bot!</b> Ya funciona; déjalo listo en un minuto.\n"
        "🗺 Zona horaria de tu red: <b>America/Bogota</b>, la que ya elegiste. Se cambia en ⚙️ Ajustes.\n\n"
        "🧭 <b>Asistente de configuración</b>\n")
    await app.send(OWNER2_ID, "/start", bot_id=CLONE_ID)
    assert app.last_text(OWNER2_ID).startswith("🧭 <b>Asistente de configuración</b>")  # said once


async def test_a_new_clone_takes_the_zone_of_another_clone_of_its_owner(app: App) -> None:
    await add_clone(app)
    await clone_zone(app, CLONE_ID, "Europe/Lisbon")
    await app.add_clone(OTHER_CLONE_ID, "otro_clon_bot", OWNER2_ID)  # its wizard was done
    await app.send(OWNER2_ID, "/start", bot_id=OTHER_CLONE_ID)
    rec = await get_bot(app, OTHER_CLONE_ID)
    assert (rec.timezone, rec.timezone_set) == ("Europe/Lisbon", True)
    assert app.last_text(OWNER2_ID).startswith(
        "🗺 Zona horaria de tu red: <b>Europe/Lisbon</b>, la que ya elegiste. Se cambia en ⚙️ Ajustes.\n\n"
        "🕸 <b>Tu red de distribución</b>")


async def test_a_new_clone_takes_the_zone_of_a_bot_of_its_owner_in_ebuttons(app: App, eb: AsyncEngine) -> None:
    await eb_bot(eb, 1, OWNER2_ID, "America/Lima")
    await add_clone(app, timezone_set=False)
    await app.send(OWNER2_ID, "/start join", bot_id=CLONE_ID)  # whatever the link
    rec = await get_bot(app, CLONE_ID)
    assert (rec.timezone, rec.timezone_set) == ("America/Lima", True)
    assert "🗺 Zona horaria de tu red: <b>America/Lima</b>, la que ya elegiste." in app.last_text(OWNER2_ID)


async def test_without_a_known_zone_the_owner_is_asked(app: App, eb: AsyncEngine) -> None:
    await eb_bot(eb, 1, SUPER_ID, "Asia/Tokyo", main=True)  # main bots never count
    await add_clone(app, owner_id=SUPER_ID, timezone_set=False)  # the main bot's zone never counts either
    await app.send(SUPER_ID, "/start", bot_id=CLONE_ID)
    assert app.last_text(SUPER_ID).startswith(ONBOARDING)
    rec = await get_bot(app, CLONE_ID)
    assert not rec.timezone_set and rec.timezone == "Europe/Madrid"
