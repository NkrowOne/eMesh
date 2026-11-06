"""Platform blocked words: an external chat whose name, @username or description contains one is refused.

The list lives in KV ``platform:words`` (``DEFAULT_BLOCKED_WORDS`` until a super admin changes it): terms used to
share abuse of minors and intimate images without consent. Matching ignores case, accents, leetspeak, look-alike
letters, invisible characters, repeated letters and letters spelled one by one; ``word*`` matches anything that
starts with it and a line of emojis matches when all of them are in the text.
"""
from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from app.db.base import utcnow
from app.db.models import KV

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

PLATFORM_KEY = "platform:words"
LIST_MAX = 200  # words per list
LISTS = 2  # lists per owner (and for the platform): when one is full the next one is used
PREFIX = "*"  # "filtrad*": anything that starts with it ("FILTRADOS"); without it, the whole word or phrase

# Protection of minors: the slang and emoji combinations used to share abuse material, in several languages.
# Combinations of emojis ("🍕 👧") match when all of them are in the text.
CHILD_SAFETY_WORDS: list[str] = [
    "cp", "pthc", "ptsc", "pedo", "pedos", "pedofil*", "pedophil*", "paedo*", "pederast*", "pedobear",
    "loli", "lolis", "lolita*", "lolicon", "shota", "shotas", "shotacon", "toddlercon", "jailbait*", "preteen*",
    "pre teen*", "underage", "under age", "menores", "menor de edad", "menores de edad", "menor de idade",
    "porno infantil", "pornografia infantil", "sexo infantil", "abuso infantil", "child porn*", "child sex*",
    "kid porn*", "kiddie porn*", "kiddy porn*", "cheese pizza", "pizza de queso", "caldo de pollo",
    "packs de menores", "packs menores", "pack menores", "nudes menores", "novinhas menores",
    "🍕 👧", "🍕 👦", "🍕 🧒", "🍕 👶", "🧀 🍕", "🍭 👧", "🍬 👧", "🔞 👧", "🔞 👦", "🔞 🧒", "🔞 👶",
]
# Intimate images without consent and "undress" bots.
NON_CONSENSUAL_WORDS: list[str] = [
    "filtrad*", "leak*", "desnud*", "desvest*", "undress*", "nudify*", "deepnude*", "deepfake*",
]
# The platform list until a super admin writes their own.
DEFAULT_BLOCKED_WORDS: list[str] = [*CHILD_SAFETY_WORDS, *NON_CONSENSUAL_WORDS]

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i",
                       "|": "i", "€": "e"})
# Cyrillic and Greek letters that look like Latin ones ("рedо" written with Cyrillic р and о).
_LOOKALIKES = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i",
                             "ѕ": "s", "к": "k", "м": "m", "т": "t", "в": "b", "н": "h", "α": "a", "ο": "o",
                             "ρ": "p", "ν": "v", "ι": "i", "κ": "k", "τ": "t"})
_EMOJI_MODIFIERS = {"️", "︎", "‍", "⃣"} | {chr(c) for c in range(0x1F3FB, 0x1F400)}


def _is_emoji(char: str) -> bool:
    return unicodedata.category(char) == "So" or 0x1F000 <= ord(char) <= 0x1FAFF


def emojis_of(text: str) -> list[str]:
    """The emojis of ``text`` without skin tones or variation selectors (👧🏻 -> 👧)."""
    return [c for c in text or "" if c not in _EMOJI_MODIFIERS and _is_emoji(c)]


def normalize(text: str) -> str:
    """Lower case words without accents, symbols or tricks: leetspeak, look-alike letters, invisible characters
    and repeated letters (``P3D0``, ``peeedo`` and ``рedо`` with Cyrillic letters all become ``pedo``)."""
    text = "".join(c for c in unicodedata.normalize("NFKC", text or "") if unicodedata.category(c) != "Cf")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = text.casefold().translate(_LOOKALIKES).translate(_LEET)
    # Letters and digits of every script are kept (Cyrillic, Greek, Arabic... words must work too).
    text = re.sub(r"[\W_]+", " ", text).strip()
    return re.sub(r"(\w)\1+", r"\1", text)


def _join_spelled(text: str) -> str:
    """Letters written one by one ("c p", "p e d o", from "c.p" or "p-e-d-o") joined back into words."""
    return re.sub(r"\b(?:\w )+\w\b", lambda m: m.group(0).replace(" ", ""), text)


