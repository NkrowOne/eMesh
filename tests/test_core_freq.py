"""Frequency math (services/freq.py)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.services import freq

TZ = "Europe/Madrid"


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=timezone.utc)


def test_interval_with_window() -> None:
    f = {"mode": "interval", "every": 180, "window": "08:00-23:00", "days": "0123456"}
    # 2026-11-06 is a Friday; Madrid is UTC+1 in November
    slots = freq.upcoming(f, TZ, utc(2026, 11, 6, 6, 30), 7)
    local = [s.astimezone(freq.zone(TZ)).strftime("%d %H:%M") for s in slots]
    assert local == ["06 08:00", "06 11:00", "06 14:00", "06 17:00", "06 20:00", "06 23:00", "07 08:00"]
    assert freq.per_day(f) == 6


def test_interval_without_window_starts_at_midnight() -> None:
    f = {"mode": "interval", "every": 240, "window": "", "days": "0123456"}
    nxt = freq.next_slot(f, TZ, utc(2026, 11, 6, 9, 5))  # 10:05 local
    assert nxt is not None and nxt.astimezone(freq.zone(TZ)).strftime("%H:%M") == "12:00"
    assert freq.per_day(f) == 6


def test_window_crossing_midnight() -> None:
    f = {"mode": "interval", "every": 120, "window": "22:00-02:00", "days": "4"}  # Fridays only
    slots = freq.upcoming(f, TZ, utc(2026, 11, 6, 12, 0), 4)
    local = [s.astimezone(freq.zone(TZ)).strftime("%a %H:%M") for s in slots]
    assert local == ["Fri 22:00", "Sat 00:00", "Sat 02:00", "Fri 22:00"]


def test_times_and_days() -> None:
    f = {"mode": "times", "times": "22:00,10:00", "days": "01234"}
    nxt = freq.next_slot(f, TZ, utc(2026, 11, 6, 22, 0))  # Friday 23:00 local -> Monday 10:00
    assert nxt is not None
    local = nxt.astimezone(freq.zone(TZ))
    assert (local.weekday(), local.strftime("%H:%M")) == (0, "10:00")
    assert freq.normalize(f)["times"] == "10:00,22:00"


def test_no_days_means_never() -> None:
    assert freq.next_slot({"mode": "interval", "every": 60, "days": ""}, TZ, utc(2026, 1, 1)) is None


def test_dst_keeps_wall_clock_times() -> None:
    f = {"mode": "times", "times": "10:00", "days": "0123456"}
    before = freq.next_slot(f, TZ, utc(2026, 3, 28, 12))  # 29/03/2026: Europe switches to summer time
    assert before is not None and before.astimezone(freq.zone(TZ)).strftime("%d %H:%M") == "29 10:00"
    assert before == utc(2026, 3, 29, 8)


@pytest.mark.parametrize(("text", "minutes"), [
    ("30", 30), ("3", 180), ("90", 90), ("45 min", 45), ("2 h", 120), ("1h30", 90), ("1:30", 90), ("1.5h", 90),
    ("1 h 30 min", 90), ("cada 2 h", 120), ("24", 1440),
])
def test_parse_every(text: str, minutes: int) -> None:
    assert freq.parse_every(text) == minutes


@pytest.mark.parametrize("text", ["5 min", "25 h", "abc", ""])
def test_parse_every_errors(text: str) -> None:
    with pytest.raises(ValueError):
        freq.parse_every(text)


def test_parse_times_and_window() -> None:
    assert freq.parse_times("22:00, 10 y 9h") == "09:00,10:00,22:00"
    assert freq.parse_window("de 8 a 23") == "08:00-23:00"
    assert freq.parse_window("0") == ""
    with pytest.raises(ValueError):
        freq.parse_window("8-8")


def test_parse_datetime() -> None:
    now = utc(2026, 11, 6, 12, 0)  # 13:00 local
    assert freq.parse_datetime("20:00", TZ, now) == utc(2026, 11, 6, 19, 0)
    assert freq.parse_datetime("10:00", TZ, now) == utc(2026, 11, 7, 9, 0)  # passed today -> tomorrow
    assert freq.parse_datetime("25/12/2026 20:00", TZ, now) == utc(2026, 12, 25, 19, 0)
    assert freq.parse_datetime("25/12 20:00", TZ, now) == utc(2026, 12, 25, 19, 0)
    with pytest.raises(ValueError, match="freq.err.past"):
        freq.parse_datetime("01/01/2026 10:00", TZ, now)
    assert freq.parse_date("01/02", TZ, now) == date(2027, 2, 1)


def test_describe() -> None:
    assert freq.describe({"mode": "interval", "every": 180, "window": "08:00-23:00", "days": "0123456"}, "es") == \
        "cada 3 h · 08:00-23:00"
    assert freq.describe({"mode": "times", "times": "10:00,22:00", "days": "01234"}, "es") == \
        "a las 10:00 y 22:00 · de lunes a viernes"
    assert freq.describe({"mode": "interval", "every": 90, "days": "56"}, "en") == "every 1 h 30 min · weekends"
