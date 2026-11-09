"""🏠 Home, 📖 guide and the basic commands: /start (+ deep links), /cancel, /id, /help, /admin and /deladmin.

The home has three views: the network of the admins (with its summary and ⏸ Pausar todo), the partners and visitors
(how to join, their chats, support; the main bot welcomes them to eMesh and offers 🤖 Crear mi bot first) and the main
bot in hub mode (what eMesh is, create your bot). The owner of a new clone goes first through the timezone (or the one
they already chose somewhere) and the 🧭 setup wizard; a user is asked their timezone on the first visit, unless they
already chose one somewhere.
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
from sqlalchemy import and_, func, or_, select
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
from app.bot.routers.setup import needs_setup
from app.bot.routers.timezone import ASK_HOME as TZ_ASK_HOME
from app.bot.routers.timezone import ASK_JOIN as TZ_ASK_JOIN
from app.bot.routers.timezone import adopt_known_zone, must_choose_timezone, needs_timezone
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import Chat, ChatOrigin, ChatStatus, EventKind
from app.services import clones, events, freq, limits, stats
from app.services.chatinfo import add_to_channel_url, add_to_group_url
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, kb, nav_row, show, toast, ws_banner
from app.ui.fmt import dt, esc, num
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
    if needs_timezone(ctx):  # a new clone: its owner's timezone first (one they already chose, or the question)
        zone = await adopt_known_zone(session, ctx)
        if zone is None:
            await open_screen("timezone", event, ctx, session)
            return
        notice = with_notice(_known_zone_notice(ctx, zone), notice)
    if await must_choose_timezone(session, ctx):  # a user's first visit: dates and times in their local time
        await open_screen("timezone", event, ctx, session, arg=TZ_ASK_HOME)
        return
    if needs_setup(ctx):  # then the setup wizard, until it is finished or skipped
        await open_screen("setup", event, ctx, session, arg=1, notice=notice)
        return
    if ctx.is_hub:
        text, markup = await _hub_home(ctx, session)
    elif ctx.is_admin:
        text, markup = await _admin_home(ctx, session)
    else:
        await _partner_home(event, ctx, session, notice)
        return
    await show(event, with_notice(text, notice), markup)


def _known_zone_notice(ctx: Ctx, zone: str) -> str:
    """A new clone took the zone its owner already chose somewhere; the welcome too when the setup wizard follows."""
    known = ctx.t("tz.saved.known", zone=esc(zone))
    return f"{ctx.t('tz.welcome')}\n{known}" if needs_setup(ctx) else known


def _next_turn(ws: BotRecord, tz: str, now: datetime) -> datetime | None:
    """Next slot of the global frequency (the stored one, unless it already passed)."""
    if ws.rot_next_at is not None and ws.rot_next_at > now:
        return ws.rot_next_at
    return freq.next_slot(ws.freq, tz, now)


async def _paused_chats(session: AsyncSession, bot_id: int, now: datetime) -> int:
    """Approved chats paused right now, by their owner or by an admin (a chat paused by both counts once)."""
    owner_pause = and_(Chat.owner_paused, or_(Chat.owner_paused_until.is_(None), Chat.owner_paused_until > now))
    q = select(func.count()).select_from(Chat).where(
        Chat.bot_id == bot_id, Chat.status == ChatStatus.APPROVED, or_(Chat.admin_paused, owner_pause))
    return int((await session.execute(q)).scalar() or 0)


def _status_line(ctx: Ctx, sendable: int, paused: int, no_rights: int, pending: int) -> str:
    """«📊 Estado: ✅ 10 reciben · ⏸ 2 pausados · ⚠️ 1 sin permisos · ⏳ 1 pendiente»."""
    parts = [ctx.t(f"{key}.1" if n == 1 else key, n=num(n)) for key, n in (
        ("home.st.ok", sendable), ("home.st.paused", paused), ("home.st.no_rights", no_rights),
        ("home.st.pending", pending))]
    return ctx.t("home.status", parts=" · ".join(parts))


async def _admin_home(ctx: Ctx, session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    ws = ctx.ws_rec
    now = utcnow()
    s = await stats.summary(session, ws.id, now=now)
    paused = await _paused_chats(session, ws.id, now)
    lines = [ctx.t("home.admin.title"), ""]
    if s.chats:
        lines += [ctx.t("home.chats", n=num(s.chats), members=num(s.members)),
                  ctx.t("home.chats.split", own=num(s.own), ext=num(s.external))]
    else:
        lines.append(ctx.t("home.chats.none"))
    if s.chats or s.pending:  # admins always see how many chats receive posts and why the others don't
        lines.append(_status_line(ctx, s.sendable, paused, s.no_rights, s.pending))
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
        # ➕ first: a network starts by adding the bot to channels and groups (both links are in its submenu).
        [btn(ctx.t("home.btn.add_chat"), MenuCB(screen="add_chat"), style="success")] if ws.username else None,
        [btn(ctx.t("home.btn.posts"), MenuCB(screen="posts")), btn(ctx.t("home.btn.chats"), MenuCB(screen="chats"))],
        [btn(ctx.t("home.btn.groups"), MenuCB(screen="groups")),
         btn(ctx.t("home.btn.freqs"), MenuCB(screen="freqs"))],
        [btn(ctx.t("home.btn.stats"), MenuCB(screen="stats")),
         btn(ctx.t("home.btn.activity"), MenuCB(screen="activity"))],
        [btn(ctx.t("home.btn.requests", n=s.pending), MenuCB(screen="requests")) if s.pending else None,
         # ⏸ Pausados even with 0 when partners can join: the admins always see every pause.
         btn(ctx.t("home.btn.paused", n=paused), MenuCB(screen="paused"))
         if ws.join_open or s.external or paused else None],
    ]
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


@screen("add_chat")
async def add_chat_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, **_: object
) -> None:
    """➕ Añadir canal o grupo (admins): how to add the network's bot to a channel or a group, with both links."""
    if not ctx.is_admin or ctx.is_hub:
        await alert(event, ctx.t("common.no_permission"))
        return
    username = ctx.ws_rec.username  # a super admin managing a clone adds the clone's bot
    await show(event, ctx.t("home.add.text"), kb(
        [btn(ctx.t("home.btn.add_channel"), url=add_to_channel_url(username)),
         btn(ctx.t("home.btn.add_group"), url=add_to_group_url(username))] if username else None,
        [btn(ctx.t("home.add.btn.chats"), MenuCB(screen="chats"))],
        back_row(ctx.lang, "home"),
    ))


