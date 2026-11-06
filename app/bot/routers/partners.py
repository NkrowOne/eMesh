"""🤝 Partners (owners of external chats): how to join the network, 📣 Mis canales and the panel of each chat
(pause within the admins' rules, resume their own pause, categories = open groups, leave the network). A partner
only touches their own external chats; admins can look at a chat's panel."""
from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.db.base import utcnow
from app.db.models import Chat, ChatGroup, ChatOrigin, ChatStatus
from app.services import audience, chatstate, stats
from app.services import chats as chat_svc
from app.services.chatinfo import REQUIRED_CHANNEL, REQUIRED_GROUP, add_to_channel_url, add_to_group_url
from app.services.publisher import Publisher
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, grid, kb, nav_row, paginate, show, toast, toggle_label
from app.ui.fmt import dt, esc, num, truncate
from app.ui.screens import screen

log = logging.getLogger(__name__)

router = Router(name="partners")

PER_PAGE = 10
# ⏸ durations a partner can choose, when the admins' rules allow them (chat_svc.pause_allowed): value -> (label,
# length; None = until they resume it)
PAUSES: dict[int, tuple[str, timedelta | None]] = {
    1: ("pa.pause.1h", timedelta(hours=1)),
    2: ("pa.pause.6h", timedelta(hours=6)),
    3: ("pa.pause.24h", timedelta(hours=24)),
    4: ("pa.pause.3d", timedelta(days=3)),
    5: ("pa.pause.7d", timedelta(days=7)),
    6: ("pa.pause.open", None),
}
PAUSE_ROWS = ((1, 2, 3), (4, 5), (6,))


class PaCB(CallbackData, prefix="pa"):
    # ls my chats page · op open · pm pause menu · pz pause (v: duration) · rs resume · ct categories
    # cx join / leave a category (v: group id) · lv leave the network · lvy confirmed
    a: str
    id: int = 0
    v: int = 0
    p: int = 0


async def _my_chats(session: AsyncSession, ctx: Ctx) -> list[Chat]:
    q = (select(Chat)
         .where(Chat.bot_id == ctx.ws_id, Chat.origin == ChatOrigin.EXTERNAL, Chat.owner_user_id == ctx.user_id,
                Chat.status != ChatStatus.LEFT)
         .order_by(Chat.id))
    return sorted((await session.execute(q)).scalars(), key=lambda c: (c.display_title.casefold(), c.id))


def _owns(ctx: Ctx, chat: Chat) -> bool:
    return (chat.bot_id == ctx.ws_id and chat.is_external and chat.owner_user_id is not None
            and chat.owner_user_id == ctx.user_id)


async def _own_chat(call: CallbackQuery, ctx: Ctx, session: AsyncSession, pk: int) -> Chat | None:
    """The partner's own external chat of a button, or None after an alert (forged or someone else's)."""
    chat = await session.get(Chat, pk)
    if chat is None or not _owns(ctx, chat):
        await alert(call, ctx.t("common.not_found"))
        return None
    return chat


def _add_buttons(ctx: Ctx) -> list[InlineKeyboardButton]:
    username = ctx.ws_rec.username
    if not username or not ctx.ws_rec.join_open:
        return []
    return [btn(ctx.t("pa.btn.add_channel"), url=add_to_channel_url(username)),
            btn(ctx.t("pa.btn.add_group"), url=add_to_group_url(username))]


# --------------------------------------------------------------------------- join
@screen("join")
async def join_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                      **_: object) -> None:
    ws = ctx.ws_rec
    mine = len(await _my_chats(session, ctx))
    my_row = [btn(ctx.t("pa.btn.my_chats", n=num(mine)), MenuCB(screen="my_chats"))] if mine else None
    if not ws.join_open:
        await show(event, ctx.t("pa.join.closed"), kb(my_row, back_row(ctx.lang)))
        return
    lines = [ctx.t("pa.join.title", bot=esc(ws.username)), "", ctx.t("pa.join.step1"),
             ctx.t("pa.join.step2", channel=chatstate.rights_text(list(REQUIRED_CHANNEL), ctx.lang),
                   group=chatstate.rights_text(list(REQUIRED_GROUP), ctx.lang)),
             ctx.t("pa.join.approval" if ws.join_approval else "pa.join.auto")]
    if ws.min_members:
        lines.append(ctx.t("pa.join.min", n=num(ws.min_members)))
    if ws.partners_can_pause:
        lines += ["", ctx.t("pa.join.pause")]
    await show(event, "\n".join(lines), kb(_add_buttons(ctx), my_row, back_row(ctx.lang)))


