"""🧭 Setup wizard of a new bot: one question per screen, the current value pre-selected, each answer saved at once.

The owner of a new clone goes through it on the first /start, right after choosing the timezone (``needs_setup``),
and can run it again from ⚙️ Ajustes. ``setup`` arg = step: 1 external chats, 2 the partners' pauses (only when
external chats are accepted), 3 the rotation (posts take turns, or each one has its own schedule), 4 the hours of the
rotation (only with rotation), 5 how long posts stay published, 6 the summary (done).

Step 4 is not a single choice: the hours it publishes at stay on screen and are changed there (quick options, the 24
hours to tick, the days, or typed times) until ``Continuar``.
"""
from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.routers.settings import PAUSE_MAX_CHOICES, duration_text, externals_line, pause_max_text, with_notice
from app.data.timezones import utc_offset_label
from app.db.base import utcnow
from app.db.models import DEFAULT_DELETE_AFTER, Post, RotationOrder, rotation_on
from app.db.models import Bot as BotRecord
from app.services import freq
from app.services.chatinfo import add_to_channel_url, add_to_group_url
from app.services.scheduler import Scheduler
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, choice_label, grid, kb, prompt, show
from app.ui.fmt import esc, truncate
from app.ui.screens import open_screen, screen

router = Router(name="setup")

JOIN_STEP, PAUSE_STEP, ROTATION_STEP, FREQ_STEP, DELETE_STEP, SUMMARY = range(1, 7)  # SUMMARY: «✅ Todo listo»
WINDOW = "08:00-22:00"
# Step 1: (join_open, join_approval); None leaves the approval as it is (it doesn't matter while closed).
JOIN_OPTIONS: tuple[tuple[bool, bool | None], ...] = ((True, True), (True, False), (False, None))
# Step 2: the longest pause of a partner in hours (0 = until they resume it); None: partners can't pause.
PAUSE_OPTIONS: tuple[int | None, ...] = (*PAUSE_MAX_CHOICES, None)
# Step 3: ``Bot.rotation``: the posts take turns in order or at random, or no rotation (each post has its own schedule).
ROTATION_OPTIONS = (RotationOrder.SEQUENTIAL, RotationOrder.RANDOM, RotationOrder.OFF)
# Step 4: quick options of the global frequency (they set the hours; the days stay): 1 a day at 12:00 (the default),
# 2, 3 or 4 a day, every 2 h or every hour from 08:00 to 22:00.
FREQ_PRESETS: tuple[dict[str, Any], ...] = tuple(freq.normalize(f) for f in (
    {"mode": "times", "times": "12:00"},
    {"mode": "times", "times": "10:00,20:00"},
    {"mode": "times", "times": "09:00,14:00,20:00"},
    {"mode": "times", "times": "09:00,13:00,17:00,21:00"},
    {"mode": "interval", "every": 120, "window": WINDOW},
    {"mode": "interval", "every": 60, "window": WINDOW},
))
DAY_PRESETS = (freq.ALL_DAYS, freq.WEEKDAYS, freq.WEEKEND)
HOUR_COLS = 6  # the 24 hours in 4 rows
# Step 5: how long new posts stay published, in minutes (0 = never deleted).
DELETE_OPTIONS = (60, 360, 720, 1440, 2880, 0)
OPTIONS: dict[int, tuple[Any, ...]] = {JOIN_STEP: JOIN_OPTIONS, PAUSE_STEP: PAUSE_OPTIONS,
                                       ROTATION_STEP: ROTATION_OPTIONS, DELETE_STEP: DELETE_OPTIONS}
# Buttons per row of each step.
LAYOUT = {JOIN_STEP: (1, 1, 1), PAUSE_STEP: (1, 1, 1, 1, 1), ROTATION_STEP: (1, 1, 1), DELETE_STEP: (3, 2, 1)}
KEEP_MAX = 45  # characters of a current value shown on its «Mantener» button


class SuCB(CallbackData, prefix="su"):
    """Answer ``v`` (the index of the chosen option) to step ``s``; ``s=0`` skips the wizard."""

    s: int
    v: int = 0


