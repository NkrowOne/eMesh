# CLAUDE.md - AI Assistant Guidelines for eMesh

> This file provides context and guidelines for AI assistants working with this codebase.

## Project Overview

**Repository**: eMesh
**What**: Telegram message distribution network. An owner adds the bot to their channels/groups (and optionally lets
partners add theirs), writes posts (text/media + colored buttons) and the bot publishes each one at its own times
(there is no rotation; new posts start with the network's default schedule). Partners can pause the distribution in
their chats; the owner is alerted. One process runs the main bot (platform: clones + 👑 panel) plus every clone.
**Stack**: Python 3.12+, aiogram 3.31 (Bot API 10.3), SQLAlchemy 2.1 async (PostgreSQL / SQLite in tests), Alembic,
pydantic-settings.
**Spec**: `docs/ARCHITECTURE.md` (rules, screens, engine, interfaces, ownership). Read it before changing code.

---

## Quick Reference

```bash
pip install -r requirements-dev.txt   # install
python -m app                          # run (needs .env, see .env.example)
pytest -q                              # all tests, in parallel (fake Telegram server, no token needed)
alembic revision --autogenerate -m "msg"   # new migration (needs DATABASE_URL + BOT_TOKEN env)
alembic upgrade head                   # migrations also run automatically at startup
```

```
app/
  main.py, __main__.py   entry point and wiring
  config.py              Settings (env vars)
  db/                    models (tables prefixed em_), session, Alembic migrations
  telegram/              BotManager (multi-bot), rate limiter, FSM storage, errors, token cipher
  bot/                   Ctx (+ workspace) + middlewares, filters, routers (one module per feature)
  services/              business logic (content, freq, audience, events, publisher, scheduler, chats, clones...)
  ui/                    show()/prompt()/btn() helpers, formatting, screens registry, callbacks
  i18n/locales/          es_<module>.py / en_<module>.py
tests/                   fake_tg.py (fake Bot API), conftest.py (app fixture), test_*.py
```

## Development Guidelines

- Follow `docs/ARCHITECTURE.md` section 1 (ground rules): i18n for every text, escape user input, permission checks
  in every handler (rows must belong to `ctx.ws_id`), `show()`/`toast()` instead of raw answers, background jobs use
  `set_low_priority()` and short DB transactions, never mutate JSON columns in place.
- All Telegram calls go through the rate limiter automatically; don't add sleeps.
- Model changes need an Alembic migration (`alembic revision --autogenerate`).
- ES and EN locale files must have the same keys and placeholders (enforced by tests).
- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.

## AI Assistant Instructions

1. Always read existing code first before making changes.
2. Keep changes minimal; follow existing patterns; no speculative features.
3. No print statements (use `logging`); handle Telegram errors; write tests with the fake Telegram server.
4. Avoid security issues: HTML injection in messages (escape user values), forged callback data (check rights and
   ownership in every handler), secrets in logs (bot tokens).
