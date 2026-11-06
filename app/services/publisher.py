"""STUB: the publishing engine (owner: engine module). See docs/ARCHITECTURE.md section 7 for the interface."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.config import Settings
    from app.db.session import SessionMaker
    from app.telegram.manager import BotManager


class Publisher:
    def __init__(self, manager: BotManager, sm: SessionMaker, settings: Settings) -> None:
        self.manager = manager
        self.sm = sm
        self.settings = settings

    async def resume(self) -> None:
        return None

    async def resume_bot(self, bot_id: int) -> None:
        return None

    async def withdraw_bot(self, bot_id: int, *, timeout: float) -> None:
        return None

    def is_busy(self, post_id: int) -> bool:
        return False

    async def send_now(self, post_id: int, *, user_id: int | None = None) -> int | None:
        return None

    async def run(self, post_id: int, chat_pks: list[int], *, kind: str, source: str = "",
                  triggered_by: int | None = None, wait: bool = False) -> int | None:
        return None

    async def retire(self, post_id: int) -> int:
        return 0

    async def update_live(self, post_id: int) -> tuple[int, int]:
        return 0, 0

    async def drop_chat(self, chat_pk: int) -> int:
        return 0

    async def delete_due(self) -> int:
        return 0


async def live_count(session: AsyncSession, post_id: int) -> int:
    """Deliveries of the post still up in the chats (sent, not deleted, younger than 48 h)."""
    return 0
