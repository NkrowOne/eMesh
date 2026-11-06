"""aiogram FSM storage: memory cache + write-behind persistence in the database.

Reads come from memory. Writes update memory at once and are flushed to the database by a
background task shortly after, so a handler never waits on (or deadlocks with) its own open
transaction. Unchanged writes (e.g. clearing an empty state) never touch the database.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from sqlalchemy import delete, select

from app.db.models import FSMRecord
from app.db.session import SessionMaker, session_scope

log = logging.getLogger(__name__)

_MISSING = object()


class SQLStorage(BaseStorage):
    FLUSH_DELAY = 0.3
    RETRY_DELAY = 2.0

    def __init__(self, sessionmaker: SessionMaker) -> None:
        self._sm = sessionmaker
        self._cache: dict[str, tuple[str | None, dict[str, Any]]] = {}
        self._dirty: set[str] = set()
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_lock = asyncio.Lock()

    @staticmethod
    def _key(key: StorageKey) -> str:
        return ":".join(
            str(p)
            for p in (
                key.bot_id,
                key.chat_id,
                key.user_id,
                key.thread_id or "",
                key.business_connection_id or "",
                key.destiny,
            )
        )

    async def _load(self, k: str) -> tuple[str | None, dict[str, Any]]:
        cached = self._cache.get(k, _MISSING)
        if cached is not _MISSING:
            return cached  # type: ignore[return-value]
        async with self._sm() as s:
            rec = await s.get(FSMRecord, k)
        value = (rec.state, dict(rec.data or {})) if rec else (None, {})
        self._cache.setdefault(k, value)
        return self._cache[k]

    def _save(self, k: str, state: str | None, data: dict[str, Any]) -> None:
        if self._cache.get(k, _MISSING) == (state, data):
            return
        self._cache[k] = (state, data)
        self._dirty.add(k)
        self._schedule(self.FLUSH_DELAY)

    def _schedule(self, delay: float) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_later(delay))

    async def _flush_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        await self.flush()

    async def flush(self) -> None:
        """Writes every pending change to the database."""
        async with self._flush_lock:
            while self._dirty:
                keys = list(self._dirty)
                self._dirty.clear()
                try:
                    async with session_scope(self._sm) as s:
                        for k in keys:
                            state, data = self._cache.get(k, (None, {}))
                            rec = await s.get(FSMRecord, k)
                            if state is None and not data:
                                if rec is not None:
                                    await s.delete(rec)
                            elif rec is None:
                                s.add(FSMRecord(key=k, state=state, data=dict(data)))
                            else:
                                rec.state = state
                                rec.data = dict(data)
                except Exception:  # noqa: BLE001
                    log.exception("FSM flush failed, retrying in %.0fs", self.RETRY_DELAY)
                    self._dirty.update(keys)
                    self._flush_task = asyncio.create_task(self._flush_later(self.RETRY_DELAY))
                    return

    async def set_state(self, key: StorageKey, state: str | State | None = None) -> None:
        k = self._key(key)
        _, data = await self._load(k)
        value = state.state if isinstance(state, State) else state
        self._save(k, value, data)

    async def get_state(self, key: StorageKey) -> str | None:
        state, _ = await self._load(self._key(key))
        return state

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        k = self._key(key)
        state, _ = await self._load(k)
        self._save(k, state, dict(data))

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        _, data = await self._load(self._key(key))
        return dict(data)

    async def close(self) -> None:
        task = self._flush_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self.flush()
        self._cache.clear()

    async def purge_stale(self, older_than: datetime) -> int:
        async with session_scope(self._sm) as s:
            res = await s.execute(select(FSMRecord.key).where(FSMRecord.updated_at < older_than))
            keys = [r[0] for r in res if r[0] not in self._dirty]
            if keys:
                await s.execute(delete(FSMRecord).where(FSMRecord.key.in_(keys)))
        for k in keys:
            self._cache.pop(k, None)
        return len(keys)
