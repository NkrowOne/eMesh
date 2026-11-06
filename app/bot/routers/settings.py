"""⚙️ Settings: notifications, external chats (and the partners' pause rules), support contact, admins and language.

Everything about the network uses the workspace (``ctx.ws_rec``): a super admin may be managing a clone. Bot level
settings (external chats, support, admins) are changed by the owner only; the other admins see them. The owner can
also run the 🧭 setup wizard again (``setup``). Also hosts the admin role helpers used by ``/admin`` and
``/deladmin`` (start.py).
"""
from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.filters import PrivateFilter
from app.data.timezones import utc_offset_label
from app.db.models import Bot as BotRecord
from app.db.models import BotUser, Role, User
from app.i18n import LANG_NAMES, SUPPORTED_LANGS, t
from app.services import audience, content, freq
from app.services import users as users_svc
from app.services.notify import send_dm
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, choice_label, grid, kb, prompt, show, toast, toggle_label, visible_len
from app.ui.fmt import esc, num, onoff, truncate, user_link
from app.ui.screens import screen

router = Router(name="settings")

MIN_MEMBERS_MAX = 100_000_000
JOIN_TEXT_MAX = 1000  # visible characters of the welcome text of the partners
USER_TOGGLES = {"notify": "notify", "summary": "summary", "reports": "run_reports"}
ADMIN_TOGGLES = frozenset({"summary", "reports"})  # only admins get these
BOT_TOGGLES = {"open": "join_open", "approval": "join_approval", "pause": "partners_can_pause"}
PAUSE_MAX_CHOICES = (24, 72, 168, 0)  # ⏸ the longest pause of a partner, in hours (0 = until they resume it)


class SettingsFSM(StatesGroup):
    min_members = State()
    join_text = State()
    support = State()


class SsCB(CallbackData, prefix="ss"):
    """``tg`` toggles ``key``; ``min``, ``jt`` and ``sup`` ask for a value; ``jt_reset`` and ``sup_reset`` go back
    to the default; ``pmax`` sets the longest pause of the partners to ``key`` hours."""

    action: str
    key: str = ""


class AdCB(CallbackData, prefix="ad"):
    """Removes the admin ``user_id``."""

    user_id: int


class LgCB(CallbackData, prefix="lg"):
    lang: str


# ---------------------------------------------------------------------------------------------------
# Helpers shared with start.py
# ---------------------------------------------------------------------------------------------------
_SUPPORT_RE = re.compile(r"(?:@|(?:https?://)?(?:www\.)?(?:t|telegram)\.me/)?([A-Za-z]\w{3,31})/?")


def parse_support(text: str | None) -> str | None:
    """``@user`` / ``t.me/user`` / ``https://t.me/user`` -> ``user``; None when it is not a username."""
    match = _SUPPORT_RE.fullmatch((text or "").strip())
    return match.group(1) if match else None


async def support_username(session: AsyncSession, rec: BotRecord) -> str | None:
    """The 🛟 contact of a network: the one its owner chose, else the owner's own @username."""
    if rec.support_username:
        return rec.support_username
    owner = await session.get(User, rec.owner_id)
    return owner.username if owner is not None and owner.username else None


async def support_url(session: AsyncSession, rec: BotRecord) -> str | None:
    username = await support_username(session, rec)
    return f"https://t.me/{username}" if username else None


class AdminError(Exception):
    """An admin change was refused. ``key`` is the i18n key of the reason, ``params`` its placeholders."""

    def __init__(self, key: str, **params: str) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


def user_label(bu: BotUser) -> str:
    return user_link(bu.user_id, bu.user.full_name, bu.user.username)


async def find_target(session: AsyncSession, ctx: Ctx, query: str) -> BotUser:
    """The user of the network for ``@username`` / id. Users that never started its bot can't be found."""
    target = await users_svc.find_bot_user(session, ctx.ws_id, query)
    if target is None:
        raise AdminError("adm.err.not_found", bot=esc(ctx.ws_rec.username))
    return target


def promote(ctx: Ctx, target: BotUser) -> None:
    """Makes ``target`` an admin of the network (the caller checked ``ctx.is_owner``)."""
    if target.user_id == ctx.user_id:
        raise AdminError("adm.err.self")
    if target.user_id == ctx.ws_rec.owner_id or target.user_id in ctx.settings.super_admin_ids:
        raise AdminError("adm.err.owner")
    if target.is_banned:
        raise AdminError("adm.err.banned")
    if target.role == Role.ADMIN:
        raise AdminError("adm.err.already", user=user_label(target))
    target.role = Role.ADMIN


