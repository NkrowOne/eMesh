"""🏠 Home, 📖 guide and the basic commands: /start (+ deep links), /cancel, /id, /help, /admin and /deladmin.

The home has three views: the network of the admins (with its summary and ⏸ Pausar todo), the partners and visitors
(how to join, their chats, support) and the main bot in hub mode (what eMesh is, create your bot).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.filters import PrivateFilter
from app.bot.routers.settings import (
    AdminError,
    demote,
    find_target,
    join_text_default,
    notify_role_change,
    promote,
    support_url,
    user_label,
    with_notice,
)
from app.bot.routers.timezone import needs_timezone
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import Chat, ChatOrigin, ChatStatus, EventKind
from app.services import clones, events, freq, limits, stats
from app.services.chatinfo import add_to_channel_url, add_to_group_url
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, kb, nav_row, show, toast, ws_banner
from app.ui.fmt import dt, num
from app.ui.screens import open_screen, screen

log = logging.getLogger(__name__)

router = Router(name="start")

GUIDE_PAGES = {"admin": 5, "partner": 2, "hub": 2}
_CHAT_LINK = re.compile(r"c(\d{1,9})")
_POST_LINK = re.compile(r"p(\d{1,9})")
_TG_EMOJI_RE = re.compile(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", re.IGNORECASE | re.DOTALL)


class StCB(CallbackData, prefix="st"):
    """``pause`` / ``resume`` the whole distribution, ``exit`` the workspace (a clone managed from the main bot)."""

    action: str


def deep_link_target(payload: str | None, *, admin: bool) -> tuple[str, int]:
    """Screen and argument of a ``/start <payload>`` deep link (``home`` when it is unknown)."""
    payload = (payload or "").strip()
    if payload in ("join", "clone"):
        return payload, 0
    if match := _CHAT_LINK.fullmatch(payload):
        return ("chat" if admin else "my_chat"), int(match.group(1))
    if admin and (match := _POST_LINK.fullmatch(payload)):
        return "post", int(match.group(1))
    return "home", 0


# ---------------------------------------------------------------------------------------------------
# 🏠 Home
# ---------------------------------------------------------------------------------------------------
@screen("home")
async def home_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, notice: str | None = None,
    **_: object,
) -> None:
    if needs_timezone(ctx):  # a new clone: its owner chooses the timezone first
        await open_screen("timezone", event, ctx, session)
        return
    if ctx.is_hub:
        text, markup = await _hub_home(ctx, session)
    elif ctx.is_admin:
        text, markup = await _admin_home(ctx, session)
    else:
        await _partner_home(event, ctx, session, notice)
        return
    await show(event, with_notice(text, notice), markup)


def _next_turn(ws: BotRecord, tz: str, now: datetime) -> datetime | None:
    """Next slot of the global frequency (the stored one, unless it already passed)."""
    if ws.rot_next_at is not None and ws.rot_next_at > now:
        return ws.rot_next_at
    return freq.next_slot(ws.freq, tz, now)


async def _admin_home(ctx: Ctx, session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    ws = ctx.ws_rec
    now = utcnow()
    s = await stats.summary(session, ws.id, now=now)
    lines = [ctx.t("home.admin.title"), ""]
    if s.chats:
        lines += [ctx.t("home.chats", n=num(s.chats), members=num(s.members)),
                  ctx.t("home.chats.split", own=num(s.own), ext=num(s.external))]
    else:
        lines.append(ctx.t("home.chats.none"))
    lines.append(ctx.t("home.posts", n=num(s.posts_active)))
    if not s.posts_active:
        lines.append(ctx.t("home.posts.none"))
    lines.append(ctx.t("home.freq", freq=freq.describe(ws.freq, ctx.lang)))
    if not ws.paused:
        lines.append(ctx.t("home.next", date=dt(_next_turn(ws, ctx.bot_tz, now), ctx.tz)))
    for key, value in (("home.owner_paused", s.owner_paused), ("home.pending", s.pending),
                       ("home.no_rights", s.no_rights)):
        if value:
            lines.append(ctx.t(key, n=num(value)))
    if ws.paused:
        lines += ["", ctx.t("home.paused")]

    rows: list[list[InlineKeyboardButton | None]] = [
        [btn(ctx.t("home.btn.posts"), MenuCB(screen="posts")), btn(ctx.t("home.btn.chats"), MenuCB(screen="chats"))],
        [btn(ctx.t("home.btn.groups"), MenuCB(screen="groups")),
         btn(ctx.t("home.btn.freqs"), MenuCB(screen="freqs"))],
        [btn(ctx.t("home.btn.stats"), MenuCB(screen="stats")),
         btn(ctx.t("home.btn.activity"), MenuCB(screen="activity"))],
        [btn(ctx.t("home.btn.requests", n=s.pending), MenuCB(screen="requests")) if s.pending else None,
         btn(ctx.t("home.btn.paused", n=s.owner_paused), MenuCB(screen="paused")) if s.owner_paused else None],
    ]
    if ws.username:
        rows.append([btn(ctx.t("home.btn.add_channel"), url=add_to_channel_url(ws.username)),
                     btn(ctx.t("home.btn.add_group"), url=add_to_group_url(ws.username))])
    if ws.paused:
        rows.append([btn(ctx.t("home.btn.resume_all"), StCB(action="resume"), style="success")])
    else:
        rows.append([btn(ctx.t("home.btn.pause_all"), StCB(action="pause"))])
    rows.append([btn(ctx.t("home.btn.settings"), MenuCB(screen="settings")),
                 btn(ctx.t("home.btn.guide"), MenuCB(screen="guide"))])
    if ctx.is_main and not ctx.in_ws:
        mine = await clones.count_user_bots(session, ctx.user_id)
        rows.append([btn(ctx.t("home.btn.create_mine"), MenuCB(screen="clone")),
                     btn(ctx.t("home.btn.mybots", n=mine), MenuCB(screen="mybots")) if mine else None])
    if ctx.is_super and ctx.is_main:
        rows.append([btn(ctx.t("home.btn.panel"), MenuCB(screen="panel"))])
    if ctx.in_ws:
        rows.append([btn(ctx.t("home.btn.exit_ws", bot=ws.username or ws.id), StCB(action="exit"),
                         style="danger")])
    return "\n".join(lines), kb(*rows)


async def _my_chats(session: AsyncSession, bot_id: int, user_id: int) -> int:
    """External chats of the user in the network (any status but left)."""
    q = select(func.count()).select_from(Chat).where(
        Chat.bot_id == bot_id, Chat.owner_user_id == user_id, Chat.origin == ChatOrigin.EXTERNAL,
        Chat.status != ChatStatus.LEFT)
    return int((await session.execute(q)).scalar() or 0)


async def _create_own_button(ctx: Ctx, session: AsyncSession) -> InlineKeyboardButton | None:
    """🤖 Crea tu propio bot: the clone screen in the main bot, a link to the main bot in a clone (none when the
    platform doesn't accept new bots)."""
    if (await limits.platform(session, ctx.settings)).clone_policy == "closed":
        return None
    if ctx.is_main:
        return btn(ctx.t("home.btn.create_own"), MenuCB(screen="clone"))
    main = await clones.main_username(session, ctx.settings)
    return btn(ctx.t("home.btn.create_own"), url=f"https://t.me/{main}?start=clone") if main else None


def _partner_text(ctx: Ctx, *, platform: bool, custom: str | None) -> str:
    ws = ctx.ws_rec
    parts = [ctx.t("home.platform")] if platform else []
    if ws.join_open:
        block = [custom or join_text_default(ctx)]
        if ws.min_members:
            block.append(ctx.t("home.join.min", n=num(ws.min_members)))
        if ws.join_approval:
            block.append(ctx.t("home.join.approval"))
        parts.append("\n\n".join(block))
    else:
        parts.append(ctx.t("home.private"))
    return "\n\n".join(parts)


async def _partner_home(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, notice: str | None) -> None:
    ws = ctx.ws_rec
    create = await _create_own_button(ctx, session)
    rows: list[list[InlineKeyboardButton | None]] = []
    if ws.join_open and ws.username:
        rows.append([btn(ctx.t("home.btn.join_channel"), url=add_to_channel_url(ws.username)),
                     btn(ctx.t("home.btn.join_group"), url=add_to_group_url(ws.username))])
    mine = await _my_chats(session, ws.id, ctx.user_id)
    if mine:
        rows.append([btn(ctx.t("home.btn.my_chats", n=mine), MenuCB(screen="my_chats"))])
    support = await support_url(session, ws)
    rows.append([btn(ctx.t("home.btn.guide"), MenuCB(screen="guide")),
                 btn(ctx.t("home.btn.support"), url=support) if support else None])
    rows.append([btn(ctx.t("home.btn.settings"), MenuCB(screen="settings"))])
    bots = await clones.count_user_bots(session, ctx.user_id) if ctx.is_main else 0
    rows.append([create, btn(ctx.t("home.btn.mybots", n=bots), MenuCB(screen="mybots")) if bots else None])
    markup = kb(*rows)
    platform = ctx.is_main and create is not None  # the platform's own bot introduces eMesh first
    # The owner's welcome text is Telegram HTML: custom emoji can't be used by most bots, and if Telegram still
    # refuses it the default text is shown instead.
    custom = _TG_EMOJI_RE.sub(r"\1", ws.join_text) if ws.join_open and ws.join_text else None
    if custom:
        try:
            await show(event, with_notice(_partner_text(ctx, platform=platform, custom=custom), notice), markup)
            return
        except TelegramBadRequest as exc:
            log.warning("The welcome text of bot %s was refused by Telegram: %s", ws.id, exc)
    await show(event, with_notice(_partner_text(ctx, platform=platform, custom=None), notice), markup)


async def _hub_home(ctx: Ctx, session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    mine = await clones.count_user_bots(session, ctx.user_id)
    rows: list[list[InlineKeyboardButton | None]] = [
        [btn(ctx.t("home.btn.create_hub"), MenuCB(screen="clone"), style="success")],
        [btn(ctx.t("home.btn.mybots", n=mine), MenuCB(screen="mybots")) if mine else None],
        [btn(ctx.t("home.btn.guide"), MenuCB(screen="guide")),
         btn(ctx.t("home.btn.settings"), MenuCB(screen="settings"))],
        [btn(ctx.t("home.btn.panel"), MenuCB(screen="panel")) if ctx.is_super else None],
    ]
    return ctx.t("home.hub"), kb(*rows)


@router.callback_query(StCB.filter(F.action.in_({"pause", "resume"})))
async def on_pause_all(
    call: CallbackQuery, callback_data: StCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    """⏸ Pausar todo / ▶️ Reanudar todo: nothing of the network is sent while it is paused."""
    if not ctx.is_admin or ctx.is_hub:
        await alert(call, ctx.t("common.no_permission"))
        return
    await state.clear()
    ws = ctx.ws_rec
    pause = callback_data.action == "pause"
    if ws.paused != pause:
        ws.paused = pause
        await events.emit(ctx.ws_bot(), session, ws, EventKind.BOT_PAUSED if pause else EventKind.BOT_RESUMED,
                          actor_id=ctx.user_id, notify=True, skip_user=ctx.user_id)
        await toast(call, ctx.t("home.toast.paused" if pause else "home.toast.resumed"))
    await home_screen(call, ctx, session)


@router.callback_query(StCB.filter(F.action == "exit"))
async def on_exit_workspace(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    """🚪 Salir de @clone: the super admin goes back to the network of the main bot."""
    await state.clear()
    left = ctx.ws_rec
    if ctx.bu is not None and ctx.bu.ws_bot_id:
        ctx.bu.ws_bot_id = None
    if ctx.in_ws:
        ctx.ws = ctx.bot_rec
        ws_banner.set("")
        await toast(call, ctx.t("home.toast.ws_left", bot=left.username or left.id))
    await home_screen(call, ctx, session)


# ---------------------------------------------------------------------------------------------------
# 📖 Guide
# ---------------------------------------------------------------------------------------------------
@screen("guide")
async def guide_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, **_: object
) -> None:
    """``arg``: 0-based page. Admins, partners and the hub each have their own guide."""
    kind = "hub" if ctx.is_hub else "admin" if ctx.is_admin else "partner"
    pages = GUIDE_PAGES[kind]
    page = min(max(arg, 0), pages - 1)
    text = f"{ctx.t(f'guide.{kind}.{page + 1}')}\n\n{ctx.t('common.page', page=page + 1, pages=pages)}"
    await show(event, text, kb(nav_row(page, pages, lambda p: MenuCB(screen="guide", arg=p), ctx.lang),
                               back_row(ctx.lang, "home")))


# ---------------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------------
@router.message(CommandStart(), PrivateFilter())
async def on_start(
    message: Message, command: CommandObject, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    await state.clear()
    name, arg = deep_link_target(command.args, admin=ctx.is_admin)
    await open_screen(name, message, ctx, session, arg=arg)


@router.message(Command("cancel"), PrivateFilter())
async def on_cancel(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    cancelled = await state.get_state() is not None
    await state.clear()
    await open_screen("home", message, ctx, session, notice=ctx.t("common.cancelled") if cancelled else None)


@router.message(Command("help"), PrivateFilter())
async def on_help(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await open_screen("guide", message, ctx, session)


@router.message(Command("id"), PrivateFilter())
async def on_id(message: Message, ctx: Ctx) -> None:
    await toast(message, ctx.t("home.id", id=ctx.user_id))


@router.message(Command("admin"), PrivateFilter())
async def on_admin(message: Message, command: CommandObject, ctx: Ctx, session: AsyncSession) -> None:
    await _change_role(message, command, ctx, session, promoted=True)


@router.message(Command("deladmin"), PrivateFilter())
async def on_deladmin(message: Message, command: CommandObject, ctx: Ctx, session: AsyncSession) -> None:
    await _change_role(message, command, ctx, session, promoted=False)


async def _change_role(message: Message, command: CommandObject, ctx: Ctx, session: AsyncSession, *,
                       promoted: bool) -> None:
    """/admin and /deladmin (the owner of the network): the user must have started the network's bot."""
    try:
        if not ctx.is_owner or ctx.is_hub:
            raise AdminError("common.no_permission")
        parts = (command.args or "").split()
        if not parts:
            raise AdminError("adm.err.usage" if promoted else "adm.err.usage_del")
        target = await find_target(session, ctx, parts[0])
        if promoted:
            promote(ctx, target)
        else:
            demote(target)
    except AdminError as err:
        await show(message, ctx.t(err.key, **err.params))
        return
    reply = ctx.t("adm.ok.added" if promoted else "adm.ok.removed", user=user_label(target))
    if not await notify_role_change(ctx, session, target, promoted=promoted) and promoted:
        reply += f"\n{ctx.t('adm.note.no_dm')}"
    await show(message, reply, kb([btn(ctx.t("adm.btn.list"), MenuCB(screen="admins"))]))