class SuFqCB(CallbackData, prefix="suf"):
    """Step 4 (the hours of the rotation): ``a`` = ``p`` quick option ``v``, ``h`` tick/untick the hour ``v``,
    ``d`` days preset ``v``, ``w`` type the times."""

    a: str
    v: int = 0


class SetupFSM(StatesGroup):
    times = State()


def needs_setup(ctx: Ctx) -> bool:
    """The owner of a new clone hasn't been through the wizard: it comes after the timezone, before the home."""
    rec = ctx.bot_rec
    return not rec.is_main and not rec.setup_done and ctx.user_id == rec.owner_id


def can_setup(ctx: Ctx) -> bool:
    """The owner of the network (or a super admin) in the bot itself, never while managing a clone."""
    return ctx.is_owner and not ctx.in_ws and not ctx.is_hub


def delete_after_of(ws: BotRecord) -> int:
    """Minutes new posts stay published (``Bot.post_defaults``, else the default; 0 = never deleted)."""
    stored = ws.post_defaults.get("delete_after") if isinstance(ws.post_defaults, dict) else None
    return stored if isinstance(stored, int) and stored >= 0 else DEFAULT_DELETE_AFTER


def _current(ws: BotRecord, step: int) -> int | None:
    """The option that is the current value of the network (None: a value set somewhere else)."""
    if step == JOIN_STEP:
        return (0 if ws.join_approval else 1) if ws.join_open else 2
    value: Any
    if step == PAUSE_STEP:
        value = ws.pause_max_hours if ws.partners_can_pause else None
    elif step == ROTATION_STEP:  # an unknown value works as «en orden» (⏰ Frecuencias does the same)
        value = ws.rotation if ws.rotation in ROTATION_OPTIONS else RotationOrder.SEQUENTIAL
    else:
        value = delete_after_of(ws)
    return OPTIONS[step].index(value) if value in OPTIONS[step] else None


def _skipped(ws: BotRecord, step: int) -> bool:
    """The partners' step only when external chats are accepted; the hours only with rotation."""
    return (step == PAUSE_STEP and not ws.join_open) or (step == FREQ_STEP and not rotation_on(ws.rotation))


def _next(ws: BotRecord, step: int) -> int:
    step += 1
    while _skipped(ws, step):
        step += 1
    return step


def _previous(ws: BotRecord, step: int) -> int:
    step -= 1
    while _skipped(ws, step):
        step -= 1
    return step


def _save(ws: BotRecord, step: int, index: int) -> None:
    if step == JOIN_STEP:
        ws.join_open, approval = JOIN_OPTIONS[index]
        if approval is not None:
            ws.join_approval = approval
    elif step == PAUSE_STEP:
        hours = PAUSE_OPTIONS[index]
        ws.partners_can_pause = hours is not None
        if hours is not None:
            ws.pause_max_hours = hours
    elif step == ROTATION_STEP:
        ws.rotation = ROTATION_OPTIONS[index]
    else:
        stored = ws.post_defaults if isinstance(ws.post_defaults, dict) else {}
        ws.post_defaults = {**stored, "delete_after": DELETE_OPTIONS[index]}  # a new dict: JSON column


# ---------------------------------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------------------------------
def _labels(ctx: Ctx, step: int) -> list[str]:
    if step == JOIN_STEP:
        labels = [ctx.t("setup.join.approval"), ctx.t("setup.join.auto"), ctx.t("setup.join.closed")]
    elif step == PAUSE_STEP:
        labels = [ctx.t("setup.pause.upto", t=pause_max_text(ctx, hours)) if hours else pause_max_text(ctx, 0)
                  for hours in PAUSE_MAX_CHOICES]
        labels.append(ctx.t("setup.pause.no"))
    elif step == ROTATION_STEP:
        labels = [ctx.t(f"setup.rot.{order}") for order in ROTATION_OPTIONS]
    else:
        labels = [duration_text(ctx, minutes) if minutes else ctx.t("setup.delete.never") for minutes in DELETE_OPTIONS]
    return labels