def demote(target: BotUser) -> None:
    if target.role != Role.ADMIN:
        raise AdminError("adm.err.not_admin", user=user_label(target))
    target.role = Role.USER


async def notify_role_change(ctx: Ctx, session: AsyncSession, target: BotUser, *, promoted: bool) -> bool:
    """Tells ``target`` (in their language, through the network's bot) about their new role. False when the
    message could not be sent."""
    bot = ctx.ws_bot()
    if bot is None:
        return False
    lang = target.lang
    text = t("adm.dm.promoted" if promoted else "adm.dm.demoted", lang, bot=esc(ctx.ws_rec.username))
    markup = kb([btn(t("common.home", lang), MenuCB(screen="home"))]) if promoted else None
    return await send_dm(bot, session, target.user_id, text, markup) is not None


# ---------------------------------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------------------------------
_THOUSANDS_RE = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+")
_INT_RE = re.compile(r"[0-9]{1,12}")


def parse_int(text: str | None, maximum: int) -> int | None:
    """A whole number 0..maximum ("1.500" and "1,500" mean 1500) or None when the text is not one."""
    raw = (text or "").strip()
    if _THOUSANDS_RE.fullmatch(raw):
        raw = re.sub(r"[.,\s]", "", raw)
    if not _INT_RE.fullmatch(raw):
        return None
    value = int(raw)
    return value if value <= maximum else None


def with_notice(text: str, notice: str | None) -> str:
    return f"{notice}\n\n{text}" if notice else text


def duration_text(ctx: Ctx, minutes: int) -> str:
    """``1 día``, ``3 días``, ``6 h``, ``1 h 30 min``."""
    days, rest = divmod(max(0, minutes), 1440)
    if days and not rest:
        return ctx.t("set.days.1" if days == 1 else "set.days", n=days)
    return freq.every_text(minutes, ctx.lang)


def pause_max_text(ctx: Ctx, hours: int) -> str:
    """The longest pause partners may choose: ``1 día``, ``12 h``… or ``Sin límite`` (0: until they resume it)."""
    return duration_text(ctx, hours * 60) if hours > 0 else ctx.t("set.ext.pmax.none")


async def _deny(event: Message | CallbackQuery, ctx: Ctx) -> None:
    await alert(event, ctx.t("common.no_permission"))


def _can_edit_network(ctx: Ctx) -> bool:
    """Bot level settings: the owner (or a super admin) of a bot that runs a network."""
    return ctx.is_owner and not ctx.is_hub


# ---------------------------------------------------------------------------------------------------
# ⚙️ Settings
# ---------------------------------------------------------------------------------------------------
def _tz_line(ctx: Ctx) -> str:
    return ctx.t("set.tz", tz=esc(ctx.tz), offset=utc_offset_label(ctx.tz))


def _lang_line(ctx: Ctx) -> str:
    return ctx.t("set.lang", lang=LANG_NAMES.get(ctx.lang, ctx.lang))


def _notif_line(ctx: Ctx) -> str:
    bu = ctx.bu
    notify, summary, reports = (bu.notify, bu.summary, bu.run_reports) if bu else (True, True, False)
    if ctx.is_admin:
        return ctx.t("set.notif.admin", a=onoff(notify), s=onoff(summary), r=onoff(reports))
    return ctx.t("set.notif.user", a=onoff(notify))


def externals_line(ctx: Ctx) -> str:
    ws = ctx.ws_rec
    if not ws.join_open:
        return ctx.t("set.line.ext_closed")
    return ctx.t("set.line.ext_approval" if ws.join_approval else "set.line.ext_auto")


@screen("settings")
async def settings_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, notice: str | None = None,
    **_: object,
) -> None:
    if ctx.is_hub:
        text, markup = _hub_settings(ctx)
    elif ctx.is_admin:
        text, markup = await _admin_settings(ctx, session)
    else:
        text, markup = _user_settings(ctx)
    await show(event, with_notice(text, notice), markup)


