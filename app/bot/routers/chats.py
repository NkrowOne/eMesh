"""📣 Canales y grupos (admins): the list with filters, a chat's detail and its actions (groups of chats, check,
pause, resume — a partner's pause too —, remove, ban), ⏸ Pausados, 📥 import and 📢 a message to the partners."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.config import Settings
from app.db.base import utcnow
from app.db.models import Chat, ChatGroup, ChatStatus, Post, User
from app.db.session import SessionMaker
from app.i18n import t
from app.services import audience, blast, chatstate, content, stats
from app.services import chats as chat_svc
from app.services import freq as freq_svc
from app.services.chatinfo import add_to_channel_url, add_to_group_url
from app.services.chats import SRC_CHAT, RqCB
from app.services.notify import send_dm
from app.services.publisher import Publisher
from app.telegram.context import set_low_priority
from app.telegram.errors import is_user_blocked, short
from app.ui.callbacks import MenuCB
from app.ui.common import (
    alert,
    back_row,
    btn,
    cancel_row,
    grid,
    kb,
    nav_row,
    paginate,
    prompt,
    show,
    toast,
    toggle_label,
)
from app.ui.fmt import dt, esc, num, truncate
from app.ui.screens import open_screen, screen

log = logging.getLogger(__name__)

router = Router(name="chats")

PER_PAGE = 10
MAX_GROUP_BUTTONS = 90
# Groups of chats named in a row of the list (cut to ROW_GROUP_WIDTH characters) and in a chat's detail; "+N" the rest.
ROW_GROUPS, ROW_GROUP_WIDTH, DETAIL_GROUPS = 2, 24, 10
IMPORT_MAX = 30
FILTER_ALL, FILTER_OWN, FILTER_EXT, FILTER_PAUSED, FILTER_RIGHTS = range(5)
FILTERS = (
    (FILTER_ALL, "ch.filter.all"),
    (FILTER_OWN, "ch.filter.own"),
    (FILTER_EXT, "ch.filter.ext"),
    (FILTER_PAUSED, "ch.filter.paused"),
    (FILTER_RIGHTS, "ch.filter.rights"),
)


class ChatsFSM(StatesGroup):
    reason = State()  # ⏳ requests: why a request is rejected
    refs = State()  # 📥 import: @usernames / ids
    blast = State()  # 📢 the message for the partners


class ChCB(CallbackData, prefix="ch"):
    a: str
    id: int = 0  # chat pk
    f: int = 0  # list filter
    p: int = 0  # list page
    v: int = 0  # value (group id)


def fsm_of(event: Message | CallbackQuery, ctx: Ctx) -> FSMContext | None:
    """The FSM of the user's private chat: a screen opened with ``MenuCB`` gets no ``state``."""
    if ctx.manager is None or event.bot is None:
        return None
    if isinstance(event, Message):
        chat_id = event.chat.id
    else:
        chat_id = event.message.chat.id if event.message is not None else event.from_user.id
    return ctx.manager.dp.fsm.resolve_context(bot=event.bot, chat_id=chat_id, user_id=ctx.user_id)


def add_row(ctx: Ctx) -> list[InlineKeyboardButton]:
    """``[➕ Añadir canal ↗][➕ Añadir grupo ↗]`` of the network's bot (Telegram's add-as-admin dialogs)."""
    username = ctx.ws_rec.username
    if not username:
        return []
    return [btn(ctx.t("ch.btn.add_channel"), url=add_to_channel_url(username)),
            btn(ctx.t("ch.btn.add_group"), url=add_to_group_url(username))]


async def _admin_chat(call: CallbackQuery, ctx: Ctx, session: AsyncSession, pk: int) -> Chat | None:
    """The chat of an admin button (admins only, rows of the workspace only), or None after an alert."""
    if not ctx.is_admin:
        await alert(call, ctx.t("common.no_permission"))
        return None
    chat = await session.get(Chat, pk)
    if chat is None or chat.bot_id != ctx.ws_id:
        await alert(call, ctx.t("common.not_found"))
        return None
    return chat


async def _wrong_status(call: CallbackQuery, ctx: Ctx, chat: Chat) -> None:
    await alert(call, ctx.t("ch.toast.wrong_status", status=chat_svc.status_text(chat, ctx.lang, ctx.tz)))


async def _ws_bot(call: CallbackQuery, ctx: Ctx) -> Bot | None:
    bot = ctx.ws_bot()
    if bot is None:
        await alert(call, ctx.t("common.not_running"))
    return bot