def entry_text(word: str) -> str:
    """How a list entry is stored and shown: lower case as written (``*`` kept), or its emojis."""
    raw = re.sub(r"\s+", " ", (word or "").strip())
    if not normalize(raw):
        return " ".join(emojis_of(raw))
    return raw.casefold()


def entry_key(word: str) -> str:
    """What an entry is compared with: ``normalize`` + letters joined (keeping a final ``*``), or its emojis."""
    raw = (word or "").strip()
    text = _join_spelled(normalize(raw))
    if not text:
        return " ".join(sorted(set(emojis_of(raw))))
    return text + PREFIX if raw.endswith(PREFIX) else text


def parse_words(text: str, limit: int | None = LIST_MAX) -> list[str]:
    """One word/phrase per line (or comma separated), unique, max ``limit``. ``word*`` matches anything that
    starts with it; a line of emojis matches when all of them are in the text."""
    out: list[str] = []
    keys: set[str] = set()
    for part in re.split(r"[\n,;]+", text or ""):
        key = entry_key(part)
        if key and key not in keys:
            keys.add(key)
            out.append(entry_text(part))
    return out if limit is None else out[:limit]


def find_in_chat(words: list[str], title: str | None, username: str | None, description: str | None) -> str | None:
    """A blocked word in the name, the @username or the description of a chat."""
    return find_blocked(" \n ".join(x for x in (title, username, description) if x), words)


def find_blocked(text: str, words: list[str]) -> str | None:
    """Returns the first entry of ``words`` found in ``text`` or None."""
    base = normalize(text)
    hays = {f" {base} ", f" {_join_spelled(base)} "}
    present = set(emojis_of(text))
    for word in words or []:
        key = entry_key(word)
        if not key:
            continue
        if not normalize(key):  # emoji entry: every emoji of it must be in the text
            if all(e in present for e in key.split()):
                return word
            continue
        w = re.escape(key.rstrip(PREFIX))
        pattern = rf" {w}" if key.endswith(PREFIX) else rf" {w} "
        if any(re.search(pattern, hay) for hay in hays):
            return word
    return None


# --------------------------------------------------------------------------- word lists
Lists = list[list[str]]


def _clean(lists: object) -> Lists:
    out: Lists = []
    for value in lists if isinstance(lists, list) else []:
        out.append([str(w) for w in value if isinstance(w, str) and w][:LIST_MAX] if isinstance(value, list) else [])
    out = out[:LISTS]
    return out + [[] for _ in range(LISTS - len(out))]


def flatten(lists: Lists) -> list[str]:
    out: list[str] = []
    for words in lists:
        out += [w for w in words if w not in out]
    return out


def add_words(lists: Lists, words: list[str]) -> tuple[Lists, int, int]:
    """Appends the new ``words`` to the first list with room, then the next one.

    Returns ``(new lists, added, left out because every list is full)``.
    """
    new = [list(x) for x in _clean(lists)]
    known = {entry_key(w) for w in flatten(new)}
    added = left = 0
    for word in words:
        key = entry_key(word)
        if not key or key in known:
            continue
        target = next((x for x in new if len(x) < LIST_MAX), None)
        if target is None:
            left += 1
            continue
        target.append(word)
        known.add(key)
        added += 1
    return new, added, left


def remove_words(lists: Lists, words: list[str]) -> tuple[Lists, int]:
    """Removes ``words`` from every list. Returns ``(new lists, how many were removed)``."""
    drop = {entry_key(w) for w in words}
    new = [[w for w in x if entry_key(w) not in drop] for x in _clean(lists)]
    return new, sum(len(x) for x in _clean(lists)) - sum(len(x) for x in new)


async def platform_lists(session: AsyncSession) -> Lists:
    """The platform's fixed lists (the default list until a super admin changes it)."""
    rec = await session.get(KV, PLATFORM_KEY)
    if rec is None:
        return _clean([list(DEFAULT_BLOCKED_WORDS)])
    return _clean(rec.value)


async def save_platform_lists(session: AsyncSession, lists: Lists) -> None:
    rec = await session.get(KV, PLATFORM_KEY)
    if rec is None:
        session.add(KV(key=PLATFORM_KEY, value=_clean(lists), updated_at=utcnow()))
    else:
        rec.value = _clean(lists)
        rec.updated_at = utcnow()


async def platform_words(session: AsyncSession) -> list[str]:
    return flatten(await platform_lists(session))


async def check_chat(session: AsyncSession, title: str | None, username: str | None,
                     description: str | None) -> str | None:
    """The platform word found in a chat's name, @username or description (None when it is clean)."""
    return find_in_chat(await platform_words(session), title, username, description)
