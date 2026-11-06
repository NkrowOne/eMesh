"""⏳ Requests: the admins' decisions (✅ Aceptar / ❌ Rechazar with a reason) from the notices, the list or a chat's
detail, the rights re-check of a waiting chat (🔄 Comprobar de nuevo) and the ``requests`` screen."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.routers.chats import ChatsFSM
from app.db.models import Chat, ChatStatus
from app.services import chats as chat_svc
from app.services import chatstate
from app.services.chats import SRC_CHAT, SRC_LIST, SRC_NOTICE, RqCB
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, cancel_row, kb, nav_row, paginate, show, toast
from app.ui.fmt import esc, num, truncate
from app.ui.screens import open_screen, screen

log = logging.getLogger(__name__)

router = Router(name="requests")

PER_PAGE = 10
REASON_MAX = 500


async def _ws_chat(session: AsyncSession, ctx: Ctx, pk: int) -> Chat | None:
    chat = await session.get(Chat, pk)
    return chat if chat is not None and chat.bot_id == ctx.ws_id else None


def _already(ctx: Ctx, chat: Chat) -> str:
    return ctx.t("rq.toast.already", status=chat_svc.status_text(chat, ctx.lang, ctx.tz))


async def _pending_chat(call: CallbackQuery, ctx: Ctx, session: AsyncSession, pk: int) -> Chat | None:
    """The pending chat of a decision button (admins only), or None after an alert."""
    if not ctx.is_admin:
        await alert(call, ctx.t("common.no_permission"))
        return None
    chat = await _ws_chat(session, ctx, pk)
    if chat is None:
        await alert(call, ctx.t("common.not_found"))
        return None
    if chat.status != ChatStatus.PENDING:
        await alert(call, _already(ctx, chat))
        return None
    return chat


async def _after(event: CallbackQuery | Message, ctx: Ctx, session: AsyncSession, src: int, pk: int, page: int,
                 done: str) -> None:
    if src == SRC_LIST:
        await open_screen("requests", event, ctx, session, arg=page)
    elif src == SRC_CHAT:
        await open_screen("chat", event, ctx, session, arg=pk)
    elif isinstance(event, Message):
        await show(event, done, kb([btn(ctx.t("rq.btn.requests"), MenuCB(screen="requests"))]))


# --------------------------------------------------------------------------- accept
@router.callback_query(RqCB.filter(F.a == "ok"))
async def on_accept(call: CallbackQuery, callback_data: RqCB, ctx: Ctx, session: AsyncSession,
                    state: FSMContext) -> None:
    chat = await _pending_chat(call, ctx, session, callback_data.pk)
    if chat is None:
        return
    bot = ctx.ws_bot()
    if bot is None:
        await alert(call, ctx.t("common.not_running"))
        return
    if await state.get_state() == ChatsFSM.reason.state:
        await state.clear()  # a reject prompt left open must not take the admin's next message
    async with chat_svc.chat_lock(bot.id, chat.chat_id):
        await session.refresh(chat)  # a chat event (the bot removed) may have changed it meanwhile
        if chat.status != ChatStatus.PENDING:
            await alert(call, _already(ctx, chat))
            return
        await chat_svc.approve(bot, session, ctx.ws_rec, chat, ctx.user_id)
        await session.commit()
    await toast(call, ctx.t("rq.toast.accepted"))
    await _after(call, ctx, session, callback_data.s, chat.id, callback_data.p, "")


# --------------------------------------------------------------------------- reject
def _reason_prompt(ctx: Ctx, chat: Chat, src: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
    cancel = ("chat", chat.id) if src == SRC_CHAT else ("requests", page if src == SRC_LIST else 0)
    markup = kb([btn(ctx.t("rq.btn.no_reason"), RqCB(a="nr", pk=chat.id, s=src, p=page))],
                cancel_row(ctx.lang, *cancel))
    return ctx.t("rq.reason.prompt", chat=esc(chat.display_title)), markup


@router.callback_query(RqCB.filter(F.a == "no"))
async def on_reject(call: CallbackQuery, callback_data: RqCB, ctx: Ctx, session: AsyncSession,
                    state: FSMContext) -> None:
    chat = await _pending_chat(call, ctx, session, callback_data.pk)
    if chat is None:
        return
    text, markup = _reason_prompt(ctx, chat, callback_data.s, callback_data.p)
    # From a notice the prompt is a new message: the notice stays as it is.
    msg = await show(call, text, markup, new=callback_data.s == SRC_NOTICE)
    await state.set_state(ChatsFSM.reason)
    await state.set_data({"pk": chat.id, "s": callback_data.s, "p": callback_data.p,
                          "prompt_id": msg.message_id if msg else None})


async def _refuse(event: CallbackQuery | Message, ctx: Ctx, text: str) -> None:
    if isinstance(event, CallbackQuery):
        await alert(event, text)
    else:
        await show(event, text, kb([btn(ctx.t("rq.btn.requests"), MenuCB(screen="requests"))]))


async def _do_reject(event: CallbackQuery | Message, ctx: Ctx, session: AsyncSession, state: FSMContext, pk: int,
                     src: int, page: int, reason: str | None) -> None:
    await state.clear()
    chat = await _ws_chat(session, ctx, pk)
    if chat is None:
        await _refuse(event, ctx, ctx.t("common.not_found"))
        return
    if chat.status != ChatStatus.PENDING:
        await _refuse(event, ctx, _already(ctx, chat))
        return
    bot = ctx.ws_bot()
    if bot is None:
        await _refuse(event, ctx, ctx.t("common.not_running"))
        return
    async with chat_svc.chat_lock(bot.id, chat.chat_id):
        await session.refresh(chat)
        if chat.status != ChatStatus.PENDING:
            await _refuse(event, ctx, _already(ctx, chat))
            return
        await chat_svc.reject(bot, session, ctx.ws_rec, chat, ctx.user_id, reason)
        await session.commit()
    done = ctx.t("rq.reason.done", kind=chatstate.kind_word(chat, ctx.lang), chat=esc(chat.display_title))
    if isinstance(event, CallbackQuery):
        await toast(event, ctx.t("rq.toast.rejected"))
        if src == SRC_NOTICE:
            await show(event, done, kb([btn(ctx.t("rq.btn.requests"), MenuCB(screen="requests"))]))
            return
    await _after(event, ctx, session, src, chat.id, page, done)


@router.callback_query(RqCB.filter(F.a == "nr"))
async def on_no_reason(call: CallbackQuery, callback_data: RqCB, ctx: Ctx, session: AsyncSession,
                       state: FSMContext) -> None:
    if not ctx.is_admin:
        await alert(call, ctx.t("common.no_permission"))
        return
    await _do_reject(call, ctx, session, state, callback_data.pk, callback_data.s, callback_data.p, None)


async def _delete_prompt(message: Message, prompt_id: object) -> None:
    if not isinstance(prompt_id, int) or message.bot is None:
        return
    try:
        await message.bot.delete_message(message.chat.id, prompt_id)
    except TelegramAPIError:
        pass


@router.message(ChatsFSM.reason, F.chat.type == "private", ~F.text.startswith("/"))
async def on_reason(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    if not ctx.is_admin:
        await state.clear()
        return
    pk, src, page = int(data.get("pk") or 0), int(data.get("s") or 0), int(data.get("p") or 0)
    reason = (message.text or "").strip()
    if not reason or len(reason) > REASON_MAX:
        chat = await _ws_chat(session, ctx, pk)
        if chat is None:
            await state.clear()
            await _refuse(message, ctx, ctx.t("common.not_found"))
            return
        await _delete_prompt(message, data.get("prompt_id"))
        text, markup = _reason_prompt(ctx, chat, src, page)
        msg = await show(message, ctx.t("rq.reason.invalid", max=REASON_MAX) + "\n\n" + text, markup)
        await state.update_data(prompt_id=msg.message_id if msg else None)
        return
    await _delete_prompt(message, data.get("prompt_id"))
    await _do_reject(message, ctx, session, state, pk, src, page, reason)


# --------------------------------------------------------------------------- 🔄 Comprobar de nuevo
@router.callback_query(RqCB.filter(F.a == "chk"))
async def on_recheck(call: CallbackQuery, callback_data: RqCB, ctx: Ctx, session: AsyncSession) -> None:
    """The owner of a chat that was missing rights (or an admin) checks them again; a chat that waited for them
    goes on with its admission."""
    chat = await _ws_chat(session, ctx, callback_data.pk)
    if chat is None or not (ctx.is_admin or chat.owner_user_id == ctx.user_id):
        await alert(call, ctx.t("common.not_found"))
        return
    bot = ctx.ws_bot()
    if bot is None:
        await alert(call, ctx.t("common.not_running"))
        return
    back = (kb([btn(ctx.t("rq.btn.chat"), MenuCB(screen="chat", arg=chat.id))]) if ctx.is_admin
            else kb([btn(ctx.t("ce.btn.my_chats"), MenuCB(screen="my_chats"))]))
    async with chat_svc.chat_lock(bot.id, chat.chat_id):
        await session.refresh(chat)  # a chat event may have changed it meanwhile
        kind, name = chatstate.kind_word(chat, ctx.lang), esc(chat.display_title)
        if chat.status not in chat_svc.ACTIVE:
            await show(call, ctx.t("rq.check.inactive", kind=kind, chat=name,
                                   status=chat_svc.status_text(chat, ctx.lang, ctx.tz)), back)
            return
        was_ok = chat.rights_ok
        res = await chatstate.refresh(bot, session, ctx.ws_rec, chat)
        if res.gone:
            await session.commit()
            await show(call, ctx.t("rq.check.gone", kind=kind, chat=name), back)
            return
        if not chat.rights_ok:
            await session.commit()
            if res.error and not res.missing:  # Telegram didn't answer: the rights are unknown
                await alert(call, ctx.t("common.error"))
                return
            await toast(call, ctx.t("rq.toast.missing"))
            await show(call, chat_svc.missing_text(chat, chat_svc.missing_list(chat) or ["admin"], ctx.lang),
                       chat_svc.recheck_markup(chat, ctx.lang))
            return
        if chat.status == ChatStatus.PENDING and not was_ok:
            await chat_svc.admit(bot, session, ctx.ws_rec, chat)
        await session.commit()
    await toast(call, ctx.t("rq.toast.rights_ok"))
    key = "rq.check.ok_pending" if chat.status == ChatStatus.PENDING else "rq.check.ok"
    await show(call, ctx.t(key, kind=kind, chat=name), back)


# --------------------------------------------------------------------------- requests screen
@screen("requests")
async def requests_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                          **_: object) -> None:
    if not ctx.is_admin:
        await show(event, ctx.t("common.no_permission"), kb(back_row(ctx.lang)))
        return
    q = (select(Chat).where(Chat.bot_id == ctx.ws_id, Chat.status == ChatStatus.PENDING)
         .order_by(Chat.created_at, Chat.id))
    pending = list((await session.execute(q)).scalars())
    items, page, pages = paginate(pending, arg, PER_PAGE)
    owners = await chat_svc.users_by_id(session, {c.owner_user_id for c in items})
    lines = [ctx.t("rq.list.title", n=num(len(pending)))]
    rows: list[list[InlineKeyboardButton]] = []
    for i, chat in enumerate(items, start=page * PER_PAGE + 1):
        icon = chat_svc.chat_icon(chat)
        origin = (ctx.t("rq.list.ext", owner=chat_svc.owner_html(chat, owners)) if chat.is_external
                  else ctx.t("rq.list.own"))
        lines.append(ctx.t("rq.list.row", n=i, icon=icon, chat=chat_svc.chat_name(chat, 48),
                           warn="" if chat.rights_ok else " ⚠️", members=num(chat.members), origin=origin))
        rows.append([
            btn(f"#{i} {icon} {truncate(chat.display_title, 20)}", MenuCB(screen="chat", arg=chat.id)),
            btn("✅", RqCB(a="ok", pk=chat.id, s=SRC_LIST, p=page), style="success"),
            btn("❌", RqCB(a="no", pk=chat.id, s=SRC_LIST, p=page), style="danger"),
        ])
    if pending:
        lines.insert(1, ctx.t("rq.list.hint"))
        lines.insert(2, "")
    else:
        lines += ["", ctx.t("rq.list.empty")]
    if pages > 1:
        lines += ["", ctx.t("common.page", page=page + 1, pages=pages)]
    markup = kb(*rows, nav_row(page, pages, lambda p: RqCB(a="pg", p=p), ctx.lang), back_row(ctx.lang))
    await show(event, "\n".join(lines), markup)


@router.callback_query(RqCB.filter(F.a == "pg"))
async def on_requests_page(call: CallbackQuery, callback_data: RqCB, ctx: Ctx, session: AsyncSession,
                           state: FSMContext) -> None:
    await state.clear()
    await open_screen("requests", call, ctx, session, arg=callback_data.p)