def _value_text(ctx: Ctx, step: int) -> str:
    """The current value of a step when it isn't one of its options (set in ⏰ Frecuencias, ⚙️ Opciones…)."""
    ws = ctx.ws_rec
    if step == PAUSE_STEP:
        return ctx.t("setup.sum.pause.upto", t=pause_max_text(ctx, ws.pause_max_hours))
    return duration_text(ctx, delete_after_of(ws))


def _question(ctx: Ctx, step: int) -> tuple[str, InlineKeyboardMarkup]:
    ws = ctx.ws_rec
    current = _current(ws, step)
    buttons = [btn(choice_label(label, i == current), SuCB(s=step, v=i)) for i, label in enumerate(_labels(ctx, step))]
    rows: list[list[InlineKeyboardButton]] = []
    for size in LAYOUT[step]:
        rows.append(buttons[:size])
        buttons = buttons[size:]
    if current is None:  # a value chosen elsewhere is pre-selected too: keeping it goes on to the next step
        keep = ctx.t("setup.keep", v=truncate(_value_text(ctx, step), KEEP_MAX))
        rows.insert(0, [btn(choice_label(keep, True), MenuCB(screen="setup", arg=_next(ws, step)))])
    if step == JOIN_STEP:
        rows.append([btn(ctx.t("setup.btn.skip"), SuCB(s=0))])
        return f"{ctx.t('setup.intro')}\n\n{ctx.t('setup.q.1')}", kb(*rows)
    rows.append(back_row(ctx.lang, "setup", _previous(ws, step)))
    return ctx.t(f"setup.q.{step}"), kb(*rows)


# --- step 4: the hours of the rotation (the global frequency) -------------------------------------------
def _save_freq(ws: BotRecord, new: dict[str, Any]) -> None:
    ws.freq = freq.normalize(new)  # a new dict: JSON column
    freq.refresh_bot(ws, utcnow())


def _with_days(f: dict[str, Any], days: str) -> dict[str, Any]:
    return freq.normalize({**f, "days": days})


def _times_dict(times: set[tuple[int, int]] | list[tuple[int, int]], days: str) -> dict[str, Any]:
    return freq.normalize({"mode": "times", "times": ",".join(f"{h:02d}:{m:02d}" for h, m in sorted(times)),
                           "days": days})


def _hours_text(ctx: Ctx, f: dict[str, Any]) -> str:
    """``10:00, 14:00 y 20:00``: every time of a day (a long interval, «cada 30 min», is described instead)."""
    times = freq.day_times(f)
    if len(times) > freq.MAX_TIMES:
        return freq.describe(f, ctx.lang)
    return freq.join_list([f"{h:02d}:{m:02d}" for h, m in times], ctx.lang)


def _preset_label(ctx: Ctx, f: dict[str, Any]) -> str:
    if f["mode"] == "times":
        return ctx.t("setup.freq.n", n=freq.per_day(f))
    if f["every"] == 60:
        return ctx.t("setup.freq.hourly")
    return ctx.t("setup.freq.every", t=freq.every_text(f["every"], ctx.lang))


