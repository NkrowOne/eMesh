"""⏰ Frecuencias: every frequency of the network at once (``freqs``), the frequency editor (``freq_edit``: the
global one, a group of chats' own one or a post's own schedule) and the 🛡 anti-spam limits (``antispam``).

A frequency is a small dict (see ``services/freq.py``). Every change stores a NEW normalized dict, refreshes the
stored next slot (``Bot.rot_next_at``, ``ChatGroup.rot_next_at``, ``Post.next_send_at``) and wakes the scheduler.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.db.base import utcnow
from app.db.models import DEFAULT_FREQ, ChatGroup, Post, PostStatus, RotationOrder, SchedMode
from app.db.models import Bot as BotRecord
from app.services import audience
from app.services import freq as freq_svc
from app.services.scheduler import Scheduler
from app.ui import fmt
from app.ui.callbacks import MenuCB
from app.ui.common import (
    alert,
    back_row,
    btn,
    choice_label,
    grid,
    kb,
    nav_row,
    paginate,
    prompt,
    show,
    toast,
    toggle_label,
)
from app.ui.screens import has_screen, open_screen, screen

router = Router(name="freqs")

Event = Message | CallbackQuery


class FqCB(CallbackData, prefix="fq"):
    """``t``: what the editor changes (0 = global, +N = group of chats N, -N = post N; the page for ``rot``),
    ``v``: the value, ``b``: 1 = the editor was opened from the ⏰ Frecuencias dashboard (its back goes there)."""

    a: str
    t: int = 0
    v: int = 0
    b: int = 0


class FreqFSM(StatesGroup):
    every = State()
    window = State()
    times = State()
    max_day = State()
    gap = State()


FREQS_PAGE = 10
# ``freq_edit`` of a group of chats opened from the dashboard: the same editor, but its back returns to ``freqs``.
DASH_EDIT = "freq_edit_dash"
WINDOW_CHOICES = ("", "08:00-22:00", "08:00-23:00", "09:00-22:00")  # quick buttons of the "active hours" input
DAY_PRESETS = (freq_svc.ALL_DAYS, freq_svc.WEEKDAYS, freq_svc.WEEKEND)
DAY_PRESET_KEYS = ("fq.b.days_all", "fq.b.days_weekdays", "fq.b.days_weekend")
ROTATIONS = (RotationOrder.SEQUENTIAL, RotationOrder.RANDOM)
MAX_CHOICES = (0, 2, 4, 6, 8, 12)  # 🛡 posts per chat and day (0 = no limit)
GAP_CHOICES = (0, 15, 30, 60, 120)  # 🛡 minutes between two posts in a chat (0 = none)
MAX_PER_DAY = 100
_NUMBER_RE = re.compile(r"[0-9]{1,6}")  # not str.isdigit(): it takes "²" or "①", which int() refuses
_NO_VALUE = {"0", "-", "no", "none", "ninguna", "ninguno", "sin", "sin límite", "sin limite"}


# ---------------------------------------------------------------------------------------------
# Shared helpers (also used by groups.py)
# ---------------------------------------------------------------------------------------------
def with_notice(text: str, notice: str | None) -> str:
    return f"{notice}\n\n{text}" if notice else text


async def guard(event: Event, ctx: Ctx) -> bool:
    """Admins of the network only (callback data can be forged); the hub main bot runs no network."""
    if ctx.is_admin and not ctx.is_hub:
        return True
    if ctx.is_admin:  # an old button of the hub main bot
        await expired(event, ctx)
    else:
        await alert(event, ctx.t("common.no_permission"))
    return False


async def expired(event: Event, ctx: Ctx) -> None:
    await toast(event, ctx.t("core.expired_button"))


def describe(ctx: Ctx, f: dict[str, Any] | None) -> str:
    return freq_svc.describe(f, ctx.lang)


def chats_text(ctx: Ctx, n: int) -> str:
    return ctx.t("fq.chats_1") if n == 1 else ctx.t("fq.chats", n=fmt.num(n))


def when_text(value: datetime | None, tz: str, now: datetime) -> str:
    """``11:00 AM`` (today) or ``07/11 08:00 AM`` (another day)."""
    if value is None:
        return "—"
    local = fmt.to_local(value, tz)
    time = local.strftime("%I:%M %p")
    return time if local.date() == fmt.to_local(now, tz).date() else f"{local:%d/%m} {time}"


def slots_text(slots: list[datetime], tz: str) -> str:
    """``07/11 11:00 AM, 02:00 PM, 05:00 PM``: the date only when the day changes."""
    out: list[str] = []
    last_day = None
    for slot in slots:
        local = fmt.to_local(slot, tz)
        time = local.strftime("%I:%M %p")
        out.append(time if local.date() == last_day else f"{local:%d/%m} {time}")
        last_day = local.date()
    return ", ".join(out) or "—"


# ---------------------------------------------------------------------------------------------
# What a frequency editor changes
# ---------------------------------------------------------------------------------------------
@dataclass
class Target:
    """The global frequency (``arg`` 0), a group of chats' own one (+id) or a post's own one (-id)."""

    arg: int
    ws: BotRecord
    group: ChatGroup | None = None
    post: Post | None = None

    @property
    def stored(self) -> dict[str, Any] | None:
        if self.group is not None:
            return self.group.freq
        if self.post is not None:
            return self.post.freq
        return self.ws.freq

    @property
    def uses_global(self) -> bool:
        """A group of chats without its own frequency: its chats follow the global one."""
        return self.group is not None and not self.group.freq

    def current(self) -> dict[str, Any]:
        """The frequency shown and edited (a post without one yet starts from a copy of the global one)."""
        return freq_svc.normalize(self.stored or self.ws.freq)

    def save(self, new: dict[str, Any] | None, tz: str, now: datetime) -> None:
        """Stores a NEW normalized dict (None: the group follows the global one) and refreshes the next slot."""
        value = freq_svc.normalize(new) if new is not None else None
        if self.group is not None:
            self.group.freq = value
            freq_svc.refresh_group(self.group, tz, now)
        elif self.post is not None:
            self.post.freq = value
            freq_svc.refresh_post(self.post, tz, now)
        else:
            self.ws.freq = freq_svc.normalize(new)
            freq_svc.refresh_bot(self.ws, now)


async def load_target(event: Event, ctx: Ctx, session: AsyncSession, arg: int) -> Target | None:
    """The target of ``arg`` in the workspace, or None after telling the user it doesn't exist."""
    if arg == 0:
        return Target(0, ctx.ws_rec)
    if arg > 0:
        group = await session.get(ChatGroup, arg)
        if group is not None and group.bot_id == ctx.ws_id:
            return Target(arg, ctx.ws_rec, group=group)
    else:
        post = await session.get(Post, -arg)
        if post is not None and post.bot_id == ctx.ws_id:
            return Target(arg, ctx.ws_rec, post=post)
    await alert(event, ctx.t("common.not_found"))
    await open_screen("posts" if arg < 0 and has_screen("posts") else "freqs", event, ctx, session)
    return None


