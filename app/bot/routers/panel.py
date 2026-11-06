"""👑 Panel (super admins, main bots): platform numbers, the clones (list, search, detail, 🛠 Gestionar, enable /
disable, approve / reject, limits, message to the owner, activity, delete), ⚙️ Plataforma (clone policy and default
limits), 📢 Aviso a los dueños and 📄 Errores (.txt)."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import ColumnElement, Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import BotStatus, BotUser, Chat, ChatStatus, Post, PostStatus, Run, User
from app.db.session import SessionMaker
from app.i18n import t
from app.services import blast, clones, events, freq, limits, logbook, stats
from app.services.notify import send_dm
from app.services.users import get_lang
from app.telegram.manager import BotManager
from app.ui.callbacks import MenuCB
from app.ui.common import (
    alert,
    back_row,
    btn,
    choice_label,
    grid,
    kb,
    nav_row,
    prompt,
    show,
    toast,
    visible_len,
    ws_banner,
)
from app.ui.fmt import esc, num, to_local, truncate, user_link
from app.ui.screens import open_screen, screen

log = logging.getLogger(__name__)

router = Router(name="panel")

BOTS_PER_PAGE = 10
ACTIVITY_PER_PAGE = 8
SEARCH_MAX = BOTS_PER_PAGE
FILTERS = ("all", "active", "paused", "pending", "invalid")
F_PENDING = FILTERS.index("pending")
FILTER_STATUS = {"active": BotStatus.ACTIVE, "paused": BotStatus.DISABLED, "pending": BotStatus.PENDING,
                 "invalid": BotStatus.INVALID}
STATUS_ICONS = {"active": "✅", "pending": "⏳", "paused": "⏸", "admin": "🔒", "removed": "🔌",
                "invalid": "❌"}
SETTING_FIELDS = ("max_clones", "limit_chats", "limit_posts")
NUMBER_MAX = 1_000_000
DM_MAX = 3500  # visible characters of a message to an owner (the header must fit too)

_tasks: set[asyncio.Task[None]] = set()  # running 📢 blasts (kept so they aren't garbage collected)
_blasts: set[tuple[int, int, int]] = set()  # (bot, super admin, message) already sent: a double tap sends once


class PanelCB(CallbackData, prefix="sa"):
    action: str
    id: int = 0  # bot id
    page: int = 0  # page of the bots list (kept to go back to it)
    f: int = 0  # filter of the bots list (index in FILTERS)
    v: int = 0  # action value: page of the activity, policy, setting, message to copy


class PanelFSM(StatesGroup):
    search = State()
    limits = State()
    dm = State()
    setting = State()
    blast = State()


def _allowed(ctx: Ctx) -> bool:
    return ctx.is_main and ctx.is_super


async def _scalar(session: AsyncSession, q: Select[Any]) -> int:
    return int((await session.execute(q)).scalar() or 0)


async def _load(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, bot_id: int) -> BotRecord | None:
    """The clone of a panel action: only for super admins in a main bot, never a main bot."""
    if not _allowed(ctx):
        await alert(event, ctx.t("common.no_permission"))
        return None
    rec = await session.get(BotRecord, bot_id, populate_existing=True) if bot_id else None
    if rec is None:
        await alert(event, ctx.t("common.not_found"))
        return None
    if rec.is_main:
        await alert(event, ctx.t("sa.main_locked"))
        return None
    return rec


def _owner_paused_now(now: datetime) -> tuple[ColumnElement[bool], ...]:
    """Approved chats paused by their owner right now (a pause whose end passed doesn't count)."""
    return (Chat.status == ChatStatus.APPROVED, Chat.owner_paused.is_(True),
            or_(Chat.owner_paused_until.is_(None), Chat.owner_paused_until > now))


def approval_markup(rec: BotRecord) -> Callable[[str], InlineKeyboardMarkup | None]:
    """Buttons of the notice of a new clone to the super admins: approve / reject it while it is pending."""
    pending, bot_id = rec.status == BotStatus.PENDING, rec.id

    def make(lang: str) -> InlineKeyboardMarkup | None:
        if not pending:
            return None
        return kb([btn(t("sa.btn.approve", lang), PanelCB(action="ok", id=bot_id), style="success"),
                   btn(t("sa.btn.reject", lang), PanelCB(action="no", id=bot_id), style="danger")])

    return make


# --------------------------------------------------------------------------- panel
@screen("panel")
async def panel_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                       **_: object) -> None:
    if not _allowed(ctx):
        await alert(event, ctx.t("common.no_permission"))
        return
    now = utcnow()
    by_status = {s: int(n) for s, n in (await session.execute(
        select(BotRecord.status, func.count()).where(BotRecord.is_main.is_(False)).group_by(BotRecord.status)
    )).all()}
    chats, members = (await session.execute(
        select(func.count(Chat.id), func.coalesce(func.sum(Chat.members), 0))
        .where(Chat.status == ChatStatus.APPROVED)
    )).one()
    runs, sent = (await session.execute(
        select(func.count(Run.id), func.coalesce(func.sum(Run.sent), 0))
        .where(Run.started_at >= now - timedelta(hours=24))
    )).one()
    policy = (await limits.platform(session, ctx.settings)).clone_policy
    pending = by_status.get(BotStatus.PENDING, 0)
    text = ctx.t(
        "sa.panel",
        bots=num(sum(by_status.values())),
        active=num(by_status.get(BotStatus.ACTIVE, 0)),
        paused=num(by_status.get(BotStatus.DISABLED, 0)),
        pending=num(pending),
        invalid=num(by_status.get(BotStatus.INVALID, 0)),
        users=num(await _scalar(session, select(func.count(func.distinct(BotUser.user_id))))),
        chats=num(chats),
        members=num(members),
        owner_paused=num(await _scalar(session, select(func.count()).select_from(Chat).where(
            *_owner_paused_now(now)))),
        posts=num(await _scalar(session, select(func.count()).select_from(Post).where(
            Post.status == PostStatus.ACTIVE))),
        runs=num(runs),
        sent=num(sent),
        policy=ctx.t(f"sa.policy.{policy}"),
    )
    first = [btn(ctx.t("sa.btn.bots"), PanelCB(action="bots"), style="primary")]
    if pending:
        first.append(btn(ctx.t("sa.btn.pending", n=pending), PanelCB(action="bots", f=F_PENDING)))
    markup = kb(
        first,
        [btn(ctx.t("sa.btn.settings"), MenuCB(screen="panel_settings")),
         btn(ctx.t("sa.btn.blast"), PanelCB(action="blast"))],
        [btn(ctx.t("sa.btn.errors"), PanelCB(action="logs"))],
        back_row(ctx.lang, "home"),
    )
    await show(event, text, markup)


