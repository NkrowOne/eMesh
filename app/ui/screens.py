"""Screen registry.

A screen is ``async def fn(event, ctx, session, arg=0, **kw) -> None`` that renders a panel.
Modules register screens with ``@screen("name")`` and open each other's screens with
``open_screen("name", ...)`` or a ``MenuCB(screen="name", arg=...)`` button, without importing
each other (no circular imports, loose coupling).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiogram.types import CallbackQuery, Message
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.bot.context import Ctx

log = logging.getLogger(__name__)

ScreenFn = Callable[..., Awaitable[None]]
_SCREENS: dict[str, ScreenFn] = {}

# Network screens: the main bot in hub mode runs no network (unless a super admin manages a clone from it), so they
# open the home screen instead.
HUB_HIDDEN = frozenset({
    "posts", "post", "post_content", "post_buttons", "post_targets", "post_sched", "post_opts", "post_defaults",
    "chats", "chat", "requests", "paused", "import", "my_chats", "my_chat", "join", "partners_msg",
    "groups", "group", "group_chats", "freqs", "freq_edit", "antispam", "stats", "activity", "externals",
})


def screen(name: str) -> Callable[[ScreenFn], ScreenFn]:
    def deco(fn: ScreenFn) -> ScreenFn:
        if name in _SCREENS and _SCREENS[name] is not fn:
            raise RuntimeError(f"Screen {name!r} registered twice")
        _SCREENS[name] = fn
        return fn

    return deco


def has_screen(name: str) -> bool:
    return name in _SCREENS


async def open_screen(
    name: str,
    event: Message | CallbackQuery,
    ctx: Ctx,
    session: AsyncSession,
    arg: int = 0,
    **kwargs: Any,
) -> None:
    if name in HUB_HIDDEN and ctx.is_hub:
        name, arg, kwargs = "home", 0, {}
    fn = _SCREENS.get(name)
    if fn is None:
        log.error("Unknown screen %r", name)
        fn = _SCREENS["home"]
        arg = 0
    await fn(event, ctx, session, arg=arg, **kwargs)
