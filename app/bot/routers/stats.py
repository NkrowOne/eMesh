"""📊 Statistics of the network (24 h / 7 days / 30 days) and its 📜 activity (the events, newest first)."""
from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.db.models import Event
from app.services import content, events
from app.services import stats as stats_svc
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, choice_label, kb, nav_row, show, visible_len
from app.ui.fmt import esc, num
from app.ui.screens import screen

router = Router(name="stats")

PERIOD_HOURS = (24, 24 * 7, 24 * 30)  # ``stats`` arg: 0 = 24 h, 1 = 7 days, 2 = 30 days
ACTIVITY_PER_PAGE = 10
ENTRY_MAX = 380  # visible characters of one activity entry: a page always fits in a message


@screen("stats")
async def stats_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, **_: object
) -> None:
    if not ctx.is_admin:
        await alert(event, ctx.t("common.no_permission"))
        return
    period = arg if 0 <= arg < len(PERIOD_HOURS) else 0
    s = await stats_svc.summary(session, ctx.ws_id, hours=PERIOD_HOURS[period])
    lines = [
        ctx.t("stats.title", period=ctx.t(f"stats.period.{period}")),
        "",
        ctx.t("stats.runs", n=num(s.runs)),
        ctx.t("stats.sent", n=num(s.sent)),
        ctx.t("stats.failed", n=num(s.failed)),
        ctx.t("stats.skipped", n=num(s.skipped)),
        ctx.t("stats.reach", n=num(s.reach)),
        ctx.t("stats.hint.reach"),
        "",
        ctx.t("stats.chats", n=num(s.chats), own=num(s.own), ext=num(s.external), members=num(s.members)),
    ]
    # Every approved chat that doesn't receive posts is counted once: paused (with its rights) or without rights.
    paused = max(0, s.chats - s.sendable - s.no_rights)
    states = [ctx.t(key, n=num(value)) for key, value in
              (("stats.paused", paused), ("stats.no_rights", s.no_rights), ("stats.pending", s.pending)) if value]
    if states:
        lines.append(" · ".join(states))
    if s.top_posts:
        lines += ["", ctx.t("stats.top")]
        lines += [ctx.t("stats.top.item", i=i, name=esc(name), n=num(sent))
                  for i, (name, sent) in enumerate(s.top_posts, start=1)]
    rows: list[list[InlineKeyboardButton]] = [
        [btn(choice_label(ctx.t(f"stats.btn.{i}"), i == period), MenuCB(screen="stats", arg=i))
         for i in range(len(PERIOD_HOURS))],
        [btn(ctx.t("stats.btn.activity"), MenuCB(screen="activity"))],
        back_row(ctx.lang, "home"),
    ]
    await show(event, "\n".join(lines), kb(*rows))


def _fit(entry: str) -> str:
    """An activity entry as is, or as plain text cut to ``ENTRY_MAX`` when names make it too long (Telegram counts
    UTF-16 units: an emoji counts twice)."""
    if visible_len(entry) <= ENTRY_MAX:
        return entry
    units = content.plain(entry).encode("utf-16-le")[: (ENTRY_MAX - 1) * 2]
    return esc(units.decode("utf-16-le", "ignore").rstrip()) + "…"


@screen("activity")
async def activity_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, **_: object
) -> None:
    """``arg``: 0-based page."""
    if not ctx.is_admin:
        await alert(event, ctx.t("common.no_permission"))
        return
    total = int((await session.execute(
        select(func.count()).select_from(Event).where(Event.bot_id == ctx.ws_id))).scalar() or 0)
    pages = max(1, -(-total // ACTIVITY_PER_PAGE))
    page = min(max(arg, 0), pages - 1)
    items = await events.recent(session, ctx.ws_id, limit=ACTIVITY_PER_PAGE, offset=page * ACTIVITY_PER_PAGE)
    lines = [ctx.t("stats.act.title")]
    if not items:
        lines += ["", ctx.t("stats.act.empty")]
    for ev in items:
        lines += ["", _fit(await events.describe(session, ev, ctx.lang, ctx.tz))]
    if pages > 1:
        lines += ["", ctx.t("common.page", page=page + 1, pages=pages)]
    rows = [nav_row(page, pages, lambda p: MenuCB(screen="activity", arg=p), ctx.lang), back_row(ctx.lang, "home")]
    await show(event, "\n".join(lines), kb(*rows))