def back_of(target: Target, dash: bool) -> tuple[str, int]:
    if target.post is not None:
        return "post_sched", target.post.id
    if target.group is not None and not dash:
        return "group", target.group.id
    return "freqs", 0


def upcoming(target: Target, f: dict[str, Any], tz: str, now: datetime) -> list[datetime]:
    """The next 3 slots (a post's campaign dates limit them, like ``freq.refresh_post``)."""
    post = target.post
    after = now
    if post is not None and post.starts_on:
        after = max(after, freq_svc.day_start(post.starts_on, tz) - timedelta(seconds=1))
    slots = freq_svc.upcoming(f, tz, after, 3)
    if post is not None and post.ends_on:
        end = freq_svc.day_end(post.ends_on, tz)
        slots = [s for s in slots if s < end]
    return slots


def window_text(ctx: Ctx, window: str) -> str:
    return window or ctx.t("fq.e.all_day")


def toggle_day(days: str, day: int) -> str:
    return "".join(sorted(set(days) ^ {str(day)}))


# ---------------------------------------------------------------------------------------------
# ⏰ Frecuencias (dashboard)
# ---------------------------------------------------------------------------------------------
def stats_line(ctx: Ctx, f: dict[str, Any] | None, chats: int, now: datetime) -> str:
    nxt = freq_svc.next_slot(f, ctx.bot_tz, now)
    return ctx.t("fq.stats", chats=chats_text(ctx, chats), per_day=freq_svc.per_day(f),
                 next=when_text(nxt, ctx.tz, now))