# --------------------------------------------------------------------------- list
def _matches(chat: Chat, flt: int) -> bool:
    if flt == FILTER_OWN:
        return not chat.is_external
    if flt == FILTER_EXT:
        return chat.is_external
    if flt == FILTER_PAUSED:
        return chat.is_paused()
    if flt == FILTER_RIGHTS:
        return not chat.rights_ok
    return True


def _row_details(ctx: Ctx, chat: Chat, owners: dict[int, User], names: list[str]) -> str:
    parts = [ctx.t("ch.list.members", n=num(chat.members))]
    if chat.is_external:
        parts.append(f"🤝 {chat_svc.owner_html(chat, owners)}".rstrip())
    else:
        parts.append("🏠")
    if names:
        parts.append("🗂 " + chat_svc.names_text(names, ROW_GROUPS, ROW_GROUP_WIDTH))
    if chat.owner_pause_active():
        parts.append(ctx.t("ch.list.until", date=dt(chat.owner_paused_until, ctx.tz)) if chat.owner_paused_until
                     else ctx.t("ch.list.until_resumed"))
    if chat.admin_paused:
        parts.append(ctx.t("ch.list.admin_paused"))
    return " · ".join(parts)


async def render_list(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, flt: int = FILTER_ALL,
                      page: int = 0) -> None:
    if not ctx.is_admin:
        await show(event, ctx.t("common.no_permission"), kb(back_row(ctx.lang)))
        return
    flt = flt if 0 <= flt < len(FILTERS) else FILTER_ALL
    chats = await chat_svc.listed_chats(session, ctx.ws_id)
    shown = [c for c in chats if _matches(c, flt)]
    items, page, pages = paginate(shown, page, PER_PAGE)
    channels = sum(1 for c in chats if c.is_channel)
    external = sum(1 for c in chats if c.is_external)
    lines = [
        ctx.t("ch.list.title"),
        ctx.t("ch.list.totals", channels=num(channels), groups=num(len(chats) - channels),
              members=num(sum(c.members or 0 for c in chats))),
        ctx.t("ch.list.origins", own=num(len(chats) - external), ext=num(external)),
        "",
    ]
    groups = {g.id: g.name for g in await audience.bot_groups(session, ctx.ws_id)}
    members = await audience.memberships(session, ctx.ws_id)
    owners = await chat_svc.users_by_id(session, {c.owner_user_id for c in items if c.is_external})
    buttons: list[InlineKeyboardButton] = []
    for i, chat in enumerate(items, start=page * PER_PAGE + 1):
        icon = chat_svc.chat_icon(chat)
        names = [groups[g] for g in sorted(members.get(chat.id, set())) if g in groups]
        lines.append(ctx.t("ch.list.row", n=i, icon=icon, chat=chat_svc.chat_name(chat, 48),
                           status=chat_svc.status_icon(chat), details=_row_details(ctx, chat, owners, names)))
        buttons.append(btn(f"#{i} {icon} {truncate(chat.display_title, 24)}", ChCB(a="op", id=chat.id, f=flt, p=page)))
    if not shown:
        lines.append(ctx.t("ch.list.empty_filter" if chats else "ch.list.empty"))
    else:
        lines += ["", ctx.t("ch.list.legend")]
    if pages > 1:
        lines += ["", ctx.t("common.page", page=page + 1, pages=pages)]

    pending = sum(1 for c in chats if c.status == ChatStatus.PENDING)
    has_partners = any(c.is_external and c.owner_user_id for c in chats)
    filters_row = [btn(ctx.t(key), ChCB(a="ls", f=value), style="primary" if value == flt else None)
                   for value, key in FILTERS]
    markup = kb(
        *grid(buttons, 2),
        filters_row,
        add_row(ctx),
        [btn(ctx.t("ch.btn.import"), MenuCB(screen="import")),
         btn(ctx.t("ch.btn.partners_msg"), MenuCB(screen="partners_msg")) if has_partners else None],
        [btn(ctx.t("ch.btn.requests", n=num(pending)), MenuCB(screen="requests"))] if pending else None,
        nav_row(page, pages, lambda p: ChCB(a="ls", f=flt, p=p), ctx.lang),
        back_row(ctx.lang),
    )
    await show(event, "\n".join(lines), markup)


@screen("chats")
async def chats_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                       **_: object) -> None:
    await render_list(event, ctx, session, page=arg)