def _freq_question(ctx: Ctx) -> tuple[str, InlineKeyboardMarkup]:
    """The hours it publishes at, with the quick options, the 24 hours to tick, the days and typed times."""
    ws = ctx.ws_rec
    f = freq.normalize(ws.freq)
    ticked = {h for h, _ in freq.day_times(f)}
    text = "\n".join([
        ctx.t(f"setup.q.{FREQ_STEP}"),
        "",
        ctx.t("setup.freq.now", n=freq.per_day(f), times=_hours_text(ctx, f)),
        ctx.t("setup.freq.days", days=freq.days_text(f["days"], ctx.lang)),
        ctx.t("setup.freq.tz", tz=esc(ctx.bot_tz)),
    ])
    presets = [btn(choice_label(_preset_label(ctx, p), _with_days(p, f["days"]) == f), SuFqCB(a="p", v=i))
               for i, p in enumerate(FREQ_PRESETS)]
    hours = [btn(f"✅ {h:02d}" if h in ticked else f"{h:02d}", SuFqCB(a="h", v=h)) for h in range(24)]
    days = [btn(choice_label(ctx.t(f"setup.days.{i}"), f["days"] == d), SuFqCB(a="d", v=i))
            for i, d in enumerate(DAY_PRESETS)]
    rows = [
        *grid(presets, 3),
        *grid(hours, HOUR_COLS),
        days,
        [btn(ctx.t("setup.freq.write"), SuFqCB(a="w"))],
        [btn(ctx.t("setup.btn.next"), MenuCB(screen="setup", arg=_next(ws, FREQ_STEP)), style="success")],
        back_row(ctx.lang, "setup", _previous(ws, FREQ_STEP)),
    ]
    return text, kb(*rows)


def _toggled(f: dict[str, Any], hour: int) -> set[tuple[int, int]]:
    """The times of a day with ``hour`` unticked (all its times, 09:00 and 09:30) or ticked (``hour``:00). A long
    interval («cada 30 min») keeps only its o'clock times."""
    times = freq.day_times(f)
    if len(times) > freq.MAX_TIMES:
        times = [hm for hm in times if hm[1] == 0]
    if any(h == hour for h, _ in times):
        return {hm for hm in times if hm[0] != hour}
    return {*times, (hour, 0)}


async def _ask_times(event: Message | CallbackQuery, ctx: Ctx, state: FSMContext, error: str | None = None) -> None:
    await state.set_state(SetupFSM.times)
    text = ctx.t("setup.freq.ask", current=_hours_text(ctx, freq.normalize(ctx.ws_rec.freq)))
    await prompt(event, ctx, with_notice(text, error), cancel_screen="setup", cancel_arg=FREQ_STEP)


def _pause_rule(ctx: Ctx) -> str:
    ws = ctx.ws_rec
    if not ws.partners_can_pause:
        return ctx.t("setup.sum.pause.no")
    if not ws.pause_max_hours:
        return ctx.t("setup.sum.pause.free")
    return ctx.t("setup.sum.pause.upto", t=pause_max_text(ctx, ws.pause_max_hours))


async def _summary(ctx: Ctx, session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    """«✅ Todo listo»: the answers, and what to do next. The wizard is done from here on."""
    ws = ctx.ws_rec
    ws.setup_done = True
    minutes = delete_after_of(ws)
    lines = [ctx.t("setup.done"), "", externals_line(ctx)]
    if ws.join_open:
        lines.append(ctx.t("setup.sum.pause", v=_pause_rule(ctx)))
    order = OPTIONS[ROTATION_STEP][_current(ws, ROTATION_STEP) or 0]
    lines.append(ctx.t("setup.sum.rot", v=ctx.t(f"setup.sum.rot.{order}")))
    if rotation_on(order):
        lines.append(ctx.t("home.freq", freq=freq.describe(ws.freq, ctx.lang)))
    lines += [
        ctx.t("setup.sum.delete", v=ctx.t("setup.sum.after", t=duration_text(ctx, minutes)) if minutes
              else ctx.t("setup.sum.never")),
        ctx.t("set.tz", tz=esc(ctx.bot_tz), offset=utc_offset_label(ctx.bot_tz)),
        "",
        ctx.t("setup.done.next"),
    ]
    rows: list[list[InlineKeyboardButton]] = []
    if ws.username:
        rows.append([btn(ctx.t("home.btn.add_channel"), url=add_to_channel_url(ws.username)),
                     btn(ctx.t("home.btn.add_group"), url=add_to_group_url(ws.username))])
    posts = int((await session.execute(
        select(func.count()).select_from(Post).where(Post.bot_id == ws.id))).scalar() or 0)
    rows += [
        [btn(ctx.t("setup.btn.new_post" if posts else "setup.btn.first_post"), MenuCB(screen="post_new"),
             style="success")],
        [btn(ctx.t("setup.btn.home"), MenuCB(screen="home"))],
        back_row(ctx.lang, "setup", _previous(ws, SUMMARY)),
    ]
    return "\n".join(lines), kb(*rows)


@screen("setup")
async def setup_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, notice: str | None = None,
    **_: object,
) -> None:
    """``arg``: the step, 1-6 (a skipped one shows the next)."""
    if not can_setup(ctx):
        await alert(event, ctx.t("common.no_permission"))
        return
    step = min(max(arg, 1), SUMMARY)
    if _skipped(ctx.ws_rec, step):
        step = _next(ctx.ws_rec, step)
    if step == SUMMARY:
        text, markup = await _summary(ctx, session)
    else:
        text, markup = _freq_question(ctx) if step == FREQ_STEP else _question(ctx, step)
    await show(event, with_notice(text, notice), markup)