async def _admin_settings(ctx: Ctx, session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    ws = ctx.ws_rec
    contact = await support_username(session, ws)
    lines = [
        ctx.t("set.title"),
        _tz_line(ctx),
        _lang_line(ctx),
        ctx.t("set.admins", n=len(await users_svc.admin_ids(session, ws))),
        _notif_line(ctx),
        externals_line(ctx),
        ctx.t("set.support", user=f"@{esc(contact)}" if contact else "—"),
    ]
    rows: list[list[InlineKeyboardButton]] = [
        [btn(ctx.t("set.btn.tz"), MenuCB(screen="timezone")), btn(ctx.t("set.btn.lang"), MenuCB(screen="lang"))],
        [btn(ctx.t("set.btn.notif"), MenuCB(screen="notifications")),
         btn(ctx.t("set.btn.admins"), MenuCB(screen="admins"))],
    ]
    if ctx.is_owner:
        rows.append([btn(ctx.t("set.btn.externals"), MenuCB(screen="externals")),
                     btn(ctx.t("set.btn.support"), MenuCB(screen="support"))])
        if not ctx.in_ws:  # the wizard is the owner's, in the bot itself
            rows.append([btn(ctx.t("set.btn.setup"), MenuCB(screen="setup", arg=1))])
    else:
        lines += ["", ctx.t("set.owner_only")]
    rows.append(back_row(ctx.lang, "home"))
    return "\n".join(lines), kb(*rows)


def _user_settings(ctx: Ctx) -> tuple[str, InlineKeyboardMarkup]:
    lines = [ctx.t("set.title"), _tz_line(ctx), ctx.t("set.hint.user_tz"), _lang_line(ctx), _notif_line(ctx)]
    rows = [
        [btn(ctx.t("set.btn.tz"), MenuCB(screen="timezone")), btn(ctx.t("set.btn.lang"), MenuCB(screen="lang"))],
        [btn(ctx.t("set.btn.notif"), MenuCB(screen="notifications"))],
        back_row(ctx.lang, "home"),
    ]
    return "\n".join(lines), kb(*rows)


def _hub_settings(ctx: Ctx) -> tuple[str, InlineKeyboardMarkup]:
    """The main bot in hub mode runs no network: only the timezone and the language."""
    lines = [ctx.t("set.title"), _tz_line(ctx), _lang_line(ctx)]
    rows = [
        [btn(ctx.t("set.btn.tz"), MenuCB(screen="timezone")), btn(ctx.t("set.btn.lang"), MenuCB(screen="lang"))],
        back_row(ctx.lang, "home"),
    ]
    return "\n".join(lines), kb(*rows)


# ---------------------------------------------------------------------------------------------------
# 🔔 Mis avisos
# ---------------------------------------------------------------------------------------------------
@screen("notifications")
async def notifications_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, **_: object
) -> None:
    bu = ctx.bu
    if bu is None:
        await _deny(event, ctx)
        return
    lines = [ctx.t("set.nt.title"), "", ctx.t("set.nt.notify", v=onoff(bu.notify)),
             ctx.t("set.nt.hint.notify" if ctx.is_admin else "set.nt.hint.notify_user")]
    rows = [[btn(toggle_label(ctx.t("set.nt.btn.notify"), bu.notify), SsCB(action="tg", key="notify"))]]
    if ctx.is_admin:
        lines += [ctx.t("set.nt.summary", v=onoff(bu.summary)), ctx.t("set.nt.hint.summary"),
                  ctx.t("set.nt.reports", v=onoff(bu.run_reports)), ctx.t("set.nt.hint.reports")]
        rows += [[btn(toggle_label(ctx.t("set.nt.btn.summary"), bu.summary), SsCB(action="tg", key="summary"))],
                 [btn(toggle_label(ctx.t("set.nt.btn.reports"), bu.run_reports),
                      SsCB(action="tg", key="reports"))]]
    rows.append(back_row(ctx.lang, "settings"))
    await show(event, "\n".join(lines), kb(*rows))