@router.callback_query(ChCB.filter(F.a == "ls"))
async def on_list(call: CallbackQuery, callback_data: ChCB, ctx: Ctx, session: AsyncSession,
                  state: FSMContext) -> None:
    await state.clear()
    await render_list(call, ctx, session, callback_data.f, callback_data.p)


# --------------------------------------------------------------------------- detail
async def detail_text(ctx: Ctx, session: AsyncSession, chat: Chat) -> str:
    lines = [f"{chat_svc.chat_icon(chat)} <b>{esc(chat.display_title)}</b>", ctx.t("ch.d.id", id=chat.chat_id)]
    if chat.public_link:
        lines.append(ctx.t("ch.d.link", link=esc(chat.public_link)))
    lines.append(ctx.t("ch.d.members", n=num(chat.members)))
    if chat.is_external:
        owners = await chat_svc.users_by_id(session, {chat.owner_user_id})
        lines.append(ctx.t("ch.d.origin_ext", owner=chat_svc.owner_html(chat, owners) or ctx.t("common.unknown")))
    else:
        lines.append(ctx.t("ch.d.origin_own"))
    lines.append(ctx.t("ch.d.status", status=chat_svc.status_text(chat, ctx.lang, ctx.tz)))
    if chat.status in (ChatStatus.REJECTED, ChatStatus.BANNED) and chat.reject_reason:
        lines.append(ctx.t("ch.d.reason", reason=esc(chat.reject_reason)))
    if chat.status == ChatStatus.APPROVED and chat.owner_pause_active():
        lines.append(ctx.t("ch.d.owner_pause_hint"))
    groups = await audience.bot_groups(session, ctx.ws_id)
    member = await audience.chat_group_ids(session, chat.id)
    names = [g.name for g in groups if g.id in member]
    lines.append(ctx.t("ch.d.groups", names=chat_svc.names_text(names, DETAIL_GROUPS) or "—"))
    source = audience.source_of(member, {g.id: g for g in groups})
    if source is not None:
        lines.append(ctx.t("ch.d.freq_group", freq=freq_svc.describe(source.freq, ctx.lang), group=esc(source.name)))
    else:
        lines.append(ctx.t("ch.d.freq_global", freq=freq_svc.describe(ctx.ws_rec.freq, ctx.lang)))
    week = await stats.chat_received(session, chat.id, days=7)
    lines.append(ctx.t("ch.d.received", total=num(chat.posts_total), week=num(week)))
    lines.append(ctx.t("ch.d.last", date=dt(chat.last_post_at, ctx.tz)))
    return "\n".join(lines)


def detail_markup(ctx: Ctx, chat: Chat, f: int = 0, p: int = 0) -> InlineKeyboardMarkup:
    def cb(action: str) -> ChCB:
        return ChCB(a=action, id=chat.id, f=f, p=p)

    rows: list[list[InlineKeyboardButton | None]] = []
    if chat.status in chat_svc.ACTIVE:
        rows.append([btn(ctx.t("ch.btn.groups"), cb("gr")), btn(ctx.t("ch.btn.check"), cb("up"))])
        if chat.status == ChatStatus.PENDING:
            rows.append([btn(ctx.t("ch.btn.accept"), RqCB(a="ok", pk=chat.id, s=SRC_CHAT), style="success"),
                         btn(ctx.t("ch.btn.reject"), RqCB(a="no", pk=chat.id, s=SRC_CHAT), style="danger")])
        else:
            if chat.owner_pause_active():  # the admins rule: a partner's pause can be lifted (asks first)
                rows.append([btn(ctx.t("ch.btn.resume_owner"), cb("rs"), style="success")])
            elif chat.admin_paused:
                rows.append([btn(ctx.t("ch.btn.resume"), cb("rs"), style="success")])
            if not chat.admin_paused:
                rows.append([btn(ctx.t("ch.btn.pause"), cb("pz"))])
        rows.append([btn(ctx.t("ch.btn.remove"), cb("rm"), style="danger"),
                     btn(ctx.t("ch.btn.ban"), cb("bn"), style="danger")])
    elif chat.status == ChatStatus.BANNED:
        rows.append([btn(ctx.t("ch.btn.unban"), cb("ub"))])
    else:
        rows.append([btn(ctx.t("ch.btn.ban"), cb("bn"), style="danger")])
    if chat.public_link:
        rows.append([btn(ctx.t("ch.btn.open"), url=chat.public_link)])
    rows.append([btn(ctx.t("common.back"), ChCB(a="ls", f=f, p=p))])
    return kb(*rows)


