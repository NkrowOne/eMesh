"""Formatting helpers for HTML messages."""
from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.i18n import t


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def esc_attr(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def num(n: int | float | None) -> str:
    return f"{int(n or 0):,}"


def onoff(value: bool) -> str:
    return "✅" if value else "✖️"


def zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def to_local(dt: datetime, tz: str | None) -> datetime:
    return dt.astimezone(zone(tz))


def dt(value: datetime | None, tz: str | None, *, empty: str = "—") -> str:
    """``01/11/2026 11:00 AM`` in the given timezone."""
    if value is None:
        return empty
    local = to_local(value, tz)
    return local.strftime("%d/%m/%Y %I:%M %p")


def hm(value: datetime | None, tz: str | None) -> str:
    if value is None:
        return "—"
    return to_local(value, tz).strftime("%H:%M")


def weekdays(days: str | list[int], lang: str, *, short: bool = False) -> str:
    items = sorted({int(d) for d in days if str(d).isdigit() and int(d) < 7})
    if len(items) == 7 and short:
        return t("weekday.all", lang)
    if not items:
        return t("weekday.none", lang)
    prefix = "weekday.short." if short else "weekday."
    return ", ".join(t(f"{prefix}{d}", lang) for d in items)


def user_link(user_id: int, name: str | None = None, username: str | None = None) -> str:
    if username:
        return f"@{esc(username)}"
    return f'<a href="tg://user?id={int(user_id)}">{esc(name or user_id)}</a>'


def link(url: str | None, text: str) -> str:
    if not url:
        return esc(text)
    return f'<a href="{esc_attr(url)}">{esc(text)}</a>'


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def members_range(min_members: int, max_members: int | None, lang: str = "es") -> str:
    """``500 - 4999`` / ``15000 - ∞`` (same style as the original bot)."""
    upper = str(max_members) if max_members else t("common.infinite", lang)
    return f"{min_members} - {upper}"
