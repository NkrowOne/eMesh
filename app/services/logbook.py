"""Recent warnings and errors kept in memory, tagged with their bot, for the 👑 Panel (downloaded as .txt).

They live in this process only: a restart starts an empty log (the hosting keeps the full stdout log).
"""
from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from app.telegram.context import current_bot_id

MAX_RECORDS = 5000
_BOT_IN_TEXT = re.compile(r"\bbot (?:id=)?(\d{5,})")  # "... for bot 123456", "by bot id=123456"
_FORMAT = logging.Formatter("%(levelname)s | %(name)s | %(message)s")


@dataclass(frozen=True)
class Entry:
    at: datetime
    bot_id: int | None
    text: str


class LogBook(logging.Handler):
    def __init__(self, size: int = MAX_RECORDS) -> None:
        super().__init__(level=logging.WARNING)
        self.entries: deque[Entry] = deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = _FORMAT.format(record)
            bot_id = getattr(record, "bot_id", None) or current_bot_id.get()
            if bot_id is None:
                match = _BOT_IN_TEXT.search(record.getMessage())
                bot_id = int(match.group(1)) if match else None
            self.entries.append(Entry(datetime.fromtimestamp(record.created, timezone.utc), bot_id, text))
        except Exception:  # noqa: BLE001 - logging must never break the caller
            self.handleError(record)

    def select(self, bot_id: int | None = None) -> list[Entry]:
        """Every entry (``bot_id`` None) or the ones of that bot, oldest first."""
        return [e for e in list(self.entries) if bot_id is None or e.bot_id == bot_id]


book = LogBook()


def install() -> None:
    root = logging.getLogger()
    if book not in root.handlers:
        root.addHandler(book)