# ---------------------------------------------------------------------- bots list
async def _rows(ctx: Ctx, session: AsyncSession, bots: list[BotRecord], start: int, *, page: int = 0,
                f: int = 0) -> tuple[list[str], list[InlineKeyboardButton]]:
    """``1. ✅ @clon_bot · 👤 @owner`` + ``   └📣 12 · 📝 5 · ⏸ 2`` per bot, and a button per bot."""
    if not bots:
        return [], []
    ids = [b.id for b in bots]
    owners = {u.id: u for u in (await session.execute(
        select(User).where(User.id.in_(list({b.owner_id for b in bots}))))).scalars()}

    async def per_bot(q: Select[Any]) -> dict[int, int]:
        return {int(b): int(n) for b, n in (await session.execute(q)).all()}

    chats = await per_bot(select(Chat.bot_id, func.count()).where(
        Chat.bot_id.in_(ids), Chat.status == ChatStatus.APPROVED).group_by(Chat.bot_id))
    posts = await per_bot(select(Post.bot_id, func.count()).where(
        Post.bot_id.in_(ids), Post.status == PostStatus.ACTIVE).group_by(Post.bot_id))
    paused = await per_bot(select(Chat.bot_id, func.count()).where(
        Chat.bot_id.in_(ids), *_owner_paused_now(utcnow())).group_by(Chat.bot_id))
    lines, buttons = [], []
    for i, rec in enumerate(bots, start):
        owner = owners.get(rec.owner_id)
        lines.append(ctx.t(
            "sa.bots.row", i=i, icon=STATUS_ICONS[clones.status_key(rec)], username=esc(rec.username or rec.id),
            owner=user_link(rec.owner_id, truncate(owner.full_name, 32) if owner else None,
                            owner.username if owner else None),
            chats=num(chats.get(rec.id, 0)), posts=num(posts.get(rec.id, 0)),
            paused=ctx.t("sa.bots.paused", n=num(paused[rec.id])) if paused.get(rec.id) else "",
        ))
        buttons.append(btn(f"#{i} @{truncate(rec.username or str(rec.id), 20)}",
                           PanelCB(action="bot", id=rec.id, page=page, f=f)))
    return lines, buttons


