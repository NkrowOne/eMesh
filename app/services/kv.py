"""Small JSON key/value store (job bookkeeping, platform settings)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.db.base import utcnow
from app.db.models import KV

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get(session: AsyncSession, key: str, default: Any = None) -> Any:
    rec = await session.get(KV, key)
    return default if rec is None or rec.value is None else rec.value


async def put(session: AsyncSession, key: str, value: Any) -> None:
    rec = await session.get(KV, key)
    if rec is None:
        session.add(KV(key=key, value=value, updated_at=utcnow()))
    else:
        rec.value = value
        rec.updated_at = utcnow()
    await session.flush()


async def delete(session: AsyncSession, key: str) -> None:
    rec = await session.get(KV, key)
    if rec is not None:
        await session.delete(rec)
        await session.flush()