def antispam_text(ctx: Ctx, ws: BotRecord) -> str:
    return " · ".join([
        ctx.t("fq.as.s.max", n=ws.max_per_day) if ws.max_per_day else ctx.t("fq.as.s.no_max"),
        ctx.t("fq.as.s.gap", gap=freq_svc.every_text(ws.min_gap, ctx.lang)) if ws.min_gap else ctx.t("fq.as.s.no_gap"),
        ctx.t("fq.as.s.one", value=fmt.onoff(ws.one_at_a_time)),
    ])


async def own_posts_count(session: AsyncSession, bot_id: int) -> int:
    q = select(func.count()).select_from(Post).where(
        Post.bot_id == bot_id, Post.mode == SchedMode.OWN, Post.status == PostStatus.ACTIVE)
    return int((await session.execute(q)).scalar() or 0)


async def render_freqs(event: Event, ctx: Ctx, session: AsyncSession, page: int = 0, *,
                       notice: str | None = None) -> None:
    ws, now = ctx.ws_rec, utcnow()
    groups = await audience.bot_groups(session, ws.id)
    counts = await audience.source_counts(session, ws.id, now)
    items, page, pages = paginate(groups, page, FREQS_PAGE)
    order = ws.rotation if ws.rotation in ROTATIONS else RotationOrder.SEQUENTIAL

    head = [ctx.t("fq.title")]
    if ws.paused:
        head.append(ctx.t("fq.paused"))
    sources = [ctx.t("fq.global", freq=describe(ctx, ws.freq)), stats_line(ctx, ws.freq, counts.get(None, 0), now)]
    for g in items:
        if g.freq:
            sources += [ctx.t("fq.group", name=fmt.esc(g.name), freq=describe(ctx, g.freq)),
                        stats_line(ctx, g.freq, counts.get(g.id, 0), now)]
        else:
            sources.append(ctx.t("fq.group_global", name=fmt.esc(g.name)))
    sources.append(ctx.t("fq.source_tip") if groups else ctx.t("fq.no_groups"))
    if pages > 1:
        sources.append(ctx.t("common.page", page=page + 1, pages=pages))
    posts = [ctx.t("fq.own_posts", n=await own_posts_count(session, ws.id)), ctx.t("fq.own_posts_hint")]
    settings = [ctx.t("fq.rotation", value=ctx.t(f"fq.rot.{order}")), ctx.t(f"fq.rot_hint.{order}"),
                ctx.t("fq.antispam", value=antispam_text(ctx, ws))]
    text = "\n\n".join("\n".join(part) for part in (head, sources, posts, settings))

    rows: list[list[InlineKeyboardButton]] = [
        [btn(fmt.truncate(ctx.t("fq.b.global", freq=describe(ctx, ws.freq)), 64), MenuCB(screen="freq_edit"))]
    ]
    for g in items:
        label = ctx.t("fq.b.group", name=g.name, freq=describe(ctx, g.freq) if g.freq else ctx.t("fq.global_short"))
        rows.append([btn(fmt.truncate(label, 64), MenuCB(screen=DASH_EDIT, arg=g.id))])
    rows.append(nav_row(page, pages, lambda p: MenuCB(screen="freqs", arg=p), ctx.lang))
    rows.append([btn(choice_label(ctx.t(f"fq.b.{o}"), o == order), FqCB(a="rot", t=page, v=i))
                 for i, o in enumerate(ROTATIONS)])
    rows.append([btn(ctx.t("fq.b.antispam"), MenuCB(screen="antispam"))])
    rows.append(back_row(ctx.lang, "home"))
    await show(event, with_notice(text, notice), kb(*rows))


@screen("freqs")
async def freqs_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    if await guard(event, ctx):
        await render_freqs(event, ctx, session, arg, notice=kw.get("notice"))