async def _show_bots(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, page: int = 0,
                     f: int = 0) -> None:
    f = f if 0 <= f < len(FILTERS) else 0
    conds = [BotRecord.is_main.is_(False)]
    if FILTERS[f] in FILTER_STATUS:
        conds.append(BotRecord.status == FILTER_STATUS[FILTERS[f]])
    total = await _scalar(session, select(func.count()).select_from(BotRecord).where(*conds))
    pages = max(1, -(-total // BOTS_PER_PAGE))
    page = min(max(0, page), pages - 1)
    bots = list((await session.execute(
        select(BotRecord).where(*conds).order_by(BotRecord.created_at.desc(), BotRecord.id.desc())
        .offset(page * BOTS_PER_PAGE).limit(BOTS_PER_PAGE).execution_options(populate_existing=True)
    )).scalars())
    lines = [ctx.t("sa.bots.title", filter=ctx.t(f"sa.filter.{FILTERS[f]}"), count=num(total)), ""]
    rows_text, buttons = await _rows(ctx, session, bots, page * BOTS_PER_PAGE + 1, page=page, f=f)
    lines += rows_text or [ctx.t("sa.bots.empty")]
    if pages > 1:
        lines += ["", ctx.t("common.page", page=page + 1, pages=pages)]
    rows = grid(buttons, 2)
    rows.append(nav_row(page, pages, lambda p: PanelCB(action="bots", page=p, f=f), ctx.lang))
    rows += grid([btn(choice_label(ctx.t(f"sa.filter.{name}"), i == f), PanelCB(action="bots", f=i))
                  for i, name in enumerate(FILTERS)], 3)
    rows.append([btn(ctx.t("sa.btn.find"), PanelCB(action="find"))])
    rows.append(back_row(ctx.lang, "panel"))
    await show(event, "\n".join(lines), kb(*rows))


@screen("panel_bots")
async def panel_bots_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                            f: int = 0, **_: object) -> None:
    if not _allowed(ctx):
        await alert(event, ctx.t("common.no_permission"))
        return
    await _show_bots(event, ctx, session, page=arg, f=f)


@router.callback_query(PanelCB.filter(F.action == "bots"))
async def on_bots(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession,
                  state: FSMContext) -> None:
    await state.clear()
    await panel_bots_screen(call, ctx, session, arg=callback_data.page, f=callback_data.f)


async def _find(session: AsyncSession, query: str) -> list[BotRecord]:
    """Clones by @username (or part of it) or id, or by their owner's @username or id; newest first."""
    q = query.strip().removeprefix("https://").removeprefix("t.me/").lstrip("@").strip()
    if not q:
        return []
    if q.isascii() and q.isdigit():
        cond = or_(BotRecord.id == int(q), BotRecord.owner_id == int(q))
    else:
        owners = select(User.id).where(func.lower(User.username) == q.lower())
        cond = or_(func.lower(BotRecord.username).contains(q.lower(), autoescape=True),
                   BotRecord.owner_id.in_(owners))
    rows = await session.execute(
        select(BotRecord).where(BotRecord.is_main.is_(False), cond)
        .order_by(BotRecord.created_at.desc(), BotRecord.id.desc()).limit(SEARCH_MAX + 1)
        .execution_options(populate_existing=True))
    return list(rows.scalars())


@router.callback_query(PanelCB.filter(F.action == "find"))
async def on_find(call: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    if not _allowed(ctx):
        await alert(call, ctx.t("common.no_permission"))
        return
    await state.set_state(PanelFSM.search)
    await prompt(call, ctx, ctx.t("sa.find.ask"), cancel_screen="panel_bots")


@router.message(PanelFSM.search, F.chat.type == "private", ~F.text.startswith("/"))
async def on_find_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not _allowed(ctx):
        await state.clear()
        return
    query = (message.text or "").strip()
    found = await _find(session, query)
    if not found:
        error = ctx.t("sa.find.none", query=esc(truncate(query, 64)))
        await prompt(message, ctx, f"{error}\n\n{ctx.t('sa.find.ask')}", cancel_screen="panel_bots")
        return
    await state.clear()
    if len(found) == 1:
        await _show_bot(message, ctx, session, found[0].id)
        return
    lines, buttons = await _rows(ctx, session, found[:SEARCH_MAX], 1)
    lines = [ctx.t("sa.find.title", query=esc(truncate(query, 64))), "", *lines]
    if len(found) > SEARCH_MAX:
        lines += ["", ctx.t("sa.find.more", n=SEARCH_MAX)]
    await show(message, "\n".join(lines), kb(*grid(buttons, 2), [btn(ctx.t("sa.btn.find"), PanelCB(action="find"))],
                                             back_row(ctx.lang, "panel_bots")))


# --------------------------------------------------------------------- bot detail
async def _limits_text(ctx: Ctx, session: AsyncSession, rec: BotRecord) -> str:
    """``50 chats · 20 mensajes (predeterminado)`` / ``sin límites``."""
    if limits.unlimited(ctx.settings, rec):
        return ctx.t("sa.lim.super")
    chats = await limits.max_chats(session, ctx.settings, rec)
    posts = await limits.max_posts(session, ctx.settings, rec)
    default = " " + ctx.t("sa.lim.default")
    if not chats and not posts:
        return ctx.t("sa.lim.none") + (default if rec.limit_chats is None and rec.limit_posts is None else "")
    return " · ".join((
        (ctx.t("sa.lim.chats", n=num(chats)) if chats else ctx.t("sa.lim.chats_free"))
        + (default if rec.limit_chats is None else ""),
        (ctx.t("sa.lim.posts", n=num(posts)) if posts else ctx.t("sa.lim.posts_free"))
        + (default if rec.limit_posts is None else ""),
    ))


async def _bot_view(ctx: Ctx, session: AsyncSession, rec: BotRecord, page: int,
                    f: int) -> tuple[str, InlineKeyboardMarkup]:
    owner = await session.get(User, rec.owner_id)
    s = await stats.summary(session, rec.id, hours=24)
    text = ctx.t(
        "sa.bot",
        username=esc(rec.username or rec.id),
        name=f" ({esc(rec.name)})" if rec.name else "",
        id=rec.id,
        owner=user_link(rec.owner_id, owner.full_name if owner else None, owner.username if owner else None),
        owner_id=rec.owner_id,
        status=ctx.t(f"cl.status.{clones.status_key(rec)}"),
        created=to_local(rec.created_at, ctx.tz).strftime("%d/%m/%Y"),
        chats=num(s.chats), own=num(s.own), ext=num(s.external), members=num(s.members),
        owner_paused=num(s.owner_paused), pending=num(s.pending),
        posts=num(s.posts_active), freq=freq.describe(rec.freq, ctx.lang),
        runs=num(s.runs), sent=num(s.sent), failed=num(s.failed),
        limits=await _limits_text(ctx, session, rec),
    )
    if rec.paused:
        text += "\n" + ctx.t("sa.bot.net_paused")

    def cb(action: str) -> PanelCB:
        return PanelCB(action=action, id=rec.id, page=page, f=f)

    rows = [[btn(ctx.t("sa.btn.manage"), cb("ws"), style="primary")]]
    # Explicit actions, not toggles: a double tap must not undo the first one.
    if rec.status == BotStatus.PENDING:
        rows.append([btn(ctx.t("sa.btn.approve"), cb("ok"), style="success"),
                     btn(ctx.t("sa.btn.reject"), cb("no"), style="danger")])
    elif rec.status == BotStatus.ACTIVE:
        rows.append([btn(ctx.t("sa.btn.disable"), cb("off"))])
    else:
        rows.append([btn(ctx.t("sa.btn.enable"), cb("on"), style="success")])
    row = [btn(ctx.t("sa.btn.dm"), cb("dm"))]
    if not limits.unlimited(ctx.settings, rec):
        row.insert(0, btn(ctx.t("sa.btn.limits"), cb("lim")))
    rows.append(row)
    rows.append([btn(ctx.t("sa.btn.activity"), cb("act")), btn(ctx.t("sa.btn.errors"), cb("logs"))])
    rows.append([btn(ctx.t("sa.btn.delete"), cb("del"), style="danger")])
    rows.append([btn(ctx.t("common.back"), PanelCB(action="bots", page=page, f=f))])
    return text, kb(*rows)


async def _show_bot(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, bot_id: int, *,
                    page: int = 0, f: int = 0, notice: str | None = None) -> None:
    rec = await session.get(BotRecord, bot_id, populate_existing=True)  # the manager changes it in its own session
    if rec is None or rec.is_main:
        await alert(event, ctx.t("common.not_found"))
        await _show_bots(event, ctx, session, page, f)
        return
    text, markup = await _bot_view(ctx, session, rec, page, f)
    await show(event, f"{notice}\n\n{text}" if notice else text, markup)


@screen("panel_bot")
async def panel_bot_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                           **_: object) -> None:
    if await _load(event, ctx, session, arg) is not None:
        await _show_bot(event, ctx, session, arg)


@router.callback_query(PanelCB.filter(F.action == "bot"))
async def on_bot(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession,
                 state: FSMContext) -> None:
    await state.clear()
    if await _load(call, ctx, session, callback_data.id) is not None:
        await _show_bot(call, ctx, session, callback_data.id, page=callback_data.page, f=callback_data.f)


@router.callback_query(PanelCB.filter(F.action == "ws"))
async def on_manage(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession,
                    state: FSMContext) -> None:
    """🛠 Gestionar: the clone's network inside this main bot (every screen of this super admin works on it, with
    the banner, until they leave it from the home screen)."""
    rec = await _load(call, ctx, session, callback_data.id)
    if rec is None:
        return
    if ctx.bu is None:
        await alert(call, ctx.t("common.error"))
        return
    await state.clear()
    ctx.bu.ws_bot_id = rec.id
    ctx.ws = rec  # this update already works on the clone
    ws_banner.set(t("ws.banner", ctx.lang, username=esc(rec.username or rec.id)))
    log.info("Super admin %s manages bot %s (@%s) from bot %s", ctx.user_id, rec.id, rec.username, ctx.bot_id)
    await open_screen("home", call, ctx, session)


@router.callback_query(PanelCB.filter(F.action.in_({"off", "on"})))
async def on_switch(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession,
                    manager: BotManager) -> None:
    rec = await _load(call, ctx, session, callback_data.id)
    if rec is None:
        return
    if callback_data.action == "off":
        if rec.status == BotStatus.ACTIVE:
            await toast(call, ctx.t("sa.disabled"))  # first: its posts are withdrawn before it stops
            await manager.disable_bot(rec.id, reason=clones.REASON_ADMIN)
            log.info("Bot %s (@%s) disabled by super admin %s", rec.id, rec.username, ctx.user_id)
    elif rec.status not in (BotStatus.ACTIVE, BotStatus.PENDING):  # pending bots are approved instead
        if await manager.enable_bot(rec.id):
            await toast(call, ctx.t("sa.enabled"))
            log.info("Bot %s (@%s) enabled by super admin %s", rec.id, rec.username, ctx.user_id)
        else:
            await alert(call, ctx.t("sa.enable_failed"))
    await _show_bot(call, ctx, session, rec.id, page=callback_data.page, f=callback_data.f)


@router.callback_query(PanelCB.filter(F.action.in_({"ok", "no"})))
async def on_decide(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession, bot: Bot,
                    manager: BotManager) -> None:
    """✅ Aprobar / ❌ Rechazar a pending clone (from its detail or from the notice of the new clone)."""
    rec = await _load(call, ctx, session, callback_data.id)
    if rec is None:
        return
    if rec.status != BotStatus.PENDING:
        await alert(call, ctx.t("sa.not_pending"))
    else:
        lang = await get_lang(session, bot.id, rec.owner_id, ctx.settings.DEFAULT_LANG)
        username = rec.username
        if callback_data.action == "ok":
            if await manager.enable_bot(rec.id):
                await toast(call, ctx.t("sa.approved"))
                markup = kb([btn(t("cl.btn.open", lang, username=username), url=f"https://t.me/{username}",
                                 style="success")])
                await send_dm(bot, session, rec.owner_id, t("cl.approved_dm", lang, username=esc(username)), markup)
                log.info("Clone %s (@%s) approved by %s", rec.id, username, ctx.user_id)
            else:
                await alert(call, ctx.t("sa.enable_failed"))
        else:
            await manager.disable_bot(rec.id, reason=clones.REASON_ADMIN)
            await toast(call, ctx.t("sa.rejected"))
            await send_dm(bot, session, rec.owner_id, t("cl.rejected_dm", lang, username=esc(username)))
            log.info("Clone %s (@%s) rejected by %s", rec.id, username, ctx.user_id)
    await _show_bot(call, ctx, session, rec.id, page=callback_data.page, f=callback_data.f)


# --------------------------------------------------------------------- limits / DM
def parse_limits(text: str) -> tuple[int | None, int | None] | None:
    """``"50 20"`` -> (50, 20); ``0`` = unlimited, ``-`` = the platform default; one value sets both."""
    parts = text.replace(",", " ").split()
    if len(parts) == 1:
        parts *= 2
    if len(parts) != 2:
        return None
    values: list[int | None] = []
    for part in parts:
        if part in ("-", "—"):
            values.append(None)
        elif part.isascii() and part.isdigit() and int(part) <= NUMBER_MAX:
            values.append(int(part))
        else:
            return None
    return values[0], values[1]


async def _input_bot(message: Message, ctx: Ctx, session: AsyncSession,
                     state: FSMContext) -> tuple[BotRecord | None, dict[str, Any]]:
    """The clone a text input of the panel is about (stored when the input was asked)."""
    data = await state.get_data()
    rec = await _load(message, ctx, session, int(data.get("bot_id") or 0))
    if rec is None:
        await state.clear()
    return rec, data


@router.callback_query(PanelCB.filter(F.action.in_({"lim", "dm"})))
async def on_ask(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession,
                 state: FSMContext) -> None:
    rec = await _load(call, ctx, session, callback_data.id)
    if rec is None:
        return
    await state.set_state(PanelFSM.limits if callback_data.action == "lim" else PanelFSM.dm)
    await state.update_data(bot_id=rec.id, page=callback_data.page, f=callback_data.f)
    if callback_data.action == "lim":
        text = ctx.t("sa.lim.ask", username=esc(rec.username), current=await _limits_text(ctx, session, rec))
    else:
        text = ctx.t("sa.dm.ask", username=esc(rec.username))
    await prompt(call, ctx, text, cancel_screen="panel_bot", cancel_arg=rec.id)


@router.message(PanelFSM.limits, F.chat.type == "private", ~F.text.startswith("/"))
async def on_limits_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    rec, data = await _input_bot(message, ctx, session, state)
    if rec is None:
        return
    parsed = parse_limits(message.text or "")
    if parsed is None:
        text = ctx.t("sa.lim.ask", username=esc(rec.username), current=await _limits_text(ctx, session, rec))
        await prompt(message, ctx, f"{ctx.t('sa.lim.err')}\n\n{text}", cancel_screen="panel_bot", cancel_arg=rec.id)
        return
    rec.limit_chats, rec.limit_posts = parsed
    await session.flush()
    await state.clear()
    log.info("Limits of bot %s set to %s by %s", rec.id, parsed, ctx.user_id)
    await _show_bot(message, ctx, session, rec.id, page=int(data.get("page") or 0), f=int(data.get("f") or 0),
                    notice=ctx.t("common.saved"))


@router.message(PanelFSM.dm, F.chat.type == "private", ~F.text.startswith("/"))
async def on_dm_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    rec, data = await _input_bot(message, ctx, session, state)
    if rec is None:
        return
    error = None
    if not message.text:
        error = ctx.t("sa.dm.err_text")
    elif visible_len(message.html_text) > DM_MAX:
        error = ctx.t("common.too_long", max=DM_MAX)
    if error:
        text = ctx.t("sa.dm.ask", username=esc(rec.username))
        await prompt(message, ctx, f"{error}\n\n{text}", cancel_screen="panel_bot", cancel_arg=rec.id)
        return
    lang = await get_lang(session, bot.id, rec.owner_id, ctx.settings.DEFAULT_LANG)
    header = t("sa.dm.header", lang, username=esc(rec.username))
    sent = await send_dm(bot, session, rec.owner_id, f"{header}\n\n{message.html_text}")
    await state.clear()
    log.info("Super admin %s wrote to the owner of bot %s (sent=%s)", ctx.user_id, rec.id, sent is not None)
    await _show_bot(message, ctx, session, rec.id, page=int(data.get("page") or 0), f=int(data.get("f") or 0),
                    notice=ctx.t("sa.dm.sent" if sent is not None else "sa.dm.failed"))


# ------------------------------------------------------------------ activity / errors
@router.callback_query(PanelCB.filter(F.action == "act"))
async def on_activity(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession) -> None:
    rec = await _load(call, ctx, session, callback_data.id)
    if rec is None:
        return
    page = max(0, callback_data.v)
    found = await events.recent(session, rec.id, limit=ACTIVITY_PER_PAGE + 1, offset=page * ACTIVITY_PER_PAGE)
    lines = [ctx.t("sa.act.title", username=esc(rec.username))]
    lines += [await events.describe(session, ev, ctx.lang, ctx.tz) for ev in found[:ACTIVITY_PER_PAGE]]
    if not found:
        lines.append(ctx.t("sa.act.empty"))

    def cb(v: int) -> PanelCB:
        return PanelCB(action="act", id=rec.id, page=callback_data.page, f=callback_data.f, v=v)

    nav = []
    if page > 0:
        nav.append(btn(ctx.t("common.prev"), cb(page - 1)))
    if len(found) > ACTIVITY_PER_PAGE:
        nav.append(btn(ctx.t("common.next"), cb(page + 1)))
    back = [btn(ctx.t("common.back"), PanelCB(action="bot", id=rec.id, page=callback_data.page, f=callback_data.f))]
    await show(call, "\n\n".join(lines), kb(nav, back))


@router.callback_query(PanelCB.filter(F.action == "logs"))
async def on_errors(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession, bot: Bot) -> None:
    """📄 Errores: the recent warnings and errors of every bot (``id`` 0) or of one clone, as a .txt file."""
    if not _allowed(ctx):
        await alert(call, ctx.t("common.no_permission"))
        return
    rec = None
    if callback_data.id:
        rec = await _load(call, ctx, session, callback_data.id)
        if rec is None:
            return
    target = f"@{rec.username or rec.id}" if rec is not None else ctx.t("sa.file.all")
    entries = logbook.book.select(rec.id if rec is not None else None)
    title = ctx.t("sa.file.errors", target=target)
    lines = [title, ctx.t("sa.file.errors_note", n=logbook.MAX_RECORDS, tz=ctx.tz), ""]
    for e in entries:
        tag = f"[bot {e.bot_id}] " if rec is None and e.bot_id else ""
        lines.append(f"{to_local(e.at, ctx.tz):%Y-%m-%d %H:%M:%S} {tag}{e.text}")
    if not entries:
        lines.append(ctx.t("sa.file.none"))
    slug = (rec.username or str(rec.id)) if rec is not None else "all"
    name = f"errors_{slug}_{to_local(utcnow(), ctx.tz):%Y-%m-%d_%H%M}.txt"
    try:
        await bot.send_document(ctx.user_id, BufferedInputFile(("\n".join(lines) + "\n").encode("utf-8"), name),
                                caption=ctx.t("sa.file.caption", what=esc(title), n=num(len(entries))))
    except TelegramAPIError as exc:
        log.warning("The errors file could not be sent: %s", exc)
        await alert(call, ctx.t("common.error"))
        return
    await toast(call, ctx.t("sa.file.sent"))


# -------------------------------------------------------------------------- delete
@router.callback_query(PanelCB.filter(F.action.in_({"del", "del2", "del3"})))
async def on_delete(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession,
                    manager: BotManager) -> None:
    """🗑 Eliminar, confirmed twice: the bot stops (its pending auto deletes first) and its row goes, and with it
    every row of its network (chats, groups, posts, runs, activity, users)."""
    rec = await _load(call, ctx, session, callback_data.id)
    if rec is None:
        return
    back = btn(ctx.t("common.no"), PanelCB(action="bot", id=rec.id, page=callback_data.page, f=callback_data.f))
    if callback_data.action != "del3":
        first = callback_data.action == "del"
        yes = btn(ctx.t("sa.btn.delete_yes" if first else "sa.btn.delete_final"),
                  PanelCB(action="del2" if first else "del3", id=rec.id, page=callback_data.page, f=callback_data.f),
                  style="danger")
        await show(call, ctx.t("sa.confirm_delete" if first else "sa.confirm_delete2", username=esc(rec.username)),
                   kb([yes, back]))
        return
    await toast(call, ctx.t("sa.deleted"))  # first: its posts are withdrawn before it stops, it can take a while
    bot_id, username = rec.id, rec.username
    await manager.disable_bot(bot_id, reason=clones.REASON_ADMIN)
    await session.execute(update(BotUser).where(BotUser.ws_bot_id == bot_id).values(ws_bot_id=None))
    await session.delete(rec)
    await session.flush()
    if ctx.ws_id == bot_id:  # this super admin was managing it
        ctx.ws = ctx.bot_rec
        ws_banner.set("")
    log.info("Clone %s (@%s) deleted by super admin %s", bot_id, username, ctx.user_id)
    await _show_bots(call, ctx, session, callback_data.page, callback_data.f)


# ------------------------------------------------------------------ ⚙️ Plataforma
@screen("panel_settings")
async def panel_settings_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                                notice: str | None = None, **_: object) -> None:
    if not _allowed(ctx):
        await alert(event, ctx.t("common.no_permission"))
        return
    p = await limits.platform(session, ctx.settings)

    def value(n: int) -> str:
        return num(n) if n else ctx.t("sa.set.unlimited")

    lines = [
        ctx.t("sa.set.title"), "",
        ctx.t("sa.set.policy", policy=ctx.t(f"sa.policy.{p.clone_policy}"),
              hint=ctx.t(f"sa.policy.hint.{p.clone_policy}")),
        ctx.t("sa.set.max_clones", value=value(p.max_clones)),
        ctx.t("sa.set.limit_chats", value=value(p.limit_chats)),
        ctx.t("sa.set.limit_posts", value=value(p.limit_posts)),
        ctx.t("sa.set.limits_hint"),
    ]
    if notice:
        lines = [notice, "", *lines]
    markup = kb(
        [btn(choice_label(ctx.t(f"sa.policy.{policy}"), policy == p.clone_policy), PanelCB(action="pol", v=i))
         for i, policy in enumerate(limits.POLICIES)],
        *([btn(ctx.t(f"sa.btn.{field}", value=value(getattr(p, field))), PanelCB(action="set", v=i))]
          for i, field in enumerate(SETTING_FIELDS)),
        back_row(ctx.lang, "panel"),
    )
    await show(event, "\n".join(lines), markup)