# --------------------------------------------------------------------------- 📣 Mis canales
async def render_my_chats(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, page: int = 0) -> None:
    chats = await _my_chats(session, ctx)
    items, page, pages = paginate(chats, page, PER_PAGE)
    lines = [ctx.t("pa.list.title"), ctx.t("pa.list.hint", bot=esc(ctx.ws_rec.username)), ""]
    buttons: list[InlineKeyboardButton] = []
    for i, chat in enumerate(items, start=page * PER_PAGE + 1):
        icon = chat_svc.chat_icon(chat)
        lines.append(ctx.t("pa.list.row", n=i, icon=icon, chat=chat_svc.chat_name(chat, 48),
                           mark=chat_svc.status_icon(chat), members=num(chat.members),
                           status=chat_svc.status_text(chat, ctx.lang, ctx.tz, partner=True)))
        buttons.append(btn(f"#{i} {icon} {truncate(chat.display_title, 24)}", PaCB(a="op", id=chat.id, p=page)))
    if not chats:
        lines.append(ctx.t("pa.list.empty"))
    if pages > 1:
        lines += ["", ctx.t("common.page", page=page + 1, pages=pages)]
    markup = kb(
        *grid(buttons, 2),
        nav_row(page, pages, lambda p: PaCB(a="ls", p=p), ctx.lang),
        _add_buttons(ctx),
        [btn(ctx.t("pa.btn.join"), MenuCB(screen="join"))] if not chats else None,
        back_row(ctx.lang),
    )
    await show(event, "\n".join(lines), markup)


@screen("my_chats")
async def my_chats_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                          **_: object) -> None:
    await render_my_chats(event, ctx, session, arg)


@router.callback_query(PaCB.filter(F.a == "ls"))
async def on_list(call: CallbackQuery, callback_data: PaCB, ctx: Ctx, session: AsyncSession) -> None:
    await render_my_chats(call, ctx, session, callback_data.p)


# --------------------------------------------------------------------------- a chat's panel
async def _panel_text(ctx: Ctx, session: AsyncSession, chat: Chat) -> str:
    lines = [f"{chat_svc.chat_icon(chat)} <b>{esc(chat.display_title)}</b>",
             ctx.t("pa.d.status", status=chat_svc.status_text(chat, ctx.lang, ctx.tz, partner=True))]
    if chat.status == ChatStatus.APPROVED and chat.admin_paused:
        lines.append(ctx.t("pa.d.admin_hint"))
    if chat.status == ChatStatus.APPROVED and not chat.owner_pause_active() and not ctx.ws_rec.partners_can_pause:
        lines.append(ctx.t("pa.pause.not_allowed"))  # in place of the ⏸ Pausar button
    week = await stats.chat_received(session, chat.id, days=7)
    lines.append(ctx.t("pa.d.received", total=num(chat.posts_total), week=num(week)))
    lines.append(ctx.t("pa.d.last", date=dt(chat.last_post_at, ctx.tz)))
    names = chat_svc.group_names(await chat_svc.open_groups_of(session, ctx.ws_id, chat.id))
    if names:
        lines.append(ctx.t("pa.d.categories", names=names))
    if not _owns(ctx, chat):
        lines += ["", ctx.t("pa.d.view_only")]
    return "\n".join(lines)


async def _has_categories(session: AsyncSession, ws_id: int) -> bool:
    return any(g.open for g in await audience.bot_groups(session, ws_id))


async def _panel_markup(ctx: Ctx, session: AsyncSession, chat: Chat, page: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton] | None] = []
    if _owns(ctx, chat) and chat.status in chat_svc.ACTIVE:
        if chat.status == ChatStatus.APPROVED:
            if chat.owner_pause_active():
                rows.append([btn(ctx.t("pa.btn.resume"), PaCB(a="rs", id=chat.id, p=page), style="success")])
            elif ctx.ws_rec.partners_can_pause:
                rows.append([btn(ctx.t("pa.btn.pause"), PaCB(a="pm", id=chat.id, p=page))])
        if await _has_categories(session, ctx.ws_id):
            rows.append([btn(ctx.t("pa.btn.categories"), PaCB(a="ct", id=chat.id, p=page))])
        rows.append([btn(ctx.t("pa.btn.leave"), PaCB(a="lv", id=chat.id, p=page), style="danger")])
    elif ctx.is_admin:
        rows.append([btn(ctx.t("pa.btn.admin_view"), MenuCB(screen="chat", arg=chat.id))])
    rows.append([btn(ctx.t("common.back"), PaCB(a="ls", p=page))])
    return kb(*rows)


async def render_panel(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, chat: Chat,
                       page: int = 0, notice: str | None = None) -> None:
    text = await _panel_text(ctx, session, chat)
    if notice:
        text = f"{notice}\n\n{text}"
    await show(event, text, await _panel_markup(ctx, session, chat, page))