@router.callback_query(FqCB.filter(F.a == "rot"))
async def on_rotation(call: CallbackQuery, callback_data: FqCB, ctx: Ctx, session: AsyncSession,
                      state: FSMContext) -> None:
    if not await guard(call, ctx):
        return
    await state.clear()
    if not 0 <= callback_data.v < len(ROTATIONS):
        await expired(call, ctx)
        return
    order = ROTATIONS[callback_data.v]
    ctx.ws_rec.rotation = order
    await toast(call, choice_label(ctx.t(f"fq.b.{order}"), True))
    await render_freqs(call, ctx, session, callback_data.t)


# ---------------------------------------------------------------------------------------------
# freq_edit
# ---------------------------------------------------------------------------------------------
def title_of(ctx: Ctx, target: Target) -> str:
    if target.group is not None:
        return ctx.t("fq.e.group", name=fmt.esc(target.group.name))
    if target.post is not None:
        return ctx.t("fq.e.post", name=fmt.esc(target.post.name or f"#{target.post.id}"))
    return ctx.t("fq.e.global")


def days_rows(ctx: Ctx, days: str, cb: Callable[[str, int], FqCB]) -> list[list[InlineKeyboardButton]]:
    toggles = [btn(("✅ " if str(d) in days else "") + ctx.t(f"weekday.short.{d}"), cb("day", d)) for d in range(7)]
    presets = [btn(("✅ " if days == preset else "") + ctx.t(key), cb("dp", i))
               for i, (preset, key) in enumerate(zip(DAY_PRESETS, DAY_PRESET_KEYS, strict=True))]
    return [toggles[:4], toggles[4:], presets]


async def render_edit(event: Event, ctx: Ctx, session: AsyncSession, target: Target, *, dash: bool = False,
                      notice: str | None = None) -> None:
    now = utcnow()
    f = target.current()
    interval = f["mode"] == "interval"

    def cb(a: str, v: int = 0) -> FqCB:
        return FqCB(a=a, t=target.arg, v=v, b=int(dash))

    lines = [title_of(ctx, target)]
    rows: list[list[InlineKeyboardButton]] = []
    if target.group is not None:
        label = choice_label(ctx.t("fq.b.use_global", freq=describe(ctx, target.ws.freq)), target.uses_global)
        rows.append([btn(fmt.truncate(label, 64), cb("glob"))])
    if target.uses_global:
        lines += [ctx.t("fq.e.uses_global", freq=describe(ctx, f)), ctx.t("fq.e.uses_global_hint")]
    else:
        if target.post is None:
            counts = await audience.source_counts(session, target.ws.id, now)
            followers = counts.get(target.group.id if target.group is not None else None, 0)
            lines += [ctx.t("fq.e.followers", chats=chats_text(ctx, followers)),
                      ctx.t("fq.source_hint" if target.group is not None else "fq.e.global_who")]
        else:
            lines.append(ctx.t("fq.e.post_hint"))
        if interval:
            lines += [ctx.t("fq.e.every", every=freq_svc.every_text(f["every"], ctx.lang)),
                      ctx.t("fq.e.window", window=window_text(ctx, f["window"]))]
        else:
            lines.append(ctx.t("fq.e.times", times=freq_svc.times_text(f["times"], ctx.lang)))
        lines.append(ctx.t("fq.e.days", days=freq_svc.days_text(f["days"], ctx.lang)))

        rows.append([btn(choice_label(ctx.t("fq.b.interval"), interval), cb("mode", 0)),
                     btn(choice_label(ctx.t("fq.b.times"), not interval), cb("mode", 1))])
        if interval:
            every = [btn(choice_label(freq_svc.every_text(m, ctx.lang), f["every"] == m), cb("ev", m))
                     for m in freq_svc.EVERY_CHOICES]
            rows += grid(every, 3)
            custom = f["every"] not in freq_svc.EVERY_CHOICES
            other = (choice_label(ctx.t("fq.b.every_custom", every=freq_svc.every_text(f["every"], ctx.lang)), True)
                     if custom else ctx.t("fq.b.every_other"))
            rows.append([btn(other, cb("evx"))])
            rows.append([btn(ctx.t("fq.b.window", window=window_text(ctx, f["window"])), cb("win"))])
        else:
            rows.append([btn(ctx.t("fq.b.write_times"), cb("tms"))])
        rows += days_rows(ctx, f["days"], cb)
    lines += [ctx.t("fq.e.next", slots=slots_text(upcoming(target, f, ctx.bot_tz, now), ctx.tz)),
              ctx.t("fq.e.per_day", n=freq_svc.per_day(f)),
              ctx.t("fq.e.tz", tz=fmt.esc(ctx.bot_tz))]
    if target.post is not None and target.post.mode != SchedMode.OWN:
        lines += ["", ctx.t("fq.e.post_unused")]
    rows.append(back_row(ctx.lang, *back_of(target, dash)))
    await show(event, with_notice("\n".join(lines), notice), kb(*rows))


