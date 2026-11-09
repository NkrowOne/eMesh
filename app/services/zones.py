"""🗺 The timezone a person already chose, in eMesh or in eButtons: it is asked once in the whole ecosystem.

Telegram doesn't tell bots the timezone of a user, so the bots ask it; a zone chosen anywhere is reused
(:func:`known_zone`), in this order:

1. eMesh: their own zone in any bot (``em_bot_users.timezone``), the most recently seen first;
2. eMesh: the zone of a clone of theirs (``em_bots.timezone_set``; never a main bot: main bots get the default zone
   at startup, nobody chose it);
3. eButtons: the same two (``eb_bot_users``, ``eb_bots``).

eButtons' tables are in eMesh's database by default (both projects prefix their tables, ``em_`` / ``eb_``, so they can
share one) or in the database of ``EBUTTONS_DATABASE_URL``. They are read with plain SQL on a connection of their
own, after checking that they exist: any failure there is logged and ignored, and the caller's transaction is never
touched.
"""
from __future__ import annotations

import logging
import time
import weakref
from collections.abc import Iterable
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.config import Settings
from app.data.timezones import resolve_zone
from app.db.models import Bot as BotRecord
from app.db.models import BotUser
from app.telegram.errors import short

log = logging.getLogger(__name__)

CANDIDATES = 10  # stored zones read per source: an invalid one never hides the next
TABLES_TTL = 300.0  # seconds the check of the eButtons tables of a database is remembered
CONNECT_TIMEOUT = 5  # seconds to reach eButtons' own database: a first visit never waits longer
EB_BOT_USERS = "eb_bot_users"
EB_BOTS = "eb_bots"

_EB_USER_ZONES = text(
    "SELECT timezone FROM eb_bot_users WHERE user_id = :user_id AND timezone IS NOT NULL AND timezone <> '' "
    "ORDER BY last_seen_at DESC LIMIT :limit"
)
_EB_OWNER_ZONES = text(
    "SELECT timezone FROM eb_bots WHERE owner_id = :user_id AND timezone_set = :yes AND is_main = :no "
    "AND timezone IS NOT NULL AND timezone <> '' ORDER BY id DESC LIMIT :limit"
)

_engines: dict[str, AsyncEngine] = {}  # EBUTTONS_DATABASE_URL -> its engine, created on first use
# The eButtons tables found in a database: engine -> (time.monotonic() of the check, their names). A failure counts
# as none, so a broken or unreachable database isn't tried again on every first visit.
_tables: weakref.WeakKeyDictionary[AsyncEngine, tuple[float, frozenset[str]]] = weakref.WeakKeyDictionary()


async def known_zone(session: AsyncSession, settings: Settings, user_id: int) -> str | None:
    """The timezone ``user_id`` already chose somewhere (eMesh first, then eButtons), or None."""
    return await _emesh_zone(session, user_id) or await _ebuttons_zone(session, settings, user_id)


async def reset() -> None:
    """Forgets the checks of the eButtons tables and closes the engines created here."""
    _tables.clear()
    engines = list(_engines.values())
    _engines.clear()
    for engine in engines:
        await engine.dispose()


def _first_valid(zones: Iterable[object]) -> str | None:
    """The first stored zone that still is a valid IANA name (in its canonical spelling)."""
    for value in zones:
        zone = resolve_zone(str(value)) if value else None
        if zone is not None:
            return zone
    return None


async def _emesh_zone(session: AsyncSession, user_id: int) -> str | None:
    own = await session.scalars(
        select(BotUser.timezone)
        .where(BotUser.user_id == user_id, BotUser.timezone.is_not(None), BotUser.timezone != "")
        .order_by(BotUser.last_seen_at.desc())
        .limit(CANDIDATES)
    )
    zone = _first_valid(own)
    if zone is not None:
        return zone
    of_clones = await session.scalars(
        select(BotRecord.timezone)
        .where(BotRecord.owner_id == user_id, BotRecord.timezone_set.is_(True), BotRecord.is_main.is_(False),
               BotRecord.timezone != "")
        .order_by(BotRecord.id.desc())
        .limit(CANDIDATES)
    )
    return _first_valid(of_clones)


def _engine_for(session: AsyncSession, settings: Settings) -> AsyncEngine | None:
    """The engine of eButtons' database: eMesh's own (the session's) or the one of ``EBUTTONS_DATABASE_URL``."""
    url = settings.EBUTTONS_DATABASE_URL
    if not url:
        bind = session.bind
        return bind if isinstance(bind, AsyncEngine) else getattr(bind, "engine", None)
    engine = _engines.get(url)
    if engine is None:
        kwargs: dict[str, Any] = {}
        if url.startswith("postgresql+asyncpg"):
            kwargs = {"pool_pre_ping": True, "pool_size": 1, "max_overflow": 2, "pool_recycle": 1800,
                      "connect_args": {"timeout": CONNECT_TIMEOUT}}
        engine = _engines[url] = create_async_engine(url, **kwargs)
    return engine


def _checked_tables(engine: AsyncEngine) -> frozenset[str] | None:
    """The eButtons tables of a database checked a moment ago (None: check them again)."""
    checked = _tables.get(engine)
    if checked is None or time.monotonic() - checked[0] >= TABLES_TTL:
        return None
    return checked[1]


def _existing_tables(conn: Connection) -> frozenset[str]:
    inspector = inspect(conn)
    return frozenset(name for name in (EB_BOT_USERS, EB_BOTS) if inspector.has_table(name))


async def _ebuttons_zone(session: AsyncSession, settings: Settings, user_id: int) -> str | None:
    engine: AsyncEngine | None = None
    try:
        engine = _engine_for(session, settings)
        if engine is None:
            return None
        tables = _checked_tables(engine)
        if tables is not None and not tables:
            return None  # no eButtons in that database (or it failed a moment ago)
        async with engine.connect() as conn:  # a connection of its own: the caller's transaction is untouched
            if tables is None:
                tables = await conn.run_sync(_existing_tables)
                _tables[engine] = (time.monotonic(), tables)
            params = {"user_id": user_id, "limit": CANDIDATES}
            if EB_BOT_USERS in tables:
                zone = _first_valid((await conn.execute(_EB_USER_ZONES, params)).scalars())
                if zone is not None:
                    return zone
            if EB_BOTS in tables:
                return _first_valid((await conn.execute(_EB_OWNER_ZONES, {**params, "yes": True, "no": False}))
                                    .scalars())
    except Exception as exc:  # noqa: BLE001 - eButtons is optional: its problems never break an update
        log.warning("The timezones chosen in eButtons could not be read: %s", short(exc))
        if engine is not None:
            _tables[engine] = (time.monotonic(), frozenset())
    return None
