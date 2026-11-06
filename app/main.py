"""Entry point: ``python -m app``."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import SimpleEventIsolation

from app import i18n
from app.bot.routers import setup_dispatcher
from app.config import Settings, get_settings
from app.db.session import LeaderLock, create_engine, create_sessionmaker
from app.services import clones, logbook
from app.services.publisher import Publisher
from app.services.scheduler import Scheduler
from app.telegram.fsm_storage import SQLStorage
from app.telegram.manager import BotManager

log = logging.getLogger("app")
ROOT = Path(__file__).resolve().parent.parent


def setup_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    # One line per handled update: only with LOG_LEVEL=DEBUG (too noisy for production).
    logging.getLogger("aiogram.event").setLevel(logging.INFO if numeric <= logging.DEBUG else logging.WARNING)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)
    logbook.install()  # recent warnings/errors for the 👑 Panel


def run_migrations(settings: Settings) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "app" / "db" / "migrations"))
    cfg.attributes["database_url"] = settings.DATABASE_URL
    command.upgrade(cfg, "head")


def build_dispatcher(settings: Settings, sm) -> tuple[Dispatcher, SQLStorage]:  # noqa: ANN001
    storage = SQLStorage(sm)
    dp = Dispatcher(storage=storage, events_isolation=SimpleEventIsolation())
    setup_dispatcher(dp, sm, settings)
    return dp, storage


def check_startup(settings: Settings, environ: dict[str, str] | os._Environ[str] = os.environ) -> None:
    """Refuses to start with a configuration that can't work (or would lose data)."""
    if settings.MODE == "webhook" and not settings.WEBHOOK_BASE_URL:
        raise SystemExit("WEBHOOK_BASE_URL is required when MODE=webhook")
    if not settings.super_admin_ids:
        raise SystemExit("SUPER_ADMIN_IDS must contain your Telegram user id")
    if settings.is_sqlite and any(k.startswith("RAILWAY_") for k in environ):
        # Railway doesn't inject the database URL by itself: without the reference variable the bot
        # would run on a SQLite file inside the container, wiped on every deploy.
        raise SystemExit(
            "DATABASE_URL is not set on Railway: add the variable DATABASE_URL=${{Postgres.DATABASE_URL}} "
            "to the bot service (a SQLite file in the container is erased on every deploy)"
        )
    if settings.is_sqlite:
        log.warning(
            "DATABASE_URL is not set: using the SQLite file %s. If this disk is not persistent, every deploy "
            "erases the data; set DATABASE_URL to a PostgreSQL database.", settings.DATABASE_URL
        )


async def amain() -> None:
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    check_startup(settings)
    i18n.load()

    if settings.RUN_MIGRATIONS:
        log.info("Running database migrations...")
        await asyncio.to_thread(run_migrations, settings)

    engine = create_engine(settings)
    sm = create_sessionmaker(engine)
    lock = LeaderLock(engine, settings.is_sqlite)
    await lock.acquire()

    dp, storage = build_dispatcher(settings, sm)
    manager = BotManager(dp, settings, sm)
    publisher = Publisher(manager, sm, settings)
    scheduler = Scheduler(manager, sm, settings, publisher)
    dp.workflow_data.update(settings=settings, sm=sm, manager=manager, publisher=publisher, scheduler=scheduler)
    clones.install(manager, sm, settings)  # a clone whose token stops working: its owner gets a DM

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    web_runner = None
    try:
        await manager.start()
        await publisher.resume()
        await scheduler.start()
        if settings.MODE == "webhook":
            from aiohttp import web

            app = web.Application()
            manager.webhook_routes(app)

            async def health(_: web.Request) -> web.Response:
                return web.Response(text="ok")

            app.router.add_get("/health", health)
            web_runner = web.AppRunner(app)
            await web_runner.setup()
            await web.TCPSite(web_runner, settings.HOST, settings.PORT).start()
            log.info("Web server listening on %s:%s", settings.HOST, settings.PORT)
        log.info("eMesh is running (%s mode, %d bots)", settings.MODE, len(manager.bots))
        await stop.wait()
    finally:
        log.info("Shutting down...")
        try:
            await scheduler.stop()
        except Exception:  # noqa: BLE001
            log.exception("Error while stopping")
        if web_runner is not None:
            await web_runner.cleanup()
        await manager.shutdown()
        await storage.close()
        await lock.release()
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