@router.callback_query(SuCB.filter())
async def on_answer(
    call: CallbackQuery, callback_data: SuCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
) -> None:
    """An answer is saved at once and the next step is shown; ⏭ Saltar el asistente keeps the current values."""
    if not can_setup(ctx):
        await alert(call, ctx.t("common.no_permission"))
        return
    await state.clear()
    ws = ctx.ws_rec
    step, index = callback_data.s, callback_data.v
    if step == 0:
        ws.setup_done = True
        await open_screen("home", call, ctx, session)
        return
    if step not in OPTIONS or not 0 <= index < len(OPTIONS[step]):  # a forged button: the first step again
        await setup_screen(call, ctx, session, arg=1)
        return
    _save(ws, step, index)
    await setup_screen(call, ctx, session, arg=_next(ws, step))


@router.callback_query(SuFqCB.filter())
async def on_freq(
    call: CallbackQuery, callback_data: SuFqCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
    scheduler: Scheduler,
) -> None:
    """Step 4: each change is saved at once and the same step is shown again, with the hours it publishes at."""
    if not can_setup(ctx):
        await alert(call, ctx.t("common.no_permission"))
        return
    await state.clear()
    ws = ctx.ws_rec
    f = freq.normalize(ws.freq)
    action, v = callback_data.a, callback_data.v
    if action == "w":
        await _ask_times(call, ctx, state)
        return
    if action == "p" and 0 <= v < len(FREQ_PRESETS):
        new = _with_days(FREQ_PRESETS[v], f["days"])
    elif action == "d" and 0 <= v < len(DAY_PRESETS):
        new = _with_days(f, DAY_PRESETS[v])
    elif action == "h" and 0 <= v <= 23:
        times = _toggled(f, v)
        if not times:
            await alert(call, ctx.t("setup.freq.need_hour"))
            return
        if len(times) > freq.MAX_TIMES:
            await alert(call, ctx.t("freq.err.too_many"))
            return
        new = _times_dict(times, f["days"])
    else:  # a forged button: the step as it is
        await setup_screen(call, ctx, session, arg=FREQ_STEP)
        return
    _save_freq(ws, new)
    scheduler.wake()
    await setup_screen(call, ctx, session, arg=FREQ_STEP)


@router.message(SetupFSM.times, F.chat.type == "private", ~F.text.startswith("/"))
async def on_times_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext,
                         scheduler: Scheduler) -> None:
    """Typed times (``9:30, 14, 21:15``): they replace the hours; the days stay."""
    if not can_setup(ctx):  # rights checked again: the state may be old
        await state.clear()
        await alert(message, ctx.t("common.no_permission"))
        return
    try:
        times = freq.parse_times(message.text or "")
    except ValueError as exc:
        await _ask_times(message, ctx, state, ctx.t(str(exc)))
        return
    await state.clear()
    ws = ctx.ws_rec
    _save_freq(ws, {"mode": "times", "times": times, "days": freq.normalize(ws.freq)["days"]})
    scheduler.wake()
    notice = ctx.t("setup.freq.saved", freq=freq.describe(ws.freq, ctx.lang))
    await setup_screen(message, ctx, session, arg=FREQ_STEP, notice=notice)