@router.callback_query(SsCB.filter(F.action == "tg"))
async def on_toggle(
    call: CallbackQuery, callback_data: SsCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    key = callback_data.key
    if key in BOT_TOGGLES and _can_edit_network(ctx):
        await state.clear()
        attr = BOT_TOGGLES[key]
        setattr(ctx.ws_rec, attr, not getattr(ctx.ws_rec, attr))
        await externals_screen(call, ctx, session)
    elif key in USER_TOGGLES and ctx.bu is not None and (key not in ADMIN_TOGGLES or ctx.is_admin):
        await state.clear()
        attr = USER_TOGGLES[key]
        setattr(ctx.bu, attr, not getattr(ctx.bu, attr))
        await notifications_screen(call, ctx, session)
    else:
        await _deny(call, ctx)


# ---------------------------------------------------------------------------------------------------
# 🤝 Canales externos
# ---------------------------------------------------------------------------------------------------
def _join_link(ws: BotRecord) -> str:
    return f"https://t.me/{ws.username}?start=join"


@screen("externals")
async def externals_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, notice: str | None = None,
    **_: object,
) -> None:
    if not _can_edit_network(ctx):
        await _deny(event, ctx)
        return
    ws = ctx.ws_rec
    lines = [ctx.t("set.ext.title"), ctx.t("set.ext.intro"), "", ctx.t("set.ext.open", v=onoff(ws.join_open))]
    rows = [[btn(toggle_label(ctx.t("set.ext.btn.open"), ws.join_open), SsCB(action="tg", key="open"))]]
    if not ws.join_open:
        lines.append(ctx.t("set.ext.hint.closed"))
    else:
        open_groups = sum(1 for g in await audience.bot_groups(session, ws.id) if g.open)
        lines += [
            ctx.t("set.ext.approval", v=onoff(ws.join_approval)),
            ctx.t("set.ext.hint.approval_on" if ws.join_approval else "set.ext.hint.approval_off"),
            ctx.t("set.ext.min", n=num(ws.min_members)),
            ctx.t("set.ext.hint.min"),
            ctx.t("set.ext.text", v=ctx.t("set.ext.text.custom" if ws.join_text else "set.ext.text.default")),
            ctx.t("set.ext.hint.text"),
            ctx.t("set.ext.groups", n=open_groups),
            ctx.t("set.ext.hint.groups"),
            ctx.t("set.ext.pause", v=onoff(ws.partners_can_pause)),
        ]
        if ws.partners_can_pause:
            lines += [ctx.t("set.ext.pmax", v=pause_max_text(ctx, ws.pause_max_hours)), ctx.t("set.ext.hint.pmax")]
        else:
            lines.append(ctx.t("set.ext.hint.no_pause"))
        if ws.username:
            lines += ["", ctx.t("set.ext.link", link=esc(_join_link(ws))), ctx.t("set.ext.hint.link")]
        rows += [
            [btn(toggle_label(ctx.t("set.ext.btn.approval"), ws.join_approval),
                 SsCB(action="tg", key="approval"))],
            [btn(ctx.t("set.ext.btn.min", n=num(ws.min_members)), SsCB(action="min"))],
            [btn(ctx.t("set.ext.btn.text"), SsCB(action="jt"))],
            [btn(ctx.t("set.ext.btn.groups"), MenuCB(screen="groups"))],
            [btn(toggle_label(ctx.t("set.ext.btn.pause"), ws.partners_can_pause), SsCB(action="tg", key="pause"))],
        ]
        if ws.partners_can_pause:
            rows += grid([btn(choice_label(pause_max_text(ctx, hours), hours == ws.pause_max_hours),
                              SsCB(action="pmax", key=str(hours))) for hours in PAUSE_MAX_CHOICES], 2)
    rows.append(back_row(ctx.lang, "settings"))
    await show(event, with_notice("\n".join(lines), notice), kb(*rows))


