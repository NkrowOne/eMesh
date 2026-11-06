"""Review probes (UI routers): each test shows a defect found in review and fails until it is fixed."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import ChatGroup, ChatStatus, Post, Run
from app.services.scheduler import Scheduler
from app.ui.common import visible_len
from tests.conftest import MAIN_BOT_ID, SUPER_ID, App
from tests.test_engine import make_chats, make_post
from tests.test_posts_helpers import add_chat, add_group, add_post, button_texts, open_menu, started

ERROR = "⚠️ Algo ha fallado"


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """No chat refresh nor daily summary in the scheduler ticks of these tests."""
    monkeypatch.setattr(Scheduler, "_refresh_chats", AsyncMock())
    monkeypatch.setattr(Scheduler, "_summary", AsyncMock())


async def wizard_targets_step(app: App) -> None:
    """The create wizard up to step 3 (🎯 ¿A quién se envía?)."""
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "posts")
    await app.click(SUPER_ID, "Nuevo mensaje")
    await app.send(SUPER_ID, "Oferta de cine")
    await app.click(SUPER_ID, "Sin botones")
    assert "3/5" in app.last_text(SUPER_ID)


# --- HIGH: a campaign ending on 31/12/9999 is accepted and then stops every send of the network ------------------
async def test_far_future_campaign_end_does_not_stop_the_network(app: App, quiet: None) -> None:
    await make_chats(app, 2)
    forever = await make_post(app, name="Para siempre")
    await make_post(app, name="Otra promo")
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post_sched", forever)
    await app.click(SUPER_ID, "Hasta")
    await app.send(SUPER_ID, "31/12/9999")  # the usual way of writing "no end"
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        rec.rot_next_at = utcnow() - timedelta(minutes=1)  # a global slot is due
    await app.scheduler.tick()
    async with app.db() as s:
        runs = list((await s.execute(select(Run))).scalars())
    # freq.in_dates / freq.ended do ends_on + 1 day -> OverflowError: no rotation (nor scheduled) post is sent any more
    assert runs, "the whole network stopped sending"


async def test_far_future_campaign_end_keeps_the_post_screens_working(app: App) -> None:
    pid = await add_post(app, status="paused")
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post_sched", pid)
    await app.click(SUPER_ID, "Hasta")
    await app.send(SUPER_ID, "31/12/9999")
    assert "Escribe la fecha así" in app.last_text(SUPER_ID)  # refused now (years 2000-2100): asked again
    async with app.db() as s:  # but stored before that check
        (await s.get(Post, pid)).ends_on = date(9999, 12, 31)
    await open_menu(app, SUPER_ID, "post_sched", pid)
    assert "hasta el 31/12/9999" in app.last_text(SUPER_ID)
    await open_menu(app, SUPER_ID, "freq_edit", -pid)  # freqs.upcoming: ends_on + 1 day
    assert "⏰ <b>Frecuencia</b>" in app.last_text(SUPER_ID), app.last_text(SUPER_ID)[:200]


# --- LOW: the group buttons of the target picker count chats that left the network ------------------------------
async def test_target_picker_counts_only_the_chats_of_the_network(app: App) -> None:
    a = await add_chat(app, -1001, "Cine HD")
    b = await add_chat(app, -1002, "Cine Club")
    left = await add_chat(app, -1003, "Se fue", status=ChatStatus.LEFT)  # groups are kept when a chat leaves
    banned = await add_chat(app, -1004, "Bloqueado", status=ChatStatus.BANNED)
    gid = await add_group(app, "Cine", (a, b, left, banned))
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "group", gid)
    assert "📣 Chats: <b>2</b>" in app.last_text(SUPER_ID)
    await wizard_targets_step(app)
    assert "⚪ Cine (2)" in button_texts(app), button_texts(app)  # shows "⚪ Cine (4)"


# --- LOW/MEDIUM: Telegram limits ------------------------------------------------------------------------------
async def test_posts_list_fits_the_telegram_text_limit(app: App) -> None:
    names = [f"{i:02d} Canales de cine, series y estrenos en español latino" for i in range(6)]
    gids = [await add_group(app, name) for name in names]
    for i in range(10):
        await add_post(app, name=f"Promo de estrenos de la semana número {i}", targets=[f"g{g}" for g in gids])
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "posts")
    assert visible_len(app.last_text(SUPER_ID)) <= 4096  # every target group is listed in full: 4,228


async def test_target_picker_fits_the_telegram_keyboard_limit(app: App) -> None:
    async with app.db() as s:
        s.add_all([ChatGroup(bot_id=MAIN_BOT_ID, name=f"Grupo {i}") for i in range(95)])
    await wizard_targets_step(app)
    assert len(button_texts(app)) <= 100  # one button per group, no pages: 101 buttons


# --- LOW: numeric inputs that crash instead of asking again ----------------------------------------------------
async def test_superscript_digit_in_the_max_per_day_input_is_refused(app: App) -> None:
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "antispam")
    await app.click(SUPER_ID, "Otro máximo")
    await app.send(SUPER_ID, "²")  # str.isdigit() is True, int() raises ValueError
    text = app.last_text(SUPER_ID)
    assert not text.startswith(ERROR) and "Escribe un número del 0 al 100" in text, text


async def test_huge_number_in_the_auto_delete_input_is_refused(app: App) -> None:
    pid = await add_post(app)
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post_opts", pid)
    await app.click(SUPER_ID, "Otro")
    await app.send(SUPER_ID, "9" * 400)  # float() -> inf, int(inf) -> OverflowError
    text = app.last_text(SUPER_ID)
    assert not text.startswith(ERROR) and "Elige entre 15 minutos y 48 horas" in text, text


async def test_once_date_in_year_9999_west_of_utc_is_refused(app: App) -> None:
    async with app.db() as s:
        rec = await s.get(BotRecord, MAIN_BOT_ID)
        rec.timezone, rec.timezone_set = "America/New_York", True
    pid = await add_post(app)
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post_sched", pid)
    await app.click(SUPER_ID, "Una sola vez")
    await app.send(SUPER_ID, "31/12/9999 23:59")  # parse_when only catches ValueError: OverflowError escapes
    text = app.last_text(SUPER_ID)
    assert not text.startswith(ERROR), text