async def render_detail(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, chat: Chat, f: int = 0,
                        p: int = 0, notice: str | None = None) -> None:
    text = await detail_text(ctx, session, chat)
    if notice:
        text = f"{notice}\n\n{text}"
    await show(event, text, detail_markup(ctx, chat, f, p))


@screen("chat")
async def chat_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                      **_: object) -> None:
    chat = await session.get(Chat, arg)
    if chat is None or chat.bot_id != ctx.ws_id:
        await show(event, ctx.t("common.not_found"), kb(back_row(ctx.lang, "chats" if ctx.is_admin else "home")))
        return
    if not ctx.is_admin:
        # A partner's link to their chat opens their own panel.
        if chat.is_external and chat.owner_user_id == ctx.user_id:
            await open_screen("my_chat", event, ctx, session, arg=chat.id)
        else:
            await show(event, ctx.t("common.no_permission"), kb(back_row(ctx.lang)))
        return
    await render_detail(event, ctx, session, chat)


@router.callback_query(ChCB.filter(F.a == "op"))
async def on_open(call: CallbackQuery, callback_data: ChCB, ctx: Ctx, session: AsyncSession,
                  state: FSMContext) -> None:
    await state.clear()
    chat = await _admin_chat(call, ctx, session, callback_data.id)
    if chat is not None:
        await render_detail(call, ctx, session, chat, callback_data.f, callback_data.p)


# --------------------------------------------------------------------------- groups of a chat
async def render_groups(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, chat: Chat, f: int = 0,
                        p: int = 0) -> None:
    groups = await audience.bot_groups(session, ctx.ws_id)
    member = await audience.chat_group_ids(session, chat.id)
    lines = [ctx.t("ch.groups.title", chat=esc(chat.display_title)), ""]
    lines.append(ctx.t("ch.groups.hint") if groups else ctx.t("ch.groups.empty"))
    buttons = [btn(toggle_label(f"🗂 {truncate(g.name, 40)}{' 🤝' if g.open else ''}", g.id in member),
                   ChCB(a="gt", id=chat.id, f=f, p=p, v=g.id)) for g in groups[:MAX_GROUP_BUTTONS]]
    if any(g.open for g in groups):
        lines.append(ctx.t("ch.groups.legend"))
    markup = kb(
        *grid(buttons, 2),
        [btn(ctx.t("ch.btn.all_groups"), MenuCB(screen="groups"))] if not groups else None,
        [btn(ctx.t("common.back"), ChCB(a="op", id=chat.id, f=f, p=p))],
    )
    await show(event, "\n".join(lines), markup)


@screen("chat_groups")
async def chat_groups_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                             **_: object) -> None:
    chat = await session.get(Chat, arg)
    if not ctx.is_admin or chat is None or chat.bot_id != ctx.ws_id:
        await show(event, ctx.t("common.not_found"), kb(back_row(ctx.lang)))
        return
    await render_groups(event, ctx, session, chat)