async def _my_chats(session: AsyncSession, bot_id: int, user_id: int) -> int:
    """External chats of the user in the network (any status but left)."""
    q = select(func.count()).select_from(Chat).where(
        Chat.bot_id == bot_id, Chat.owner_user_id == user_id, Chat.origin == ChatOrigin.EXTERNAL,
        Chat.status != ChatStatus.LEFT)
    return int((await session.execute(q)).scalar() or 0)


async def _clones_open(ctx: Ctx, session: AsyncSession) -> bool:
    """The platform accepts new bots (its clone policy isn't ``closed``)."""
    return (await limits.platform(session, ctx.settings)).clone_policy != "closed"


async def _create_own_button(ctx: Ctx, session: AsyncSession) -> InlineKeyboardButton | None:
    """🤖 Crea tu propio bot in a clone: a link to the main bot (none when the platform doesn't accept new bots)."""
    if not await _clones_open(ctx, session):
        return None
    main = await clones.main_username(session, ctx.settings)
    return btn(ctx.t("home.btn.create_own"), url=f"https://t.me/{main}?start=clone") if main else None


def _first_name(ctx: Ctx) -> str:
    user = ctx.user
    return esc(user.first_name or user.full_name) if user is not None else ""


def _partner_text(ctx: Ctx, *, platform: bool, custom: str | None) -> str:
    ws = ctx.ws_rec
    parts = [ctx.t("home.welcome", name=_first_name(ctx))] if platform else []
    if ws.join_open:
        block = [custom or join_text_default(ctx)]
        if ws.min_members:
            block.append(ctx.t("home.join.min", n=num(ws.min_members)))
        if ws.join_approval:
            block.append(ctx.t("home.join.approval"))
        parts.append("\n\n".join(block))
    elif not platform:  # the main bot's visitors come to create their own bot, not to join its network
        parts.append(ctx.t("home.private"))
    return "\n\n".join(parts)


async def _partner_home(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, notice: str | None) -> None:
    ws = ctx.ws_rec
    # The platform's own bot welcomes its visitors to eMesh: publishing needs their own bot, so 🤖 Crear mi bot comes
    # first (unless the platform doesn't accept new bots).
    platform = ctx.is_main and await _clones_open(ctx, session)
    bots = await clones.count_user_bots(session, ctx.user_id) if ctx.is_main else 0
    mybots = btn(ctx.t("home.btn.mybots", n=bots), MenuCB(screen="mybots")) if bots else None
    rows: list[list[InlineKeyboardButton | None]] = []
    if platform:
        rows += [[btn(ctx.t("home.btn.create_mine"), MenuCB(screen="clone"), style="success")], [mybots]]
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
    if not platform:
        rows.append([None if ctx.is_main else await _create_own_button(ctx, session), mybots])
    markup = kb(*rows)
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
    if needs_timezone(ctx):  # a new clone: its owner goes through the timezone first, whatever the link
        name, arg = "home", 0
    elif name == "join" and await must_choose_timezone(session, ctx):  # a user's first visit
        name, arg = "timezone", TZ_ASK_JOIN
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
