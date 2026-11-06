"""Shared callback data.

Every router module defines its OWN CallbackData classes using the prefix assigned
to it in docs/ARCHITECTURE.md, so prefixes never collide. Only cross-module ones live here.
"""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCB(CallbackData, prefix="m"):
    """Opens a registered screen by name (see app/ui/screens.py)."""

    screen: str
    arg: int = 0


class NoopCB(CallbackData, prefix="noop"):
    """Button that does nothing (labels, separators)."""

    tag: str = ""


class CloseCB(CallbackData, prefix="close"):
    """Deletes the message it belongs to (previews that shouldn't stay in the chat)."""


class InputCancelCB(CallbackData, prefix="inx"):
    """Cancels the current text input (FSM) and reopens ``screen``."""

    screen: str = "home"
    arg: int = 0