@router.callback_query(SsCB.filter(F.action == "pmax"))
async def on_pause_max(
    call: CallbackQuery, callback_data: SsCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    """⏸ Pausa máxima of the partners (a rule changed later applies to new pauses)."""
    if not _can_edit_network(ctx):
        await _deny(call, ctx)
        return
    await state.clear()
    if callback_data.key in {str(hours) for hours in PAUSE_MAX_CHOICES}:  # a forged value changes nothing
        ctx.ws_rec.pause_max_hours = int(callback_data.key)
    await externals_screen(call, ctx, session)


# --- 🔢 minimum members -----------------------------------------------------------------------------
def _min_prompt(ctx: Ctx) -> str:
    return ctx.t("set.ext.min.prompt", n=num(ctx.ws_rec.min_members))


@router.callback_query(SsCB.filter(F.action == "min"))
async def on_min_start(call: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    if not _can_edit_network(ctx):
        await _deny(call, ctx)
        return
    await state.set_state(SettingsFSM.min_members)
    await prompt(call, ctx, _min_prompt(ctx), cancel_screen="externals")


@router.message(SettingsFSM.min_members, PrivateFilter(), ~F.text.startswith("/"))
async def on_min_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not _can_edit_network(ctx):
        await state.clear()
        await _deny(message, ctx)
        return
    value = parse_int(message.text, MIN_MEMBERS_MAX)
    if value is None:
        await prompt(message, ctx, f"{ctx.t('set.ext.min.invalid')}\n\n{_min_prompt(ctx)}",
                     cancel_screen="externals")
        return
    await state.clear()
    ctx.ws_rec.min_members = value
    await externals_screen(message, ctx, session, notice=ctx.t("common.saved"))


# --- 💬 welcome text of the partners ------------------------------------------------------------------
def join_text_default(ctx: Ctx) -> str:
    """The welcome text of the partners (it only promises pauses when the admins allow them)."""
    key = "home.join.default" if ctx.ws_rec.partners_can_pause else "home.join.default_no_pause"
    return ctx.t(key, bot=esc(ctx.ws_rec.username))


def _join_text_prompt(ctx: Ctx) -> str:
    custom = ctx.ws_rec.join_text
    current = esc(truncate(content.plain(custom).strip(), 300)) if custom else join_text_default(ctx)
    return "\n\n".join([ctx.t("set.ext.text.prompt", max=JOIN_TEXT_MAX), ctx.t("set.ext.text.current", text=current)])


def _join_text_extra(ctx: Ctx) -> list[list[InlineKeyboardButton]]:
    if not ctx.ws_rec.join_text:
        return []
    return [[btn(ctx.t("set.ext.text.reset"), SsCB(action="jt_reset"))]]


@router.callback_query(SsCB.filter(F.action == "jt"))
async def on_join_text_start(call: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    if not _can_edit_network(ctx):
        await _deny(call, ctx)
        return
    await state.set_state(SettingsFSM.join_text)
    await prompt(call, ctx, _join_text_prompt(ctx), cancel_screen="externals", extra_rows=_join_text_extra(ctx))


@router.message(SettingsFSM.join_text, PrivateFilter(), ~F.text.startswith("/"))
async def on_join_text_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not _can_edit_network(ctx):
        await state.clear()
        await _deny(message, ctx)
        return
    error: str | None = None
    text = ""
    if not (message.text and message.text.strip()):
        error = ctx.t("set.ext.text.invalid")
    else:
        text = message.html_text
        if visible_len(text) > JOIN_TEXT_MAX:
            error = ctx.t("common.too_long", max=JOIN_TEXT_MAX)
    if error is not None:
        await prompt(message, ctx, f"{error}\n\n{_join_text_prompt(ctx)}", cancel_screen="externals",
                     extra_rows=_join_text_extra(ctx))
        return
    await state.clear()
    ctx.ws_rec.join_text = text
    await externals_screen(message, ctx, session, notice=ctx.t("common.saved"))


@router.callback_query(SsCB.filter(F.action == "jt_reset"))
async def on_join_text_reset(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not _can_edit_network(ctx):
        await _deny(call, ctx)
        return
    await state.clear()
    ctx.ws_rec.join_text = None
    await externals_screen(call, ctx, session, notice=ctx.t("set.ext.text.reset_done"))


# ---------------------------------------------------------------------------------------------------
# 🛟 Soporte
# ---------------------------------------------------------------------------------------------------
@screen("support")
async def support_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, notice: str | None = None,
    **_: object,
) -> None:
    if not _can_edit_network(ctx):
        await _deny(event, ctx)
        return
    ws = ctx.ws_rec
    username = await support_username(session, ws)
    if ws.support_username:
        current = ctx.t("set.sup.custom", user=esc(username))
    elif username:
        current = ctx.t("set.sup.owner", user=esc(username))
    else:
        current = ctx.t("set.sup.none")
    rows = [[btn(ctx.t("set.sup.btn.change"), SsCB(action="sup"))]]
    if ws.support_username:
        mine = ctx.user_id == ws.owner_id
        rows.append([btn(ctx.t("set.sup.btn.mine" if mine else "set.sup.btn.owner"), SsCB(action="sup_reset"))])
    rows.append(back_row(ctx.lang, "settings"))
    text = "\n\n".join([ctx.t("set.sup.title"), ctx.t("set.sup.intro"), current])
    await show(event, with_notice(text, notice), kb(*rows))


@router.callback_query(SsCB.filter(F.action == "sup"))
async def on_support_edit(call: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    if not _can_edit_network(ctx):
        await _deny(call, ctx)
        return
    await state.set_state(SettingsFSM.support)
    await prompt(call, ctx, ctx.t("set.sup.prompt"), cancel_screen="support")


@router.message(SettingsFSM.support, PrivateFilter(), ~F.text.startswith("/"))
async def on_support_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not _can_edit_network(ctx):
        await state.clear()
        await _deny(message, ctx)
        return
    username = parse_support(message.text)
    if username is None:
        await prompt(message, ctx, f"{ctx.t('set.sup.invalid')}\n\n{ctx.t('set.sup.prompt')}",
                     cancel_screen="support")
        return
    await state.clear()
    ctx.ws_rec.support_username = username
    await support_screen(message, ctx, session, notice=ctx.t("common.saved"))


@router.callback_query(SsCB.filter(F.action == "sup_reset"))
async def on_support_reset(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not _can_edit_network(ctx):
        await _deny(call, ctx)
        return
    await state.clear()
    ctx.ws_rec.support_username = None
    await support_screen(call, ctx, session, notice=ctx.t("common.saved"))


# ---------------------------------------------------------------------------------------------------
# 👮 Admins
# ---------------------------------------------------------------------------------------------------
def _plain_name(bu: BotUser) -> str:
    return f"@{bu.user.username}" if bu.user.username else bu.user.full_name


@screen("admins")
async def admins_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, notice: str | None = None,
    **_: object,
) -> None:
    if not ctx.is_admin:
        await _deny(event, ctx)
        return
    ws = ctx.ws_rec
    owner = await session.get(User, ws.owner_id)
    owner_label = user_link(ws.owner_id, owner.full_name if owner else None, owner.username if owner else None)
    lines = [ctx.t("adm.title"), "", ctx.t("adm.owner", n=1, user=owner_label, id=ws.owner_id)]
    rows: list[list[InlineKeyboardButton]] = []
    for index, bu in enumerate(await users_svc.admins(session, ws), start=2):
        lines.append(ctx.t("adm.admin", n=index, user=user_label(bu), id=bu.user_id))
        if ctx.is_owner:
            label = ctx.t("adm.btn.remove", n=index, name=truncate(_plain_name(bu), 24))
            rows.append([btn(label, AdCB(user_id=bu.user_id), style="danger")])
    if ctx.is_owner:
        lines += ["", ctx.t("adm.hint"), ctx.t("adm.hint_started", bot=esc(ws.username))]
    rows.append(back_row(ctx.lang, "settings"))
    await show(event, with_notice("\n".join(lines), notice), kb(*rows))


@router.callback_query(AdCB.filter())
async def on_admin_remove(
    call: CallbackQuery, callback_data: AdCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    if not ctx.is_owner:
        await _deny(call, ctx)
        return
    await state.clear()
    target = await session.get(BotUser, (ctx.ws_id, callback_data.user_id))
    if target is None or target.role != Role.ADMIN:  # already removed (an old button)
        await admins_screen(call, ctx, session)
        return
    demote(target)
    await notify_role_change(ctx, session, target, promoted=False)
    await admins_screen(call, ctx, session, notice=ctx.t("adm.ok.removed", user=user_label(target)))


# ---------------------------------------------------------------------------------------------------
# 🌍 Language
# ---------------------------------------------------------------------------------------------------
@screen("lang")
async def lang_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                      **_: object) -> None:
    rows = [[btn(f"{'✅ ' if code == ctx.lang else ''}{LANG_NAMES[code]}", LgCB(lang=code))]
            for code in SUPPORTED_LANGS]
    rows.append(back_row(ctx.lang, "settings"))
    await show(event, f"{ctx.t('lang.title')}\n\n{ctx.t('lang.body')}", kb(*rows))


@router.callback_query(LgCB.filter())
async def on_lang(call: CallbackQuery, callback_data: LgCB, ctx: Ctx, session: AsyncSession,
                  state: FSMContext) -> None:
    if callback_data.lang not in SUPPORTED_LANGS or ctx.bu is None:
        await lang_screen(call, ctx, session)
        return
    await state.clear()
    ctx.bu.lang = callback_data.lang
    ctx.lang = callback_data.lang
    await toast(call, ctx.t("lang.changed"))
    await settings_screen(call, ctx, session)
