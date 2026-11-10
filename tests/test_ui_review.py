"""Fixes of the UI review (see test_review_probes_ui.py): typed dates within 2000-2100 and far dates stored before,
long lists of targets, the cap of groups of chats and numeric inputs at the edge."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.bot.routers.groups import MAX_GROUPS, GrCB
from app.bot.routers.posts import parse_minutes
from app.db.base import utcnow
from app.db.models import ChatGroup, Post, PostStatus, Run, SchedMode
from app.services import freq
from app.services.scheduler import Scheduler
from tests.conftest import MAIN_BOT_ID, SUPER_ID, App
from tests.test_engine import make_chats, make_post
from tests.test_posts_helpers import add_group, add_post, answers, button_texts, open_menu, started

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
NY = "America/New_York"
HOURLY = {"mode": "interval", "every": 60, "window": "", "days": "0123456"}
GROUPS_LIMIT = (f"🔒 Esta red ya tiene el máximo de grupos de canales ({MAX_GROUPS}). Elimina alguno que ya no uses "
                "para crear otro.")


def error_of(parse: object, *args: object) -> str:
    with pytest.raises(ValueError) as err:
        parse(*args)  # type: ignore[operator]
    return str(err.value)


# --------------------------------------------------------------------------- far dates
@pytest.mark.parametrize("day", ["31/12/9999", "31/12/1999", "01/01/2101", "01/01/0100"])
def test_typed_dates_outside_2000_2100_are_refused(day: str) -> None:
    assert error_of(freq.parse_date, day, NY, NOW) == "freq.err.date"
    assert error_of(freq.parse_datetime, f"{day} 23:59", NY, NOW) == "freq.err.datetime"


def test_typed_dates_up_to_2100_are_accepted() -> None:
    assert freq.parse_date("31/12/2100", NY, NOW) == date(2100, 12, 31)
    assert freq.parse_date("25/12/26", NY, NOW) == date(2026, 12, 25)
    assert freq.parse_datetime("31/12/2100 23:59", NY, NOW) == datetime(2101, 1, 1, 4, 59, tzinfo=timezone.utc)


def test_campaign_math_with_the_last_day_of_the_calendar() -> None:
    post = Post(status=PostStatus.ACTIVE, mode=SchedMode.OWN, freq=HOURLY, ends_on=date(9999, 12, 31))
    assert freq.day_end(date(9999, 12, 31), NY) == datetime.max.replace(tzinfo=timezone.utc)
    assert freq.in_dates(post, NY, NOW) and not freq.ended(post, NY, NOW)
    assert freq.refresh_post(post, NY, NOW) == datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc)


async def test_far_end_dates_stored_before_the_fix_keep_working(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Scheduler, "_refresh_chats", AsyncMock())
    monkeypatch.setattr(Scheduler, "_summary", AsyncMock())
    await make_chats(app, 2)
    forever = await make_post(app, name="Para siempre", ends_on=date(9999, 12, 31))
    paused = await make_post(app, name="En pausa", ends_on=date(9999, 12, 31), status=PostStatus.PAUSED)
    async with app.db() as s:
        for pid in (forever, paused):
            (await s.get(Post, pid)).next_send_at = utcnow() - timedelta(minutes=1)  # due (the paused one never goes)
    await app.scheduler.tick()
    async with app.db() as s:
        assert [run.post_id for run in (await s.execute(select(Run))).scalars()] == [forever]
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post", paused)
    await app.click(SUPER_ID, "Activar")  # its campaign isn't over
    assert "📌 Estado: ▶️ Activo" in app.last_text(SUPER_ID)


# --------------------------------------------------------------------------- numeric inputs at the edge
@pytest.mark.parametrize("text", ["1h" + "9" * 400, "9" * 400, "1 h " + "9" * 400 + " min", "²"])
def test_odd_intervals_are_refused(text: str) -> None:
    assert error_of(freq.parse_every, text) == "freq.err.every"  # nobody writes an interval that long


@pytest.mark.parametrize("text", ["9" * 400, "1h" + "9" * 400 + "m", "9" * 400 + " h"])
def test_huge_auto_delete_times_are_out_of_range(text: str) -> None:
    assert error_of(parse_minutes, text) == "po.err.duration_range"


async def test_admin_command_with_odd_digits_finds_nobody(app: App) -> None:
    await started(app, SUPER_ID)
    for query in ("²", "①", "--5", "9" * 25):  # int() refuses them or the id doesn't fit a BIGINT
        await app.send(SUPER_ID, f"/admin {query}")
        assert app.last_text(SUPER_ID) == ("⚠️ No se ha encontrado a esa persona. Antes debe abrir @emesh_test_bot y "
                                           "pulsar /start."), query


# --------------------------------------------------------------------------- groups of chats
async def test_a_network_has_at_most_max_groups(app: App) -> None:
    async with app.db() as s:
        s.add_all([ChatGroup(bot_id=MAIN_BOT_ID, name=f"Grupo {i}") for i in range(MAX_GROUPS - 1)])
    await started(app, SUPER_ID)
    await app.press(SUPER_ID, GrCB(a="new").pack())  # the last one: its name is asked
    assert "<b>Nuevo grupo de canales</b>" in app.last_text(SUPER_ID)
    await add_group(app, "De otro admin")  # created meanwhile
    await app.send(SUPER_ID, "Cine")
    text = app.last_text(SUPER_ID)
    assert text.startswith(GROUPS_LIMIT + "\n\n🗂 <b>Grupos de canales</b>"), text
    await app.press(SUPER_ID, GrCB(a="new").pack())
    assert answers(app)[-1] == GROUPS_LIMIT and app.last_text(SUPER_ID) == text  # no name prompt
    async with app.db() as s:
        assert await s.scalar(select(func.count()).select_from(ChatGroup)) == MAX_GROUPS
        assert await s.scalar(select(func.count()).where(ChatGroup.name == "Cine")) == 0


async def test_long_lists_of_targets_are_summarised(app: App) -> None:
    gids = [await add_group(app, f"{i:02d} Canales de cine y series en español latino") for i in range(12)]
    pid = await add_post(app, targets=["own", *(f"g{g}" for g in gids)])
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "posts")
    assert ("└🎯 Propios, 00 Canales de cine y series e…, 01 Canales de cine y series e… +10 más · "
            in app.last_text(SUPER_ID))
    await open_menu(app, SUPER_ID, "post", pid)
    text = app.last_text(SUPER_ID)
    assert "🎯 Destino: 🏠 Propios, 🗂 00 Canales de cine y series e…, 🗂 01 Canales" in text
    assert "🗂 09 Canales de cine y series e… +2 más → 0 chats" in text and "🗂 10 " not in text


async def test_target_picker_with_too_many_groups_keeps_the_chosen_ones(app: App) -> None:
    async with app.db() as s:  # a network from before the cap of groups
        groups = [ChatGroup(bot_id=MAIN_BOT_ID, name=f"Grupo {i}") for i in range(70)]
        s.add_all(groups)
        await s.flush()
        chosen = groups[-1].id
    pid = await add_post(app, targets=[f"g{chosen}"])
    await started(app, SUPER_ID)
    await open_menu(app, SUPER_ID, "post_targets", pid)
    texts = button_texts(app)
    assert len(texts) <= 100 and "✅ Grupo 69 (0)" in texts and "⚪ Grupo 58 (0)" in texts
    assert "⚪ Grupo 59 (0)" not in texts