@router.callback_query(PanelCB.filter(F.action == "pol"))
async def on_policy(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession) -> None:
    if not _allowed(ctx) or not 0 <= callback_data.v < len(limits.POLICIES):
        await alert(call, ctx.t("common.no_permission"))
        return
    p = await limits.platform(session, ctx.settings)
    p.clone_policy = limits.POLICIES[callback_data.v]
    await limits.save_platform(session, p)
    log.info("Clone policy set to %s by %s", p.clone_policy, ctx.user_id)
    await toast(call, ctx.t("common.saved"))
    await panel_settings_screen(call, ctx, session)


def _setting_prompt(ctx: Ctx, field: str, current: int) -> str:
    return ctx.t(f"sa.set.ask.{field}", value=num(current) if current else ctx.t("sa.set.unlimited"))


@router.callback_query(PanelCB.filter(F.action == "set"))
async def on_setting(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession,
                     state: FSMContext) -> None:
    if not _allowed(ctx) or not 0 <= callback_data.v < len(SETTING_FIELDS):
        await alert(call, ctx.t("common.no_permission"))
        return
    field = SETTING_FIELDS[callback_data.v]
    p = await limits.platform(session, ctx.settings)
    await state.set_state(PanelFSM.setting)
    await state.update_data(field=field)
    await prompt(call, ctx, _setting_prompt(ctx, field, getattr(p, field)), cancel_screen="panel_settings")