async def open_edit(event: Event, ctx: Ctx, session: AsyncSession, arg: int, *, dash: bool,
                    notice: str | None = None) -> None:
    if not await guard(event, ctx):
        return
    target = await load_target(event, ctx, session, arg)
    if target is not None:
        await render_edit(event, ctx, session, target, dash=dash, notice=notice)


@screen("freq_edit")
async def freq_edit_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    await open_edit(event, ctx, session, arg, dash=False, notice=kw.get("notice"))


@screen(DASH_EDIT)
async def freq_edit_dash_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    await open_edit(event, ctx, session, arg, dash=True, notice=kw.get("notice"))


async def edit_target(call: CallbackQuery, data: FqCB, ctx: Ctx, session: AsyncSession,
                      state: FSMContext) -> Target | None:
    if not await guard(call, ctx):
        return None
    await state.clear()
    return await load_target(call, ctx, session, data.t)


async def apply(event: Event, ctx: Ctx, session: AsyncSession, scheduler: Scheduler, target: Target,
                new: dict[str, Any] | None, *, dash: bool, notice: str | None = None) -> None:
    """Stores the change, wakes the scheduler and shows the editor again with what it is now (toast on buttons,
    notice on inputs)."""
    target.save(new, ctx.bot_tz, utcnow())
    scheduler.wake()
    notice = notice or ctx.t("fq.saved", freq=describe(ctx, target.current()))
    if isinstance(event, CallbackQuery) and notice:
        await toast(event, notice)
        notice = None
    await render_edit(event, ctx, session, target, dash=dash, notice=notice)


