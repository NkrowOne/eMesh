"""Tiny i18n layer.

Strings live in ``app/i18n/locales/<lang>_<module>.py`` files that define ``STRINGS: dict[str, str]``.
Every module owns its own files, so keys never collide (a duplicate key raises at startup).
Placeholders use ``str.format`` syntax: write literal braces as ``{{`` and ``}}``.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

log = logging.getLogger(__name__)

SUPPORTED_LANGS: tuple[str, ...] = ("es", "en")
DEFAULT_LANG = "es"
LANG_NAMES = {"es": "🇪🇸 Español", "en": "🇬🇧 English"}
LANG_FLAGS = {"es": "🇪🇸", "en": "🇬🇧"}

_CATALOG: dict[str, dict[str, str]] = {lang: {} for lang in SUPPORTED_LANGS}
_loaded = False


def load() -> None:
    global _loaded
    if _loaded:
        return
    from app.i18n import locales

    for info in sorted(pkgutil.iter_modules(locales.__path__), key=lambda m: m.name):
        lang = info.name.split("_", 1)[0]
        if lang not in _CATALOG:
            continue
        module = importlib.import_module(f"{locales.__name__}.{info.name}")
        strings: dict[str, str] = getattr(module, "STRINGS", {})
        dup = set(_CATALOG[lang]).intersection(strings)
        if dup:
            raise RuntimeError(f"Duplicated i18n keys in {info.name}: {sorted(dup)}")
        _CATALOG[lang].update(strings)
    _loaded = True


def t(key: str, lang: str = DEFAULT_LANG, /, **kwargs: object) -> str:
    if not _loaded:
        load()
    text = _CATALOG.get(lang, {}).get(key)
    if text is None:
        text = _CATALOG[DEFAULT_LANG].get(key)
    if text is None:
        log.warning("Missing i18n key: %s", key)
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            log.exception("Bad i18n format for key %s", key)
            return text
    return text


def has(key: str, lang: str = DEFAULT_LANG) -> bool:
    if not _loaded:
        load()
    return key in _CATALOG.get(lang, {})


def normalize_lang(code: str | None) -> str:
    if not code:
        return DEFAULT_LANG
    code = code.lower().split("-")[0]
    return code if code in SUPPORTED_LANGS else ("es" if code in {"es", "ca", "gl", "eu", "pt"} else "en")


def catalog() -> dict[str, dict[str, str]]:
    if not _loaded:
        load()
    return _CATALOG
