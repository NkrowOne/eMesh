"""⏰ Frequencies (schedules): when a post goes out (its own one, ``Post.freq``; ``Bot.freq`` is the default schedule
every new post starts with).

A frequency is a small dict stored in JSON columns (``Bot.freq``, ``Post.freq``):

* ``{"mode": "interval", "every": 180, "window": "08:00-23:00", "days": "0123456"}``: every 3 hours from 08:00 to
  23:00 (both included) on those weekdays (Monday = 0). Without a window the slots start at 00:00 and cover the
  whole day. A window can cross midnight ("22:00-02:00"): its slots belong to the day it starts.
* ``{"mode": "times", "times": "10:00,14:00,22:00", "days": "01234"}``: at those times, Monday to Friday.

Times are wall-clock times of the bot's timezone (DST safe). Every datetime returned is aware UTC.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from app.db.models import DEFAULT_FREQ, PostStatus, SchedMode
from app.i18n import t
from app.ui.fmt import zone

if TYPE_CHECKING:
    from app.db.models import Post

DEFAULT_EVERY = 240  # minutes: an interval frequency without a valid "every" (4 h)
DEFAULT_TIMES = "12:00"  # a times frequency without valid times
MIN_EVERY = 10  # minutes
MAX_EVERY = 1440
MAX_TIMES = 24
MIN_YEAR, MAX_YEAR = 2000, 2100  # of a typed date: far ones ("31/12/9999" = no end) overflow the date math
MAX_EVERY_TEXT = 40  # characters of a typed interval: nobody writes a longer one
EVERY_CHOICES = (30, 60, 120, 180, 240, 360, 480, 720, 1440)  # quick buttons of the editor
ALL_DAYS = "0123456"
WEEKDAYS = "01234"
WEEKEND = "56"

_HM_RE = re.compile(r"^(\d{1,2})(?:[:.hH](\d{2})?)?\s*(?:h|hs|hrs)?$")
_COMPACT_RE = re.compile(r"^(\d{2})(\d{2})$")
_SPLIT_RE = re.compile(r"\s*(?:[,;/]|\s+y\s+|\s+and\s+|\s+)\s*", re.IGNORECASE)
_SUFFIX_RE = re.compile(r"(\d)\s+(hrs|hs|h)\b", re.IGNORECASE)
_WINDOW_RE = re.compile(r"^(?:de\s+|from\s+)?(.+?)\s*(?:-|–|—|\ba\b|\bto\b|\bhasta\b)\s*(.+)$", re.IGNORECASE)
_NO_WINDOW = {"", "0", "-", "no", "none", "ninguno", "ninguna", "todo el dia", "todo el día", "all day", "24h"}
_EVERY_RE = re.compile(
    r"^(?:(?P<h>\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hora|horas|hour|hours))?\s*"
    r"(?:(?P<m>\d+)\s*(?:m|min|mins|minuto|minutos|minute|minutes)?)?$"
)
_DATETIME_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?(?:\s+(.+))?$")


# --------------------------------------------------------------------------- the dict
def normalize(freq: dict[str, Any] | None) -> dict[str, Any]:
    """A clean copy of ``freq`` (``DEFAULT_FREQ`` when it is missing or broken). Never raises."""
    src = freq if isinstance(freq, dict) else DEFAULT_FREQ
    days = "".join(sorted({c for c in str(src.get("days", ALL_DAYS)) if c in ALL_DAYS}))
    if src.get("mode") == "times":
        times = ",".join(f"{h:02d}:{m:02d}" for h, m in _times_of(str(src.get("times") or "")))
        return {"mode": "times", "times": times or DEFAULT_TIMES, "days": days}
    try:
        every = int(src.get("every") or DEFAULT_EVERY)
    except (TypeError, ValueError):
        every = DEFAULT_EVERY
    every = min(max(every, MIN_EVERY), MAX_EVERY)
    window = str(src.get("window") or "")
    if window and _window_of(window) is None:
        window = ""
    return {"mode": "interval", "every": every, "window": window, "days": days}


def _times_of(value: str) -> list[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for part in (value or "").split(","):
        try:
            out.add(_parse_hm(part))
        except ValueError:
            continue
    return sorted(out)


def _window_of(value: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    try:
        start, end = value.split("-", 1)
        a, b = _parse_hm(start), _parse_hm(end)
    except ValueError:
        return None
    return (a, b) if a != b else None


# --------------------------------------------------------------------------- slots
def _local_slots(freq: dict[str, Any], day: date, tz: str) -> list[datetime]:
    """The slots of one local day, as aware local datetimes (a window may spill past midnight)."""
    f = normalize(freq)
    if str(day.weekday()) not in f["days"]:
        return []
    z = zone(tz)
    if f["mode"] == "times":
        return [datetime(day.year, day.month, day.day, h, m, tzinfo=z) for h, m in _times_of(f["times"])]
    every = timedelta(minutes=f["every"])
    win = _window_of(f["window"]) if f["window"] else None
    if win is None:
        start = datetime(day.year, day.month, day.day, tzinfo=z)
        end = start + timedelta(days=1) - timedelta(minutes=1)
    else:
        (sh, sm), (eh, em) = win
        start = datetime(day.year, day.month, day.day, sh, sm, tzinfo=z)
        end = datetime(day.year, day.month, day.day, eh, em, tzinfo=z)
        if end <= start:
            end += timedelta(days=1)
    out: list[datetime] = []
    slot = start
    while slot <= end:
        out.append(slot)
        slot += every
    return out


def next_slot(freq: dict[str, Any] | None, tz: str, after: datetime) -> datetime | None:
    """The first slot strictly after ``after`` (aware UTC), or None (no weekday selected)."""
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    f = normalize(freq)
    if not f["days"]:
        return None
    first = after.astimezone(zone(tz)).date() - timedelta(days=1)
    try:
        for i in range(10):
            # The earliest in real time, not in wall-clock order: on the spring-forward day a time that doesn't
            # exist ("02:30") maps after the next ones ("03:15").
            day = [slot.astimezone(timezone.utc) for slot in _local_slots(f, first + timedelta(days=i), tz)]
            later = [utc for utc in day if utc > after]
            if later:
                nxt = min(later)
                # a window spilling past midnight can overlap the next day's first slots: look one day more
                ahead = [slot.astimezone(timezone.utc) for slot in _local_slots(f, first + timedelta(days=i + 1), tz)]
                return min([nxt, *(utc for utc in ahead if utc > after)])
    except OverflowError:
        return None
    return None


def upcoming(freq: dict[str, Any] | None, tz: str, after: datetime, n: int = 3) -> list[datetime]:
    """The next ``n`` slots after ``after``."""
    out: list[datetime] = []
    cursor = after
    while len(out) < n:
        nxt = next_slot(freq, tz, cursor)
        if nxt is None:
            break
        out.append(nxt)
        cursor = nxt
    return out


def day_times(freq: dict[str, Any] | None) -> list[tuple[int, int]]:
    """The wall-clock times (hour, minute) of the slots of a day it runs, sorted (``per_day`` of them)."""
    f = normalize(freq)
    if f["mode"] == "times":
        return _times_of(f["times"])
    win = _window_of(f["window"]) if f["window"] else None
    start, length = 0, 1439
    if win is not None:
        (sh, sm), (eh, em) = win
        start = sh * 60 + sm
        length = (eh * 60 + em) - start
        if length <= 0:
            length += 1440
    return sorted({divmod((start + k) % 1440, 60) for k in range(0, length + 1, f["every"])})


def per_day(freq: dict[str, Any] | None) -> int:
    """Slots on a day it runs (to show "≈ 6 al día")."""
    f = normalize(freq)
    if f["mode"] == "times":
        return len(_times_of(f["times"]))
    win = _window_of(f["window"]) if f["window"] else None
    if win is None:
        return -(-1440 // f["every"])
    (sh, sm), (eh, em) = win
    length = (eh * 60 + em) - (sh * 60 + sm)
    if length <= 0:
        length += 1440
    return length // f["every"] + 1


# --------------------------------------------------------------------------- campaign dates and next send times
def day_start(day: date, tz: str) -> datetime:
    """00:00 of ``day`` in ``tz``, as aware UTC."""
    return datetime(day.year, day.month, day.day, tzinfo=zone(tz)).astimezone(timezone.utc)


def day_end(day: date, tz: str) -> datetime:
    """The end of ``day`` in ``tz`` (00:00 of the next day), as aware UTC. Never overflows: the end of 31/12/9999 is
    the largest datetime."""
    try:
        return day_start(day + timedelta(days=1), tz)
    except OverflowError:
        return datetime.max.replace(tzinfo=timezone.utc)


def in_dates(post: Post, tz: str, now: datetime) -> bool:
    """``now`` is inside the campaign dates of the post (from 00:00 of starts_on to 23:59 of ends_on)."""
    if post.starts_on and now < day_start(post.starts_on, tz):
        return False
    return not (post.ends_on and now >= day_end(post.ends_on, tz))


def ended(post: Post, tz: str, now: datetime) -> bool:
    """The campaign of the post is over (its end date passed)."""
    return post.ends_on is not None and now >= day_end(post.ends_on, tz)


def refresh_post(post: Post, tz: str, now: datetime) -> datetime | None:
    """``posts.next_send_at``: own frequency or one-time posts only (manual posts have none)."""
    nxt: datetime | None = None
    if post.status == PostStatus.ACTIVE:
        if post.mode == SchedMode.ONCE:
            nxt = post.send_at
        elif post.mode == SchedMode.OWN:
            after = now
            if post.starts_on:
                after = max(after, day_start(post.starts_on, tz) - timedelta(seconds=1))
            nxt = next_slot(post.freq, tz, after)
            if nxt is not None and post.ends_on and nxt >= day_end(post.ends_on, tz):
                nxt = None
    post.next_send_at = nxt
    return nxt


# --------------------------------------------------------------------------- parsing user input
def _parse_hm(text: str) -> tuple[int, int]:
    text = (text or "").strip().lower().replace(" ", "")
    m = _COMPACT_RE.match(text)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
    else:
        m = _HM_RE.match(text)
        if not m:
            raise ValueError("freq.err.times")
        hh, mm = int(m.group(1)), int(m.group(2) or 0)
    if hh == 24 and mm == 0:
        hh = 0
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("freq.err.times")
    return hh, mm


def parse_every(text: str) -> int:
    """``45 min``, ``2 h``, ``1h30``, ``1:30``, ``1.5 h`` -> minutes. A bare number up to 24 is hours ("3" = 3 h),
    a bigger one minutes ("90" = 90 min). Raises ValueError("freq.err.every" | "freq.err.every_range")."""
    raw = (text or "").strip().lower().replace(",", ".")
    raw = re.sub(r"^(cada|every)\s+", "", raw)
    if len(raw) > MAX_EVERY_TEXT:
        raise ValueError("freq.err.every")
    minutes: float
    try:
        if re.fullmatch(r"\d+(?:\.\d+)?", raw):
            value = float(raw)
            minutes = value * 60 if value <= 24 else value
        elif m := re.fullmatch(r"(\d{1,2}):(\d{2})", raw):
            minutes = int(m.group(1)) * 60 + int(m.group(2))
        else:
            compact = re.sub(r"\s+", "", raw)
            m = re.fullmatch(r"(\d+(?:\.\d+)?)h(\d+)(?:m|min)?", compact)
            if m:
                minutes = float(m.group(1)) * 60 + int(m.group(2))
            else:
                m = _EVERY_RE.fullmatch(raw.replace(" y ", " ").replace(" and ", " "))
                if not m or not (m.group("h") or m.group("m")):
                    raise ValueError("freq.err.every")
                minutes = float(m.group("h") or 0) * 60 + int(m.group("m") or 0)
    except OverflowError as exc:  # a number too big for a float
        raise ValueError("freq.err.every_range") from exc
    if not MIN_EVERY <= minutes <= MAX_EVERY or minutes != int(minutes):
        raise ValueError("freq.err.every_range")
    return int(minutes)


def parse_times(text: str) -> str:
    """One or several times: "10:00, 22:00", "10 y 22", "9h 14h 21h", "0930". Returns "HH:MM,HH:MM" sorted.
    Raises ValueError("freq.err.times" | "freq.err.too_many")."""
    parts = [p for p in _SPLIT_RE.split(_SUFFIX_RE.sub(r"\1\2", (text or "").strip())) if p]
    if not parts:
        raise ValueError("freq.err.times")
    times = sorted({_parse_hm(part) for part in parts})
    if len(times) > MAX_TIMES:
        raise ValueError("freq.err.too_many")
    return ",".join(f"{h:02d}:{m:02d}" for h, m in times)


def parse_window(text: str) -> str:
    """"08:00-23:00", "8-23", "de 8 a 23" -> "08:00-23:00"; "0", "no", "-" -> "" (all day).
    Raises ValueError("freq.err.window")."""
    raw = (text or "").strip().lower()
    if raw in _NO_WINDOW:
        return ""
    m = _WINDOW_RE.match(raw)
    if not m:
        raise ValueError("freq.err.window")
    try:
        a, b = _parse_hm(m.group(1)), _parse_hm(m.group(2))
    except ValueError as exc:
        raise ValueError("freq.err.window") from exc
    if a == b:
        raise ValueError("freq.err.window")
    return f"{a[0]:02d}:{a[1]:02d}-{b[0]:02d}:{b[1]:02d}"


def parse_date(text: str, tz: str, now: datetime) -> date:
    """"dd/mm/YYYY" or "dd/mm" (this year, or the next one when it already passed), years ``MIN_YEAR`` to
    ``MAX_YEAR``. Raises ValueError("freq.err.date")."""
    m = _DATETIME_RE.match((text or "").strip())
    if not m or m.group(4):
        raise ValueError("freq.err.date")
    today = now.astimezone(zone(tz)).date()
    day, month = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else today.year
    if year < 100:
        year += 2000
    try:
        out = date(year, month, day)
    except ValueError as exc:
        raise ValueError("freq.err.date") from exc
    if not m.group(3) and out < today:
        try:
            out = date(year + 1, month, day)
        except ValueError as exc:
            raise ValueError("freq.err.date") from exc
    if not MIN_YEAR <= out.year <= MAX_YEAR:
        raise ValueError("freq.err.date")
    return out


def parse_datetime(text: str, tz: str, now: datetime) -> datetime:
    """"dd/mm/YYYY HH:MM", "dd/mm HH:MM" (the date as in ``parse_date``) or just "HH:MM" (today, or tomorrow when it
    already passed) in ``tz`` -> aware UTC. Raises ValueError("freq.err.datetime" | "freq.err.past")."""
    raw = (text or "").strip()
    z = zone(tz)
    local_now = now.astimezone(z)
    try:
        if ":" in raw and "/" not in raw and "-" not in raw and "." not in raw.split(":")[0]:
            hh, mm = _parse_hm(raw)
            out = datetime(local_now.year, local_now.month, local_now.day, hh, mm, tzinfo=z)
            if out <= local_now:
                out += timedelta(days=1)
            return out.astimezone(timezone.utc)
        m = _DATETIME_RE.match(raw)
        if not m or not m.group(4):
            raise ValueError("freq.err.datetime")
        day = parse_date(raw[: m.start(4)].strip(), tz, now)
        hh, mm = _parse_hm(m.group(4))
    except ValueError as exc:
        if str(exc) in ("freq.err.datetime", "freq.err.past"):
            raise
        raise ValueError("freq.err.datetime") from exc
    out = datetime(day.year, day.month, day.day, hh, mm, tzinfo=z)
    if out <= local_now:
        raise ValueError("freq.err.past")
    return out.astimezone(timezone.utc)


# --------------------------------------------------------------------------- describing
def every_text(minutes: int, lang: str) -> str:
    """``30 min``, ``2 h``, ``1 h 30 min``."""
    h, m = divmod(int(minutes), 60)
    if h and m:
        return t("freq.hm", lang, h=h, m=m)
    if h:
        return t("freq.h", lang, h=h)
    return t("freq.m", lang, m=m)


def days_text(days: str, lang: str) -> str:
    """``todos los días``, ``L-V``, ``S-D``, ``L, X, V``."""
    days = "".join(sorted(set(days or "")))
    if days == ALL_DAYS:
        return t("freq.days.all", lang)
    if days == WEEKDAYS:
        return t("freq.days.weekdays", lang)
    if days == WEEKEND:
        return t("freq.days.weekend", lang)
    if not days:
        return t("freq.days.none", lang)
    return ", ".join(t(f"weekday.short.{d}", lang) for d in days)


def join_list(items: list[str], lang: str) -> str:
    """``a``, ``a y b``, ``a, b y c``."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + t("freq.and", lang) + items[-1]


def times_text(times: str, lang: str) -> str:
    return join_list([f"{h:02d}:{m:02d}" for h, m in _times_of(times)], lang)


def describe(freq: dict[str, Any] | None, lang: str) -> str:
    """One line: ``cada 3 h · 08:00-23:00`` / ``10:00, 14:00 y 22:00 · L-V``."""
    f = normalize(freq)
    if f["mode"] == "times":
        parts = [t("freq.d.at", lang, times=times_text(f["times"], lang))]
    else:
        parts = [t("freq.d.every", lang, every=every_text(f["every"], lang))]
        if f["window"]:
            parts.append(f["window"])
    if f["days"] != ALL_DAYS:
        parts.append(days_text(f["days"], lang))
    return " · ".join(parts)
