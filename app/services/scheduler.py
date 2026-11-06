"""STUB: the scheduler (owner: engine module). See docs/ARCHITECTURE.md section 7 for the interface."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings
    from app.db.session import SessionMaker
    from app.services.publisher import Publisher
    from app.telegram.manager import BotManager


class Scheduler:
    def __init__(self, manager: BotManager, sm: SessionMaker, settings: Settings, publisher: Publisher) -> None:
        self.manager = manager
        self.sm = sm
        self.settings = settings
        self.publisher = publisher

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def wake(self) -> None:
        return None

    async def tick(self) -> None:
        return None
