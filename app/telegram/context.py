"""Request priority. Interactive handlers run as HIGH, background jobs must run as LOW."""
from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from enum import IntEnum


class Priority(IntEnum):
    HIGH = 0
    LOW = 1


request_priority: contextvars.ContextVar[Priority] = contextvars.ContextVar("request_priority", default=Priority.HIGH)


def set_low_priority() -> None:
    """Call at the start of a background task (publication, broadcast, maintenance)."""
    request_priority.set(Priority.LOW)


# Bot whose update or background job is running: the log records of errors are tagged with it.
current_bot_id: contextvars.ContextVar[int | None] = contextvars.ContextVar("current_bot_id", default=None)


@contextmanager
def bot_scope(bot_id: int) -> Iterator[None]:
    token = current_bot_id.set(bot_id)
    try:
        yield
    finally:
        current_bot_id.reset(token)