@router.message(PanelFSM.setting, F.chat.type == "private", ~F.text.startswith("/"))
async def on_setting_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    field = (await state.get_data()).get("field")
    if not _allowed(ctx) or field not in SETTING_FIELDS:
        await state.clear()
        return
    p = await limits.platform(session, ctx.settings)
    text = (message.text or "").strip()
    if not (text.isascii() and text.isdigit() and int(text) <= NUMBER_MAX):
        error = ctx.t("common.invalid_number")
        await prompt(message, ctx, f"{error}\n\n{_setting_prompt(ctx, field, getattr(p, field))}",
                     cancel_screen="panel_settings")
        return
    setattr(p, field, int(text))
    await limits.save_platform(session, p)
    await state.clear()
    log.info("Platform setting %s set to %s by %s", field, text, ctx.user_id)
    await panel_settings_screen(message, ctx, session, notice=ctx.t("common.saved"))


# ------------------------------------------------------------ 📢 Aviso a los dueños
async def _owners(session: AsyncSession, ctx: Ctx) -> list[int]:
    return [uid for uid in await clones.clone_owner_ids(session) if uid != ctx.user_id]


@screen("panel_blast")
async def panel_blast_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                             state: FSMContext | None = None, **_: object) -> None:
    """A message copied to the owners of every clone through this bot. Opened with a ``state`` it asks for the
    message at once; otherwise it explains it first."""
    if not _allowed(ctx):
        await alert(event, ctx.t("common.no_permission"))
        return
    owners = await _owners(session, ctx)
    if not owners:
        await show(event, ctx.t("sa.blast.none"), kb(back_row(ctx.lang, "panel")))
        return
    if state is None:
        markup = kb([btn(ctx.t("sa.btn.blast_write"), PanelCB(action="blast"), style="primary")],
                    back_row(ctx.lang, "panel"))
        await show(event, ctx.t("sa.blast.intro", n=num(len(owners))), markup)
        return
    await state.set_state(PanelFSM.blast)
    await prompt(event, ctx, ctx.t("sa.blast.ask", n=num(len(owners))), cancel_screen="panel")


