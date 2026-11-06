from __future__ import annotations

from typing import Any

from aiogram.filters import Filter
from aiogram.types import TelegramObject

from app.bot.context import Ctx
from app.db.models import Role


class RoleFilter(Filter):
    """Passes when ``ctx.role`` is at least ``role``. Example: ``RoleFilter(Role.ADMIN)``."""

    def __init__(self, role: str = Role.ADMIN) -> None:
        self.role = role

    async def __call__(self, event: TelegramObject, ctx: Ctx | None = None, **_: Any) -> bool:
        return ctx is not None and ctx.at_least(self.role)


class MainBotFilter(Filter):
    """Passes only for updates of the main (platform) bot."""

    async def __call__(self, event: TelegramObject, ctx: Ctx | None = None, **_: Any) -> bool:
        return ctx is not None and ctx.is_main


class PrivateFilter(Filter):
    async def __call__(self, event: TelegramObject, event_chat: Any = None, **_: Any) -> bool:
        return event_chat is not None and event_chat.type == "private"


IsAdmin = RoleFilter(Role.ADMIN)
IsOwner = RoleFilter(Role.OWNER)
IsSuper = RoleFilter(Role.SUPER)