@screen("my_chat")
async def my_chat_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                         **_: object) -> None:
    chat = await session.get(Chat, arg)
    if (chat is None or chat.bot_id != ctx.ws_id or not chat.is_external
            or not (_owns(ctx, chat) or ctx.is_admin)):
        await show(event, ctx.t("common.not_found"), kb(back_row(ctx.lang, "my_chats")))
        return
    await render_panel(event, ctx, session, chat)


@router.callback_query(PaCB.filter(F.a == "op"))
async def on_open(call: CallbackQuery, callback_data: PaCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _own_chat(call, ctx, session, callback_data.id)
    if chat is not None:
        await render_panel(call, ctx, session, chat, callback_data.p)


# --------------------------------------------------------------------------- ⏸ pause / ▶️ resume
async def _approved_chat(call: CallbackQuery, ctx: Ctx, session: AsyncSession, cb: PaCB) -> Chat | None:
    chat = await _own_chat(call, ctx, session, cb.id)
    if chat is not None and chat.status != ChatStatus.APPROVED:
        await alert(call, ctx.t("pa.toast.not_active",
                                status=chat_svc.status_text(chat, ctx.lang, ctx.tz, partner=True)))
        return None
    return chat


async def _render_pause_menu(call: CallbackQuery, ctx: Ctx, chat: Chat, page: int) -> None:
    """The durations the admins' rules allow (at least 1 h when partners may pause)."""
    rows = [[btn(ctx.t(PAUSES[v][0]), PaCB(a="pz", id=chat.id, v=v, p=page)) for v in row
             if chat_svc.pause_allowed(ctx.ws_rec, PAUSES[v][1])] for row in PAUSE_ROWS]
    rows.append([btn(ctx.t("common.back"), PaCB(a="op", id=chat.id, p=page))])
    await show(call, ctx.t("pa.pause.title", chat=esc(chat.display_title), kind=chatstate.kind_word(chat, ctx.lang)),
               kb(*rows))


@router.callback_query(PaCB.filter(F.a == "pm"))
async def on_pause_menu(call: CallbackQuery, callback_data: PaCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _approved_chat(call, ctx, session, callback_data)
    if chat is None:
        return
    if not ctx.ws_rec.partners_can_pause:
        await alert(call, ctx.t("pa.pause.not_allowed"))
        await render_panel(call, ctx, session, chat, callback_data.p)
        return
    await _render_pause_menu(call, ctx, chat, callback_data.p)


@router.callback_query(PaCB.filter(F.a == "pz"))
async def on_pause(call: CallbackQuery, callback_data: PaCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _approved_chat(call, ctx, session, callback_data)
    if chat is None:
        return
    choice = PAUSES.get(callback_data.v)
    if choice is None:
        await alert(call, ctx.t("common.not_found"))
        return
    bot = ctx.ws_bot()
    if bot is None:
        await alert(call, ctx.t("common.not_running"))
        return
    length = choice[1]
    until = utcnow() + length if length is not None else None
    if not await chat_svc.pause_by_owner(bot, session, ctx.ws_rec, chat, ctx.user_id, until):
        # The admins' rules don't allow it: a forged button, or a menu shown before they changed.
        if ctx.ws_rec.partners_can_pause:
            await alert(call, ctx.t("pa.pause.too_long"))
            await _render_pause_menu(call, ctx, chat, callback_data.p)
        else:
            await alert(call, ctx.t("pa.pause.not_allowed"))
            await render_panel(call, ctx, session, chat, callback_data.p)
        return
    await toast(call, ctx.t("pa.toast.paused"))
    await render_panel(call, ctx, session, chat, callback_data.p)


@router.callback_query(PaCB.filter(F.a == "rs"))
async def on_resume(call: CallbackQuery, callback_data: PaCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _approved_chat(call, ctx, session, callback_data)
    if chat is None:
        return
    if not chat.owner_pause_active():
        # Only their own pause: a pause of the administration is theirs to lift.
        await alert(call, ctx.t("pa.toast.admin_pause" if chat.admin_paused else "pa.toast.not_paused"))
        return
    bot = ctx.ws_bot()
    if bot is None:
        await alert(call, ctx.t("common.not_running"))
        return
    await chat_svc.resume_by_owner(bot, session, ctx.ws_rec, chat, ctx.user_id)
    await toast(call, ctx.t("pa.toast.resumed"))
    await render_panel(call, ctx, session, chat, callback_data.p)


# --------------------------------------------------------------------------- 🗂 categories (open groups)
async def _render_categories(call: CallbackQuery, ctx: Ctx, session: AsyncSession, chat: Chat, page: int) -> None:
    groups = [g for g in await audience.bot_groups(session, ctx.ws_id) if g.open]
    member = await audience.chat_group_ids(session, chat.id)
    kind = chatstate.kind_word(chat, ctx.lang)
    lines = [ctx.t("pa.cat.title", chat=esc(chat.display_title)), "",
             ctx.t("pa.cat.hint", kind=kind) if groups else ctx.t("pa.cat.empty")]
    buttons = [btn(toggle_label(f"🗂 {truncate(g.name, 40)}", g.id in member),
                   PaCB(a="cx", id=chat.id, v=g.id, p=page)) for g in groups[:90]]
    markup = kb(*grid(buttons, 2), [btn(ctx.t("common.back"), PaCB(a="op", id=chat.id, p=page))])
    await show(call, "\n".join(lines), markup)


@router.callback_query(PaCB.filter(F.a == "ct"))
async def on_categories(call: CallbackQuery, callback_data: PaCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _own_chat(call, ctx, session, callback_data.id)
    if chat is None:
        return
    if chat.status not in chat_svc.ACTIVE:
        await alert(call, ctx.t("pa.toast.not_active",
                                status=chat_svc.status_text(chat, ctx.lang, ctx.tz, partner=True)))
        return
    await _render_categories(call, ctx, session, chat, callback_data.p)


@router.callback_query(PaCB.filter(F.a == "cx"))
async def on_category_toggle(call: CallbackQuery, callback_data: PaCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _own_chat(call, ctx, session, callback_data.id)
    if chat is None:
        return
    if chat.status not in chat_svc.ACTIVE:
        await alert(call, ctx.t("pa.toast.not_active",
                                status=chat_svc.status_text(chat, ctx.lang, ctx.tz, partner=True)))
        return
    group = await session.get(ChatGroup, callback_data.v)
    if group is None or group.bot_id != ctx.ws_id or not group.open:
        await alert(call, ctx.t("common.not_found"))
        return
    on = group.id not in await audience.chat_group_ids(session, chat.id)
    await audience.set_member(session, group.id, chat.id, on)
    await toast(call, ctx.t("pa.toast.cat_on" if on else "pa.toast.cat_off", group=esc(truncate(group.name, 40))))
    await _render_categories(call, ctx, session, chat, callback_data.p)


# --------------------------------------------------------------------------- 🚪 leave the network
@router.callback_query(PaCB.filter(F.a == "lv"))
async def on_leave_ask(call: CallbackQuery, callback_data: PaCB, ctx: Ctx, session: AsyncSession) -> None:
    chat = await _own_chat(call, ctx, session, callback_data.id)
    if chat is None:
        return
    if chat.status not in chat_svc.ACTIVE:
        await alert(call, ctx.t("pa.toast.not_active",
                                status=chat_svc.status_text(chat, ctx.lang, ctx.tz, partner=True)))
        return
    markup = kb([btn(ctx.t("pa.leave.yes"), PaCB(a="lvy", id=chat.id, p=callback_data.p), style="danger"),
                 btn(ctx.t("pa.leave.no"), PaCB(a="op", id=chat.id, p=callback_data.p))])
    await show(call, ctx.t("pa.leave.confirm", kind=chatstate.kind_word(chat, ctx.lang),
                           chat=esc(chat.display_title)), markup)


@router.callback_query(PaCB.filter(F.a == "lvy"))
async def on_leave(call: CallbackQuery, callback_data: PaCB, ctx: Ctx, session: AsyncSession,
                   publisher: Publisher) -> None:
    chat = await _own_chat(call, ctx, session, callback_data.id)
    if chat is None:
        return
    if chat.status not in chat_svc.ACTIVE:
        await alert(call, ctx.t("pa.toast.not_active",
                                status=chat_svc.status_text(chat, ctx.lang, ctx.tz, partner=True)))
        return
    bot = ctx.ws_bot()
    if bot is None:
        await alert(call, ctx.t("common.not_running"))
        return
    async with chat_svc.chat_lock(bot.id, chat.chat_id):
        await session.refresh(chat)
        if chat.status not in chat_svc.ACTIVE:
            await alert(call, ctx.t("pa.toast.not_active",
                                    status=chat_svc.status_text(chat, ctx.lang, ctx.tz, partner=True)))
            return
        await chat_svc.remove(bot, session, ctx.ws_rec, chat, ctx.user_id, publisher=publisher, by_owner=True)
        await session.commit()
    await toast(call, ctx.t("pa.toast.left"))
    await show(call, ctx.t("pa.leave.done", kind=chatstate.kind_word(chat, ctx.lang), chat=esc(chat.display_title)),
               kb([btn(ctx.t("ce.btn.my_chats"), MenuCB(screen="my_chats"))]))