def interval_of(f: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """An interval frequency from ``f`` (a "times" one has no interval yet: it starts from the default one)."""
    base = {"mode": "interval", "every": f.get("every", freq.DEFAULT_EVERY), "window": f.get("window", ""),
            "days": f["days"]}
    return {**base, **changes}


@router.callback_query(FqCB.filter(F.a == "glob"))
async def on_use_global(call: CallbackQuery, callback_data: FqCB, ctx: Ctx, session: AsyncSession,
                        state: FSMContext, scheduler: Scheduler) -> None:
    target = await edit_target(call, callback_data, ctx, session, state)
    if target is None:
        return
    if target.group is None:
        await expired(call, ctx)
        return
    if target.uses_global:  # its own frequency starts as a copy of the global one
        new, notice = freq_svc.normalize(target.ws.freq), ctx.t("fq.own_on")
    else:
        new, notice = None, ctx.t("fq.own_off")
    await apply(call, ctx, session, scheduler, target, new, dash=bool(callback_data.b), notice=notice)


@router.callback_query(FqCB.filter(F.a == "mode"))
async def on_mode(call: CallbackQuery, callback_data: FqCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
                  scheduler: Scheduler) -> None:
    target = await edit_target(call, callback_data, ctx, session, state)
    if target is None:
        return
    dash = bool(callback_data.b)
    f = target.current()
    if callback_data.v == 1:  # fixed times: they are asked first, the mode changes with them
        if f["mode"] == "times" and not target.uses_global:
            await render_edit(call, ctx, session, target, dash=dash)
        else:
            await ask_times(call, ctx, state, target, dash)
        return
    if callback_data.v != 0:
        await expired(call, ctx)
        return
    if f["mode"] == "interval" and not target.uses_global:
        await render_edit(call, ctx, session, target, dash=dash)
        return
    await apply(call, ctx, session, scheduler, target, interval_of(f), dash=dash)


@router.callback_query(FqCB.filter(F.a == "ev"))
async def on_every(call: CallbackQuery, callback_data: FqCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
                   scheduler: Scheduler) -> None:
    target = await edit_target(call, callback_data, ctx, session, state)
    if target is None:
        return
    if callback_data.v not in freq_svc.EVERY_CHOICES:
        await expired(call, ctx)
        return
    new = interval_of(target.current(), every=callback_data.v)
    await apply(call, ctx, session, scheduler, target, new, dash=bool(callback_data.b))


@router.callback_query(FqCB.filter(F.a == "wq"))
async def on_window_choice(call: CallbackQuery, callback_data: FqCB, ctx: Ctx, session: AsyncSession,
                           state: FSMContext, scheduler: Scheduler) -> None:
    target = await edit_target(call, callback_data, ctx, session, state)
    if target is None:
        return
    if not 0 <= callback_data.v < len(WINDOW_CHOICES):
        await expired(call, ctx)
        return
    new = interval_of(target.current(), window=WINDOW_CHOICES[callback_data.v])
    await apply(call, ctx, session, scheduler, target, new, dash=bool(callback_data.b))


@router.callback_query(FqCB.filter(F.a.in_({"day", "dp"})))
async def on_days(call: CallbackQuery, callback_data: FqCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
                  scheduler: Scheduler) -> None:
    target = await edit_target(call, callback_data, ctx, session, state)
    if target is None:
        return
    f = target.current()
    v = callback_data.v
    if callback_data.a == "day" and 0 <= v <= 6:
        days = toggle_day(f["days"], v)
    elif callback_data.a == "dp" and 0 <= v < len(DAY_PRESETS):
        days = DAY_PRESETS[v]
    else:
        await expired(call, ctx)
        return
    if not days:
        await alert(call, ctx.t("fq.need_day"))
        return
    await apply(call, ctx, session, scheduler, target, {**f, "days": days}, dash=bool(callback_data.b))


# --- text inputs: other interval, active hours, fixed times ------------------------------------
async def ask(event: Event, ctx: Ctx, state: FSMContext, step: State, target: Target, dash: bool, text: str, *,
              error: str | None = None, extra_rows: list[list[InlineKeyboardButton]] | None = None) -> None:
    await state.set_state(step)
    await state.set_data({"t": target.arg, "b": int(dash)})
    cancel = DASH_EDIT if dash and target.group is not None else "freq_edit"
    await prompt(event, ctx, with_notice(text, error), cancel_screen=cancel, cancel_arg=target.arg,
                 extra_rows=extra_rows or ())


async def ask_every(event: Event, ctx: Ctx, state: FSMContext, target: Target, dash: bool,
                    error: str | None = None) -> None:
    f = target.current()
    current = freq_svc.every_text(f["every"], ctx.lang) if f["mode"] == "interval" else "—"
    await ask(event, ctx, state, FreqFSM.every, target, dash, ctx.t("fq.p.every", current=current), error=error)


async def ask_window(event: Event, ctx: Ctx, state: FSMContext, target: Target, dash: bool,
                     error: str | None = None) -> None:
    f = target.current()
    current = window_text(ctx, f["window"]) if f["mode"] == "interval" else "—"
    quick = [btn(choice_label(w or ctx.t("fq.b.all_day"), f.get("window") == w),
                 FqCB(a="wq", t=target.arg, v=i, b=int(dash))) for i, w in enumerate(WINDOW_CHOICES)]
    await ask(event, ctx, state, FreqFSM.window, target, dash, ctx.t("fq.p.window", current=current), error=error,
              extra_rows=[quick])


async def ask_times(event: Event, ctx: Ctx, state: FSMContext, target: Target, dash: bool,
                    error: str | None = None) -> None:
    f = target.current()
    current = freq_svc.times_text(f["times"], ctx.lang) if f["mode"] == "times" else "—"
    await ask(event, ctx, state, FreqFSM.times, target, dash, ctx.t("fq.p.times", current=current), error=error)


@router.callback_query(FqCB.filter(F.a.in_({"evx", "win", "tms"})))
async def on_ask(call: CallbackQuery, callback_data: FqCB, ctx: Ctx, session: AsyncSession,
                 state: FSMContext) -> None:
    target = await edit_target(call, callback_data, ctx, session, state)
    if target is None:
        return
    asker = {"evx": ask_every, "win": ask_window, "tms": ask_times}[callback_data.a]
    await asker(call, ctx, state, target, bool(callback_data.b))


async def input_target(message: Message, ctx: Ctx, session: AsyncSession,
                       state: FSMContext) -> tuple[Target | None, bool]:
    """The target of a text input (rights and ownership checked again: the state may be old)."""
    data = await state.get_data()
    if not await guard(message, ctx):
        await state.clear()
        return None, False
    target = await load_target(message, ctx, session, int(data.get("t") or 0))
    if target is None:
        await state.clear()
    return target, bool(data.get("b"))


@router.message(FreqFSM.every, F.chat.type == "private", ~F.text.startswith("/"))
async def on_every_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext,
                         scheduler: Scheduler) -> None:
    target, dash = await input_target(message, ctx, session, state)
    if target is None:
        return
    try:
        minutes = freq_svc.parse_every(message.text or "")
    except ValueError as exc:
        await ask_every(message, ctx, state, target, dash, ctx.t(str(exc)))
        return
    await state.clear()
    await apply(message, ctx, session, scheduler, target, interval_of(target.current(), every=minutes), dash=dash)