@router.callback_query(ChCB.filter(F.a == "gr"))
async def on_groups(call: CallbackQuery, callback_data: ChCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _admin_chat(call, ctx, session, callback_data.id)
    if chat is not None:
        await render_groups(call, ctx, session, chat, callback_data.f, callback_data.p)


@router.callback_query(ChCB.filter(F.a == "gt"))
async def on_group_toggle(call: CallbackQuery, callback_data: ChCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _admin_chat(call, ctx, session, callback_data.id)
    if chat is None:
        return
    group = await session.get(ChatGroup, callback_data.v)
    if group is None or group.bot_id != ctx.ws_id:
        await alert(call, ctx.t("common.not_found"))
        return
    on = group.id not in await audience.chat_group_ids(session, chat.id)
    await audience.set_member(session, group.id, chat.id, on)
    await toast(call, ctx.t("ch.toast.group_on" if on else "ch.toast.group_off", group=esc(truncate(group.name, 40))))
    await render_groups(call, ctx, session, chat, callback_data.f, callback_data.p)


# --------------------------------------------------------------------------- 🔄 Comprobar
def _check_notice(ctx: Ctx, res: chatstate.RefreshResult, chat: Chat) -> str:
    lines = [ctx.t("ch.check.title")]
    if res.gone:
        lines.append(ctx.t("ch.check.gone"))
        return "\n".join(lines)
    if res.members_before != res.members_after:
        lines.append(ctx.t("ch.check.members", before=num(res.members_before), after=num(res.members_after)))
    else:
        lines.append(ctx.t("ch.check.members_same", n=num(res.members_after)))
    if chat.rights_ok:
        lines.append(ctx.t("ch.check.rights_ok"))
    else:
        missing = chat_svc.missing_list(chat) or ["admin"]
        lines.append(ctx.t("ch.check.rights_missing", rights=chatstate.rights_text(missing, ctx.lang)))
    if res.error:
        lines.append(ctx.t("ch.check.error"))
    return "\n".join(lines)


@router.callback_query(ChCB.filter(F.a == "up"))
async def on_check(call: CallbackQuery, callback_data: ChCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _admin_chat(call, ctx, session, callback_data.id)
    if chat is None:
        return
    if chat.status not in chat_svc.ACTIVE:
        await _wrong_status(call, ctx, chat)
        return
    bot = await _ws_bot(call, ctx)
    if bot is None:
        return
    async with chat_svc.chat_lock(bot.id, chat.chat_id):
        await session.refresh(chat)
        was_ok = chat.rights_ok
        res = await chatstate.refresh(bot, session, ctx.ws_rec, chat)
        if not res.gone and chat.status == ChatStatus.PENDING and chat.rights_ok and not was_ok:
            await chat_svc.admit(bot, session, ctx.ws_rec, chat)  # it was waiting for these rights
        await session.commit()
    await toast(call, ctx.t("ch.toast.checked"))
    await render_detail(call, ctx, session, chat, callback_data.f, callback_data.p,
                        notice=_check_notice(ctx, res, chat))


# --------------------------------------------------------------------------- ⏸ admin pause
@router.callback_query(ChCB.filter(F.a == "pz"))
async def on_pause(call: CallbackQuery, callback_data: ChCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _admin_chat(call, ctx, session, callback_data.id)
    if chat is None:
        return
    if chat.status != ChatStatus.APPROVED or chat.admin_paused:
        await _wrong_status(call, ctx, chat)
        return
    bot = await _ws_bot(call, ctx)
    if bot is None:
        return
    await chat_svc.pause_by_admin(bot, session, ctx.ws_rec, chat, ctx.user_id)
    await toast(call, ctx.t("ch.toast.paused"))
    await render_detail(call, ctx, session, chat, callback_data.f, callback_data.p)


# ▶️ resume: ``rs`` / ``rsy`` (confirmed) from a chat's detail, ``pr`` / ``pry`` from ⏸ Pausados (p: its page).
RESUME_ACTIONS = {"rs": (False, False), "rsy": (False, True), "pr": (True, False), "pry": (True, True)}


def _owner_until(ctx: Ctx, chat: Chat) -> str:
    return (ctx.t("ch.paused.until", date=dt(chat.owner_paused_until, ctx.tz)) if chat.owner_paused_until
            else ctx.t("ch.paused.until_open"))


@router.callback_query(ChCB.filter(F.a.in_(set(RESUME_ACTIONS))))
async def on_resume(call: CallbackQuery, callback_data: ChCB, ctx: Ctx, session: AsyncSession) -> None:
    """The admins rule over the partners: resuming lifts an admin's pause and the partner's own (that one after a
    confirmation; the partner is told)."""
    chat = await _admin_chat(call, ctx, session, callback_data.id)
    if chat is None:
        return
    from_list, confirmed = RESUME_ACTIONS[callback_data.a]
    f, p = callback_data.f, callback_data.p

    async def back() -> None:
        if from_list:
            await render_paused(call, ctx, session, p)
        else:
            await render_detail(call, ctx, session, chat, f, p)

    if not chat.is_paused():
        await alert(call, ctx.t("ch.toast.not_paused"))
        await back()
        return
    if chat.owner_pause_active() and not confirmed:
        yes = ChCB(a="pry" if from_list else "rsy", id=chat.id, f=f, p=p)
        no = MenuCB(screen="paused", arg=p) if from_list else ChCB(a="op", id=chat.id, f=f, p=p)
        markup = kb([btn(ctx.t("ch.resume.yes"), yes, style="success"), btn(ctx.t("ch.confirm.no"), no)])
        await show(call, ctx.t("ch.resume.confirm", kind=chatstate.kind_word(chat, ctx.lang),
                               chat=esc(chat.display_title), until=_owner_until(ctx, chat)), markup)
        return
    bot = await _ws_bot(call, ctx)
    if bot is None:
        return
    await chat_svc.resume_by_admin(bot, session, ctx.ws_rec, chat, ctx.user_id)
    await toast(call, ctx.t("ch.toast.resumed"))
    await back()


# --------------------------------------------------------------------------- 🗑 remove / 🚫 ban
def _can_remove(chat: Chat, ban: bool) -> bool:
    return chat.status != ChatStatus.BANNED if ban else chat.status in chat_svc.ACTIVE


@router.callback_query(ChCB.filter(F.a.in_({"rm", "bn"})))
async def on_remove_ask(call: CallbackQuery, callback_data: ChCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _admin_chat(call, ctx, session, callback_data.id)
    if chat is None:
        return
    ban = callback_data.a == "bn"
    if not _can_remove(chat, ban):
        await _wrong_status(call, ctx, chat)
        return
    f, p = callback_data.f, callback_data.p
    kw = {"kind": chatstate.kind_word(chat, ctx.lang), "chat": esc(chat.display_title)}
    yes = btn(ctx.t("ch.ban.yes" if ban else "ch.remove.yes"), ChCB(a="bny" if ban else "rmy", id=chat.id, f=f, p=p),
              style="danger")
    markup = kb([yes, btn(ctx.t("ch.confirm.no"), ChCB(a="op", id=chat.id, f=f, p=p))])
    await show(call, ctx.t("ch.ban.confirm" if ban else "ch.remove.confirm", **kw), markup)


@router.callback_query(ChCB.filter(F.a.in_({"rmy", "bny"})))
async def on_remove(call: CallbackQuery, callback_data: ChCB, ctx: Ctx, session: AsyncSession,
                    publisher: Publisher) -> None:
    chat = await _admin_chat(call, ctx, session, callback_data.id)
    if chat is None:
        return
    ban = callback_data.a == "bny"
    if not _can_remove(chat, ban):
        await _wrong_status(call, ctx, chat)
        return
    bot = await _ws_bot(call, ctx)
    if bot is None:
        return
    name = esc(truncate(chat.display_title, 60))
    async with chat_svc.chat_lock(bot.id, chat.chat_id):
        await session.refresh(chat)
        if not _can_remove(chat, ban):
            await _wrong_status(call, ctx, chat)
            return
        await chat_svc.remove(bot, session, ctx.ws_rec, chat, ctx.user_id, publisher=publisher, ban=ban)
        await session.commit()
    await toast(call, ctx.t("ch.toast.banned" if ban else "ch.toast.removed", chat=name))
    await render_list(call, ctx, session, callback_data.f, callback_data.p)


@router.callback_query(ChCB.filter(F.a == "ub"))
async def on_unban(call: CallbackQuery, callback_data: ChCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _admin_chat(call, ctx, session, callback_data.id)
    if chat is None:
        return
    if chat.status != ChatStatus.BANNED:
        await _wrong_status(call, ctx, chat)
        return
    chat.status = ChatStatus.LEFT  # adding the bot again is a new admission
    chat.decided_by = ctx.user_id
    chat.decided_at = utcnow()
    await toast(call, ctx.t("ch.toast.unbanned"))
    await render_detail(call, ctx, session, chat, callback_data.f, callback_data.p)


# --------------------------------------------------------------------------- ⏸ paused chats
def _paused_by(ctx: Ctx, chat: Chat, owners: dict[int, User], now: datetime) -> str:
    """Who paused it: its partner (``🤝 @pepe``), ``👮 un admin`` or both."""
    if not chat.owner_pause_active(now):
        return ctx.t("ch.paused.by_admin")
    owner = chat_svc.owner_html(chat, owners) or ctx.t("common.unknown")
    return ctx.t("ch.paused.by_both" if chat.admin_paused else "ch.paused.by_owner", owner=owner)


async def render_paused(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, page: int = 0) -> None:
    """Every paused chat, by its owner or by an admin (who, until, since), with ▶️ to resume each one."""
    if not ctx.is_admin:
        await show(event, ctx.t("common.no_permission"), kb(back_row(ctx.lang)))
        return
    now = utcnow()
    chats = [c for c in await chat_svc.listed_chats(session, ctx.ws_id)
             if c.status == ChatStatus.APPROVED and c.is_paused(now)]
    items, page, pages = paginate(chats, page, PER_PAGE)
    owners = await chat_svc.users_by_id(session, {c.owner_user_id for c in items if c.owner_pause_active(now)})
    lines = [ctx.t("ch.paused.title", n=num(len(chats)))]
    lines += [ctx.t("ch.paused.hint"), ""] if chats else ["", ctx.t("ch.paused.empty")]
    rows: list[list[InlineKeyboardButton]] = []
    for i, chat in enumerate(items, start=page * PER_PAGE + 1):
        icon = chat_svc.chat_icon(chat)
        until = ctx.t("ch.paused.until_admin") if chat.admin_paused else _owner_until(ctx, chat)
        lines.append(ctx.t("ch.paused.row", n=i, icon=icon, chat=chat_svc.chat_name(chat, 48),
                           who=_paused_by(ctx, chat, owners, now), until=until, since=dt(chat.paused_at, ctx.tz)))
        rows.append([btn(f"#{i} {icon} {truncate(chat.display_title, 24)}", MenuCB(screen="chat", arg=chat.id)),
                     btn(f"▶️ #{i}", ChCB(a="pr", id=chat.id, p=page), style="success")])
    if pages > 1:
        lines += ["", ctx.t("common.page", page=page + 1, pages=pages)]
    markup = kb(*rows, nav_row(page, pages, lambda p: MenuCB(screen="paused", arg=p), ctx.lang), back_row(ctx.lang))
    await show(event, "\n".join(lines), markup)


@screen("paused")
async def paused_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                        **_: object) -> None:
    await render_paused(event, ctx, session, arg)


# --------------------------------------------------------------------------- 📥 import
@screen("import")
async def import_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                        **_: object) -> None:
    if not ctx.is_admin:
        await show(event, ctx.t("common.no_permission"), kb(back_row(ctx.lang)))
        return
    state = fsm_of(event, ctx)
    if state is not None:
        await state.set_state(ChatsFSM.refs)
    await prompt(event, ctx, ctx.t("ch.import.prompt"), cancel_screen="chats")


_REF_RE = re.compile(r"^(?:https?://)?(?:t\.me/|telegram\.me/)?@?([A-Za-z][A-Za-z0-9_]{3,31})/?$")


def parse_ref(raw: str) -> int | str | None:
    """``-100123`` -> int, ``@canal`` / ``t.me/canal`` -> ``"@canal"``; None when it is neither."""
    raw = raw.strip()
    if re.fullmatch(r"-?\d{1,20}", raw):
        return int(raw)
    m = _REF_RE.match(raw)
    return f"@{m.group(1)}" if m else None


IMPORT_ORDER = (chat_svc.ADDED, chat_svc.PENDING, chat_svc.EXISTING, chat_svc.NOT_ADMIN, chat_svc.NOT_FOUND,
                chat_svc.LIMIT, chat_svc.REJECTED)


@router.message(ChatsFSM.refs, F.chat.type == "private", ~F.text.startswith("/"))
async def on_import_refs(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext,
                         settings: Settings) -> None:
    if not ctx.is_admin:
        await state.clear()
        return
    raw = [part for part in re.split(r"[\s,;]+", message.text or "") if part]
    if not raw or len(raw) > IMPORT_MAX:
        await prompt(message, ctx, ctx.t("ch.import.invalid", max=IMPORT_MAX) + "\n\n" + ctx.t("ch.import.prompt"),
                     cancel_screen="chats")
        return
    bot = ctx.ws_bot()
    if bot is None:
        await state.clear()
        await show(message, ctx.t("common.not_running"), kb(back_row(ctx.lang, "chats")))
        return
    await state.clear()
    outcomes: dict[str, list[str]] = {key: [] for key in IMPORT_ORDER}
    for part in dict.fromkeys(raw):
        ref = parse_ref(part)
        outcome = (await chat_svc.register_existing(bot, session, ctx.ws_rec, ref, added_by=ctx.user_id,
                                                    settings=settings) if ref is not None else chat_svc.NOT_FOUND)
        outcomes.setdefault(outcome, []).append(part)
        await session.commit()  # one chat at a time: what was imported stays even if a later one fails
    lines = [ctx.t("ch.import.title")]
    for key in IMPORT_ORDER:
        refs = outcomes.get(key) or []
        if refs:
            lines.append(ctx.t(f"ch.import.{key}", n=len(refs)))
            if key not in (chat_svc.ADDED, chat_svc.EXISTING):
                lines.append(ctx.t("ch.import.refs", refs=esc(", ".join(truncate(r, 40) for r in refs))))
    markup = kb([btn(ctx.t("ch.btn.import_more"), MenuCB(screen="import"))],
                [btn(ctx.t("ch.btn.chats"), MenuCB(screen="chats"))])
    await show(message, "\n".join(lines), markup)


# --------------------------------------------------------------------------- 📢 message to the partners
@screen("partners_msg")
async def partners_msg_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                              **_: object) -> None:
    if not ctx.is_admin:
        await show(event, ctx.t("common.no_permission"), kb(back_row(ctx.lang)))
        return
    n = len(await chat_svc.partner_ids(session, ctx.ws_id))
    if not n:
        await show(event, ctx.t("ch.pm.none"), kb(back_row(ctx.lang, "chats")))
        return
    state = fsm_of(event, ctx)
    if state is not None:
        await state.set_state(ChatsFSM.blast)
    await prompt(event, ctx, ctx.t("ch.pm.prompt", n=num(n)), cancel_screen="chats")


@router.message(ChatsFSM.blast, F.chat.type == "private", ~F.text.startswith("/"))
async def on_blast_message(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not ctx.is_admin:
        await state.clear()
        return
    data: dict[str, Any] = {"chat_id": message.chat.id, "message_id": message.message_id}
    if ctx.in_ws:
        # The partners talk to the managed bot, which can't copy a message of this chat: it sends the content.
        c = content.from_message(message)
        if c is None or content.content_error(c):
            error = ctx.t(content.content_error(c) if c is not None else "content.err.unsupported")
            await prompt(message, ctx, error, cancel_screen="chats")
            return
        data["content"] = {"kind": c.kind, "text": c.text, "file_id": c.file_id, "file_name": c.file_name,
                           "bot_id": ctx.bot_id}
    await state.set_data(data)
    n = len(await chat_svc.partner_ids(session, ctx.ws_id))
    markup = kb([btn(ctx.t("ch.btn.send"), ChCB(a="bs"), style="success")], cancel_row(ctx.lang, "chats"))
    await show(message, ctx.t("ch.pm.confirm", n=num(n)), markup)


_blasts: set[asyncio.Task[Any]] = set()


async def _send_content(bot: Bot, manager: Any, data: dict[str, Any], user_ids: list[int]) -> blast.BlastResult:
    """The content of a message sent to another bot, sent to every user by ``bot`` (its media passed over once)."""
    post = Post(kind=data["kind"], text=data["text"], media={str(data["bot_id"]): data["file_id"]}
                if data["file_id"] else {}, media_name=data["file_name"], buttons=[])
    res = blast.BlastResult()
    media = await content.media_for(bot, post, manager)
    for uid in dict.fromkeys(user_ids):
        try:
            sent = await content.deliver(bot, uid, post, media=media, reply_markup=None)
            res.sent += 1
            if isinstance(media, InputFile):
                media = content.file_id_of(sent, post.kind) or media
        except TelegramAPIError as exc:
            if is_user_blocked(exc):
                res.blocked += 1
            else:
                res.failed += 1
                log.info("Message to partner %s failed: %s", uid, short(exc))
    return res


async def _run_blast(report_bot: Bot, bot: Bot, sm: SessionMaker, manager: Any, admin_id: int, lang: str,
                     data: dict[str, Any], user_ids: list[int]) -> None:
    set_low_priority()
    try:
        if data.get("content"):
            res = await _send_content(bot, manager, data["content"], user_ids)
        else:
            res = await blast.copy_to_users(bot, sm, int(data["chat_id"]), int(data["message_id"]), user_ids)
        text = t("ch.pm.report", lang, sent=num(res.sent), failed=num(res.failed), blocked=num(res.blocked))
    except content.MediaError as exc:
        text = t(f"content.err.media_{exc}", lang)
    except Exception:  # noqa: BLE001 - background task: the admin hears about it
        log.exception("Message to the partners of bot %s failed", bot.id)
        text = t("common.error", lang)
    await send_dm(report_bot, None, admin_id, text)


@router.callback_query(ChCB.filter(F.a == "bs"))
async def on_blast_send(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext,
                        sm: SessionMaker) -> None:
    if not ctx.is_admin:
        await alert(call, ctx.t("common.no_permission"))
        return
    data = await state.get_data()
    if await state.get_state() != ChatsFSM.blast.state or not data.get("message_id"):
        await alert(call, ctx.t("ch.pm.expired"))
        return
    bot = await _ws_bot(call, ctx)
    if bot is None or call.bot is None:
        return
    user_ids = await chat_svc.partner_ids(session, ctx.ws_id)
    await state.clear()
    task = asyncio.create_task(_run_blast(call.bot, bot, sm, ctx.manager, ctx.user_id, ctx.lang, data, user_ids))
    _blasts.add(task)
    task.add_done_callback(_blasts.discard)
    await toast(call, ctx.t("ch.toast.sending"))
    await show(call, ctx.t("ch.pm.started", n=num(len(user_ids))), kb(back_row(ctx.lang, "chats")))
