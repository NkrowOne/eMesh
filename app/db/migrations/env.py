from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import models  # noqa: F401  (registers tables)
from app.db.base import Base

config = context.config
target_metadata = Base.metadata
VERSION_TABLE = config.get_main_option("version_table") or "em_alembic_version"


def _url() -> str:
    url = config.attributes.get("database_url")
    if not url:
        from app.config import get_settings

        url = get_settings().DATABASE_URL
    return url


def _own_table(name: str | None, type_: str, parent_names: dict) -> bool:  # noqa: ARG001
    """Autogenerate only looks at eMesh's tables (``em_``): the database may be shared with eButtons (``eb_``)."""
    return type_ != "table" or bool(name and name.startswith("em_"))


def _configure(**kw) -> None:  # noqa: ANN003
    context.configure(
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        include_name=_own_table,
        render_as_batch=_url().startswith("sqlite"),
        compare_type=True,
        **kw,
    )


def run_migrations_offline() -> None:
    _configure(url=_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:  # noqa: ANN001
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
        await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
