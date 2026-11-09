"""🧭 Setup wizard of a new bot: one question per screen, the current value pre-selected, each answer saved at once.

The owner of a new clone goes through it on the first /start, right after choosing the timezone (``needs_setup``),
and can run it again from ⚙️ Ajustes. ``setup`` arg = step: 1 external chats, 2 the partners' pauses (only when
external chats are accepted), 3 the global frequency, 4 how long posts stay published, 5 the summary (done).
"""
from __future__ import annotations

from typing import Any

from aiogram import Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.routers.settings import PAUSE_MAX_CHOICES, duration_text, externals_line, pause_max_text, with_notice
from app.data.timezones import utc_offset_label
from app.db.base import utcnow
from app.db.models import DEFAULT_DELETE_AFTER, Post
from app.db.models import Bot as BotRecord
from app.services import freq
from app.services.chatinfo import add_to_channel_url, add_to_group_url
from app.services.scheduler import Scheduler
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, choice_label, kb, show
from app.ui.fmt import esc, truncate
from app.ui.screens import open_screen, screen

router = Router(name="setup")

SUMMARY = 5  # the last step: «✅ Todo listo»
WINDOW = "08:00-22:00"
# Step 1: (join_open, join_approval); None leaves the approval as it is (it doesn't matter while closed).
JOIN_OPTIONS: tuple[tuple[bool, bool | None], ...] = ((True, True), (True, False), (False, None))
# Step 2: the longest pause of a partner in hours (0 = until they resume it); None: partners can't pause.
PAUSE_OPTIONS: tuple[int | None, ...] = (*PAUSE_MAX_CHOICES, None)
# Step 3: the global frequency: once a day at 12:00 (the default), or every 2, 4, 6 or 12 h from 08:00 to 22:00.
FREQ_OPTIONS: tuple[dict[str, Any], ...] = tuple(freq.normalize(f) for f in (
    {"mode": "times", "times": "12:00", "days": freq.ALL_DAYS},
    *({"mode": "interval", "every": hours * 60, "window": WINDOW, "days": freq.ALL_DAYS} for hours in (2, 4, 6, 12)),
))
# Step 4: how long new posts stay published, in minutes (0 = never deleted).
DELETE_OPTIONS = (60, 360, 720, 1440, 2880, 0)
OPTIONS: dict[int, tuple[Any, ...]] = {1: JOIN_OPTIONS, 2: PAUSE_OPTIONS, 3: FREQ_OPTIONS, 4: DELETE_OPTIONS}
LAYOUT = {1: (1, 1, 1), 2: (1, 1, 1, 1, 1), 3: (1, 2, 2), 4: (3, 2, 1)}  # buttons per row of each step
KEEP_MAX = 45  # characters of a current value shown on its «Mantener» button


class SuCB(CallbackData, prefix="su"):
    """Answer ``v`` (the index of the chosen option) to step ``s``; ``s=0`` skips the wizard."""

    s: int
    v: int = 0


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
    if step == 1:
        return (0 if ws.join_approval else 1) if ws.join_open else 2
    value: Any
    if step == 2:
        value = ws.pause_max_hours if ws.partners_can_pause else None
    elif step == 3:
        value = freq.normalize(ws.freq)
    else:
        value = delete_after_of(ws)
    return OPTIONS[step].index(value) if value in OPTIONS[step] else None


def _next(ws: BotRecord, step: int) -> int:
    """The step after ``step``: the partners' one only when external chats are accepted."""
    return 2 if step == 1 and ws.join_open else max(step + 1, 3)


def _previous(ws: BotRecord, step: int) -> int:
    return 1 if step == 3 and not ws.join_open else step - 1


def _save(ws: BotRecord, step: int, index: int) -> None:
    if step == 1:
        ws.join_open, approval = JOIN_OPTIONS[index]
        if approval is not None:
            ws.join_approval = approval
    elif step == 2:
        hours = PAUSE_OPTIONS[index]
        ws.partners_can_pause = hours is not None
        if hours is not None:
            ws.pause_max_hours = hours
    elif step == 3:
        ws.freq = dict(FREQ_OPTIONS[index])  # a new dict: JSON column
        freq.refresh_bot(ws, utcnow())
    else:
        stored = ws.post_defaults if isinstance(ws.post_defaults, dict) else {}
        ws.post_defaults = {**stored, "delete_after": DELETE_OPTIONS[index]}  # a new dict: JSON column


# ---------------------------------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------------------------------
def _labels(ctx: Ctx, step: int) -> list[str]:
    if step == 1:
        labels = [ctx.t("setup.join.approval"), ctx.t("setup.join.auto"), ctx.t("setup.join.closed")]
    elif step == 2:
        labels = [ctx.t("setup.pause.upto", t=pause_max_text(ctx, hours)) if hours else pause_max_text(ctx, 0)
                  for hours in PAUSE_MAX_CHOICES]
        labels.append(ctx.t("setup.pause.no"))
    elif step == 3:
        labels = [ctx.t("setup.freq.daily")]
        labels += [ctx.t("setup.freq.every", t=freq.every_text(f["every"], ctx.lang)) for f in FREQ_OPTIONS[1:]]
    else:
        labels = [duration_text(ctx, minutes) if minutes else ctx.t("setup.delete.never") for minutes in DELETE_OPTIONS]
    return labels


def _value_text(ctx: Ctx, step: int) -> str:
    """The current value of a step when it isn't one of its options (set in ⏰ Frecuencias, ⚙️ Opciones…)."""
    ws = ctx.ws_rec
    if step == 2:
        return ctx.t("setup.sum.pause.upto", t=pause_max_text(ctx, ws.pause_max_hours))
    if step == 3:
        return freq.describe(ws.freq, ctx.lang)
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
    if step == 1:
        rows.append([btn(ctx.t("setup.btn.skip"), SuCB(s=0))])
        return f"{ctx.t('setup.intro')}\n\n{ctx.t('setup.q.1')}", kb(*rows)
    rows.append(back_row(ctx.lang, "setup", _previous(ws, step)))
    return ctx.t(f"setup.q.{step}"), kb(*rows)


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
    lines += [
        ctx.t("home.freq", freq=freq.describe(ws.freq, ctx.lang)),
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
    """``arg``: the step, 1-5."""
    if not can_setup(ctx):
        await alert(event, ctx.t("common.no_permission"))
        return
    step = min(max(arg, 1), SUMMARY)
    if step == 2 and not ctx.ws_rec.join_open:  # the partners' step only when external chats are accepted
        step = 3
    text, markup = await _summary(ctx, session) if step == SUMMARY else _question(ctx, step)
    await show(event, with_notice(text, notice), markup)


@router.callback_query(SuCB.filter())
async def on_answer(
    call: CallbackQuery, callback_data: SuCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
    scheduler: Scheduler,
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
    if step == 3:
        scheduler.wake()
    await setup_screen(call, ctx, session, arg=_next(ws, step))