@router.callback_query(PanelCB.filter(F.action == "blast"))
async def on_blast(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    await panel_blast_screen(call, ctx, session, state=state)


@router.message(PanelFSM.blast, F.chat.type == "private", ~F.text.startswith("/"))
async def on_blast_message(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if not _allowed(ctx):
        return
    owners = await _owners(session, ctx)
    if not owners:
        await show(message, ctx.t("sa.blast.none"), kb(back_row(ctx.lang, "panel")))
        return
    markup = kb([btn(ctx.t("sa.btn.blast_send"), PanelCB(action="blast_go", v=message.message_id), style="success"),
                 btn(ctx.t("common.no"), MenuCB(screen="panel"))])
    await show(message, ctx.t("sa.blast.confirm", n=num(len(owners))), markup)


async def _run_blast(bot: Bot, sm: SessionMaker, admin_id: int, message_id: int, owners: list[int],
                     lang: str) -> None:
    res = await blast.copy_to_users(bot, sm, admin_id, message_id, owners)
    log.info("Notice to the owners of clones by %s: %d sent, %d blocked, %d failed", admin_id, res.sent,
             res.blocked, res.failed)
    await send_dm(bot, None, admin_id, t("sa.blast.done", lang, sent=num(res.sent), blocked=num(res.blocked),
                                         failed=num(res.failed)))


@router.callback_query(PanelCB.filter(F.action == "blast_go"))
async def on_blast_go(call: CallbackQuery, callback_data: PanelCB, ctx: Ctx, session: AsyncSession, bot: Bot,
                      sm: SessionMaker) -> None:
    if not _allowed(ctx):
        await alert(call, ctx.t("common.no_permission"))
        return
    key = (bot.id, ctx.user_id, callback_data.v)
    if key in _blasts:
        await alert(call, ctx.t("sa.blast.dup"))
        return
    owners = await _owners(session, ctx)
    if not owners:
        await show(call, ctx.t("sa.blast.none"), kb(back_row(ctx.lang, "panel")))
        return
    _blasts.add(key)
    task = asyncio.create_task(_run_blast(bot, sm, ctx.user_id, callback_data.v, owners, ctx.lang))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    await show(call, ctx.t("sa.blast.started", n=num(len(owners))), kb(back_row(ctx.lang, "panel")))
