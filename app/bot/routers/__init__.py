"""Router assembly. Order matters: specific handlers first, fallbacks last."""
from __future__ import annotations

from aiogram import Dispatcher

from app.bot.context import CallbackAutoAnswerMiddleware, DbContextMiddleware, ThrottleMiddleware
from app.config import Settings
from app.db.session import SessionMaker


def setup_dispatcher(dp: Dispatcher, sessionmaker: SessionMaker, settings: Settings) -> None:
    from app.bot.routers import (
        chat_events,
        chats,
        clone,
        core,
        freqs,
        groups,
        panel,
        partners,
        post_buttons,
        posts,
        requests,
        settings as settings_router,
        start,
        stats,
        timezone,
    )

    dp.update.outer_middleware(ThrottleMiddleware(settings.THROTTLE_LIMIT, settings.THROTTLE_WINDOW))
    dp.update.outer_middleware(DbContextMiddleware(sessionmaker, settings))
    dp.callback_query.outer_middleware(CallbackAutoAnswerMiddleware())

    routers = (
        core.router,
        start.router,  # /start, /cancel and the other commands win over any half-finished input
        chat_events.router,
        requests.router,
        chats.router,
        partners.router,
        posts.router,
        post_buttons.router,
        groups.router,
        freqs.router,
        settings_router.router,
        timezone.router,
        stats.router,
        clone.router,
        panel.router,
        core.fallback_router,
    )
    for r in routers:
        # Module level routers can be attached to a new Dispatcher (tests build one per test).
        r._parent_router = None  # noqa: SLF001
    dp.include_routers(*routers)
    dp.errors.register(core.on_error)