@router.message(FreqFSM.window, F.chat.type == "private", ~F.text.startswith("/"))
async def on_window_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext,
                          scheduler: Scheduler) -> None:
    target, dash = await input_target(message, ctx, session, state)
    if target is None:
        return
    try:
        window = freq_svc.parse_window(message.text or "")
    except ValueError as exc:
        await ask_window(message, ctx, state, target, dash, ctx.t(str(exc)))
        return
    await state.clear()
    await apply(message, ctx, session, scheduler, target, interval_of(target.current(), window=window), dash=dash)


@router.message(FreqFSM.times, F.chat.type == "private", ~F.text.startswith("/"))
async def on_times_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext,
                         scheduler: Scheduler) -> None:
    target, dash = await input_target(message, ctx, session, state)
    if target is None:
        return
    try:
        times = freq_svc.parse_times(message.text or "")
    except ValueError as exc:
        await ask_times(message, ctx, state, target, dash, ctx.t(str(exc)))
        return
    await state.clear()
    new = {"mode": "times", "times": times, "days": target.current()["days"]}
    await apply(message, ctx, session, scheduler, target, new, dash=dash)


# ---------------------------------------------------------------------------------------------
# 🛡 Anti-spam
# ---------------------------------------------------------------------------------------------
def max_text(ctx: Ctx, n: int) -> str:
    return str(n) if n else ctx.t("fq.as.no_limit")


def gap_text(ctx: Ctx, minutes: int) -> str:
    return freq_svc.every_text(minutes, ctx.lang) if minutes else ctx.t("fq.as.no_gap")


async def render_antispam(event: Event, ctx: Ctx, *, notice: str | None = None) -> None:
    ws = ctx.ws_rec
    lines = [
        ctx.t("fq.as.title"), "",
        ctx.t("fq.as.l.max", value=max_text(ctx, ws.max_per_day)), ctx.t("fq.as.h.max"),
        ctx.t("fq.as.l.gap", value=gap_text(ctx, ws.min_gap)), ctx.t("fq.as.h.gap"),
        ctx.t("fq.as.l.one", value=fmt.onoff(ws.one_at_a_time)), ctx.t("fq.as.h.one"),
    ]
    maxes = [btn(choice_label(ctx.t("fq.as.b.per_day", n=n) if n else ctx.t("fq.as.b.no_limit"), ws.max_per_day == n),
                 FqCB(a="mx", v=n)) for n in MAX_CHOICES]
    max_custom = ws.max_per_day not in MAX_CHOICES
    max_other = (choice_label(ctx.t("fq.as.b.max_custom", n=ws.max_per_day), True) if max_custom
                 else ctx.t("fq.as.b.max_other"))
    gaps = [btn(choice_label(freq_svc.every_text(m, ctx.lang) if m else ctx.t("fq.as.b.no_gap"), ws.min_gap == m),
                FqCB(a="gp", v=m)) for m in GAP_CHOICES]
    gap_custom = ws.min_gap not in GAP_CHOICES
    gap_other = (choice_label(ctx.t("fq.as.b.gap_custom", gap=freq_svc.every_text(ws.min_gap, ctx.lang)), True)
                 if gap_custom else ctx.t("fq.as.b.gap_other"))
    markup = kb(
        *grid(maxes, 3),
        [btn(max_other, FqCB(a="mxx"))],
        *grid([*gaps, btn(gap_other, FqCB(a="gpx"))], 3),
        [btn(toggle_label(ctx.t("fq.as.b.one"), ws.one_at_a_time), FqCB(a="one"))],
        back_row(ctx.lang, "freqs"),
    )
    await show(event, with_notice("\n".join(lines), notice), markup)


