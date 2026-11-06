from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings

log = logging.getLogger(__name__)

SessionMaker = async_sessionmaker[AsyncSession]


def create_engine(settings: Settings) -> AsyncEngine:
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if settings.is_sqlite:
        kwargs = {}
    else:
        kwargs.update(pool_size=settings.DB_POOL_SIZE, max_overflow=settings.DB_MAX_OVERFLOW, pool_recycle=1800)
    engine = create_async_engine(settings.DATABASE_URL, **kwargs)
    if settings.is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    return engine


def create_sessionmaker(engine: AsyncEngine) -> SessionMaker:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(sessionmaker: SessionMaker) -> AsyncIterator[AsyncSession]:
    """Transactional scope: commits on success, rolls back on error."""
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


class LeaderLock:
    """Postgres advisory lock so only one instance polls and schedules at a time."""

    KEY = 7_340_112_377

    def __init__(self, engine: AsyncEngine, is_sqlite: bool) -> None:
        self._engine = engine
        self._is_sqlite = is_sqlite
        self._conn = None

    async def acquire(self, retry_every: float = 5.0) -> None:
        if self._is_sqlite:
            return
        warned = False
        while True:
            conn = await self._engine.connect()
            got = (await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": self.KEY})).scalar()
            if got:
                self._conn = conn
                log.info("Leader lock acquired")
                return
            await conn.close()
            if not warned:
                log.warning("Another instance holds the leader lock; waiting...")
                warned = True
            await asyncio.sleep(retry_every)

    async def release(self) -> None:
        if self._conn is None:
            return
        try:
            await self._conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.KEY})
            await self._conn.close()
        except Exception:  # noqa: BLE001
            log.exception("Failed to release leader lock")
        self._conn = None