@screen("antispam")
async def antispam_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    if await guard(event, ctx):
        await render_antispam(event, ctx, notice=kw.get("notice"))


@router.callback_query(FqCB.filter(F.a.in_({"mx", "gp", "one"})))
async def on_antispam(call: CallbackQuery, callback_data: FqCB, ctx: Ctx, state: FSMContext) -> None:
    if not await guard(call, ctx):
        return
    await state.clear()
    ws, v = ctx.ws_rec, callback_data.v
    if callback_data.a == "mx" and v in MAX_CHOICES:
        ws.max_per_day = v
        notice = ctx.t("common.saved")
    elif callback_data.a == "gp" and v in GAP_CHOICES:
        ws.min_gap = v
        notice = ctx.t("common.saved")
    elif callback_data.a == "one":
        ws.one_at_a_time = not ws.one_at_a_time
        notice = toggle_label(ctx.t("fq.as.b.one"), ws.one_at_a_time)
    else:
        await expired(call, ctx)
        return
    await toast(call, notice)
    await render_antispam(call, ctx)


async def ask_max(event: Event, ctx: Ctx, state: FSMContext, error: str | None = None) -> None:
    await state.set_state(FreqFSM.max_day)
    text = ctx.t("fq.as.p.max", max=MAX_PER_DAY, current=max_text(ctx, ctx.ws_rec.max_per_day))
    await prompt(event, ctx, with_notice(text, error), cancel_screen="antispam")


async def ask_gap(event: Event, ctx: Ctx, state: FSMContext, error: str | None = None) -> None:
    await state.set_state(FreqFSM.gap)
    text = ctx.t("fq.as.p.gap", current=gap_text(ctx, ctx.ws_rec.min_gap))
    await prompt(event, ctx, with_notice(text, error), cancel_screen="antispam")


@router.callback_query(FqCB.filter(F.a.in_({"mxx", "gpx"})))
async def on_antispam_ask(call: CallbackQuery, callback_data: FqCB, ctx: Ctx, state: FSMContext) -> None:
    if not await guard(call, ctx):
        return
    await (ask_max if callback_data.a == "mxx" else ask_gap)(call, ctx, state)


@router.message(FreqFSM.max_day, F.chat.type == "private", ~F.text.startswith("/"))
async def on_max_input(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if not await guard(message, ctx):
        await state.clear()
        return
    raw = (message.text or "").strip().lower()
    n = 0 if raw in _NO_VALUE else (int(raw) if _NUMBER_RE.fullmatch(raw) else -1)
    if not 0 <= n <= MAX_PER_DAY:
        await ask_max(message, ctx, state, ctx.t("fq.as.err.max", max=MAX_PER_DAY))
        return
    await state.clear()
    ctx.ws_rec.max_per_day = n
    await render_antispam(message, ctx, notice=ctx.t("common.saved"))


@router.message(FreqFSM.gap, F.chat.type == "private", ~F.text.startswith("/"))
async def on_gap_input(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if not await guard(message, ctx):
        await state.clear()
        return
    raw = (message.text or "").strip().lower()
    try:
        minutes = 0 if raw in _NO_VALUE else freq_svc.parse_every(raw)
    except ValueError as exc:
        await ask_gap(message, ctx, state, ctx.t(str(exc)))
        return
    await state.clear()
    ctx.ws_rec.min_gap = minutes
    await render_antispam(message, ctx, notice=ctx.t("common.saved"))
