"""🤖 Crear mi bot (main bot): a clone created with Telegram Managed Bots or a @BotFather token, the platform's
clone policy (open / approval / closed) and limits, and 🤖 Mis bots (pause, resume, disconnect). A clone that starts
running gets the platform's bot image (👑 › 🖼 Imagen del bot) unless it has a photo of its own."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, ManagedBotUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.filters import MainBotFilter
from app.bot.routers.panel import approval_markup, give_image
from app.config import Settings
from app.db.models import Bot as BotRecord
from app.db.models import BotStatus
from app.db.session import SessionMaker
from app.services import brand, clones, limits
from app.services.notify import send_dm
from app.telegram.manager import BotManager, BotTokenError
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, kb, nav_row, paginate, prompt, show, toast
from app.ui.fmt import esc, truncate
from app.ui.screens import open_screen, screen

log = logging.getLogger(__name__)

router = Router(name="clone")

MYBOTS_PER_PAGE = 10
# Token errors after which the flow ends (sending another token wouldn't help).
FINAL_ERRORS = {"limit", "closed"}


class CloneCB(CallbackData, prefix="cl"):
    action: str
    id: int = 0
    page: int = 0


class CloneFSM(StatesGroup):
    token = State()


async def _limit_text(ctx: Ctx, session: AsyncSession) -> str:
    limit = await clones.clone_limit(session, ctx.settings, ctx.user_id)
    return ctx.t("common.infinite") if limit is None else str(limit)


async def _show_not_main(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession) -> None:
    """Clones are created and managed from the main bot: point there."""
    text = ctx.t("cl.not_main")
    if (await limits.platform(session, ctx.settings)).clone_policy == "closed":
        text += "\n\n" + ctx.t("cl.closed")
    main = await clones.main_username(session, ctx.settings)
    rows = []
    if main:
        rows.append([btn(ctx.t("cl.btn.open_main", username=main), url=f"https://t.me/{main}?start=clone")])
    rows.append(back_row(ctx.lang, "home"))
    await show(event, text, kb(*rows))


def _result_view(ctx: Ctx, rec: BotRecord) -> tuple[str, InlineKeyboardMarkup]:
    """What the owner sees once their bot is connected: ready, or waiting for approval."""
    if rec.status == BotStatus.PENDING:
        return ctx.t("cl.pending", username=esc(rec.username)), kb(
            [btn(ctx.t("cl.btn.mybots_short"), MenuCB(screen="mybots"))])
    return ctx.t("cl.ready", username=esc(rec.username)), kb(
        [btn(ctx.t("cl.btn.open", username=rec.username), url=f"https://t.me/{rec.username}", style="success")],
        [btn(ctx.t("cl.btn.mybots_short"), MenuCB(screen="mybots"))],
    )


class _Room:
    """What the user may do on the clone screen right now."""

    def __init__(self, ctx: Ctx, policy: str, count: int, limit: int | None) -> None:
        self.closed = policy == "closed" and not ctx.is_super
        self.full = limit is not None and count >= limit
        self.new_ok = not self.closed and not self.full  # a new bot can be connected
        self.approval = policy == "approval" and not ctx.is_super
        self.token_ok = self.new_ok or count > 0  # 🔑 also re-connects one of the user's bots


async def _room(ctx: Ctx, session: AsyncSession) -> tuple[_Room, int]:
    count = await clones.count_user_bots(session, ctx.user_id)
    limit = await clones.clone_limit(session, ctx.settings, ctx.user_id)
    policy = (await limits.platform(session, ctx.settings)).clone_policy
    return _Room(ctx, policy, count, limit), count


# -------------------------------------------------------------------------- screens
@screen("clone")
async def clone_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                       **_: object) -> None:
    if not ctx.is_main:
        await _show_not_main(event, ctx, session)
        return
    room, count = await _room(ctx, session)
    bot = event.bot
    can_create = room.new_ok and bot is not None and await clones.can_manage_bots(bot)
    parts = [ctx.t("cl.title"), ctx.t("cl.intro")]
    how = []
    if can_create:
        how.append(ctx.t("cl.how.create"))
    if room.token_ok:
        how.append(ctx.t("cl.how.token" if room.new_ok else "cl.how.reconnect"))
    if room.new_ok and await brand.has_photo(session, brand.BOT):
        how.append(ctx.t("cl.photo"))
    if how:
        parts.append("\n".join(how))
    status = [ctx.t("cl.count", count=count, limit=await _limit_text(ctx, session))]
    if room.closed:
        status.append(ctx.t("cl.closed"))
    elif room.full:
        status.append(ctx.t("cl.limit_reached"))
    elif room.approval:
        status.append(ctx.t("cl.approval"))
    parts.append("\n".join(status))
    rows = []
    if can_create:
        user = ctx.user
        suggested = clones.suggest_username(user.username if user else None, user.first_name if user else None,
                                            ctx.user_id)
        name = ctx.t("cl.newbot_name", name=(user.first_name if user and user.first_name else "eMesh"))
        rows.append([btn(ctx.t("cl.btn.create"), url=clones.newbot_url(ctx.bot_rec.username, suggested, name),
                         style="success")])
    if room.token_ok:
        rows.append([btn(ctx.t("cl.btn.token"), CloneCB(action="token"), style="primary")])
    rows.append([btn(ctx.t("cl.btn.mybots", n=count), MenuCB(screen="mybots"))])
    rows.append(back_row(ctx.lang, "home"))
    await show(event, "\n\n".join(parts), kb(*rows))


@screen("mybots")
async def mybots_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                        **_: object) -> None:
    if not ctx.is_main:
        await _show_not_main(event, ctx, session)
        return
    bots = await clones.user_bots(session, ctx.user_id)
    items, page, pages = paginate(bots, arg, MYBOTS_PER_PAGE)
    lines = [ctx.t("cl.mybots.title", count=len(bots), limit=await _limit_text(ctx, session)), ""]
    rows = []
    if not bots:
        lines.append(ctx.t("cl.mybots.empty"))
        rows.append([btn(ctx.t("cl.btn.clone"), MenuCB(screen="clone"), style="success")])
    keys = set()
    for i, rec in enumerate(items, start=page * MYBOTS_PER_PAGE + 1):
        key = clones.status_key(rec)
        keys.add(key)
        lines.append(ctx.t("cl.mybots.row", i=i, username=esc(rec.username), status=ctx.t(f"cl.status.{key}")))
        row = [btn(f"#{i} @{truncate(rec.username, 18)}", url=f"https://t.me/{rec.username}")]
        if key == "active":
            row.append(btn(ctx.t("cl.btn.pause"), CloneCB(action="pause", id=rec.id, page=page)))
        elif key == "paused":
            row.append(btn(ctx.t("cl.btn.resume"), CloneCB(action="resume", id=rec.id, page=page), style="success"))
        if key != "admin":  # disconnecting would lift the super admin's lock
            row.append(btn(ctx.t("cl.btn.remove"), CloneCB(action="remove", id=rec.id, page=page), style="danger"))
        rows.append(row)
    hints = [ctx.t(f"cl.mybots.hint.{key}") for key in ("pending", "invalid") if key in keys]
    if hints:
        lines += ["", *hints]
    if pages > 1:
        lines += ["", ctx.t("common.page", page=page + 1, pages=pages)]
    rows.append(nav_row(page, pages, lambda p: MenuCB(screen="mybots", arg=p), ctx.lang))
    rows.append(back_row(ctx.lang, "home"))
    await show(event, "\n".join(lines), kb(*rows))


# ---------------------------------------------------------------------- token flow
async def _ask_token(event: Message | CallbackQuery, ctx: Ctx, error: str | None = None) -> None:
    text = ctx.t("cl.ask_token")
    await prompt(event, ctx, f"{error}\n\n{text}" if error else text, cancel_screen="clone")


@router.callback_query(CloneCB.filter(F.action == "token"))
async def on_token_start(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not ctx.is_main:
        await alert(call, ctx.t("common.no_permission"))
        return
    room, _ = await _room(ctx, session)
    if not room.token_ok:
        error = ctx.t("cl.err.closed") if room.closed else ctx.t("cl.err.limit",
                                                                    limit=await _limit_text(ctx, session))
        await alert(call, error)
        return
    await state.set_state(CloneFSM.token)
    await _ask_token(call, ctx)


@router.message(CloneFSM.token, F.chat.type == "private", ~F.text.startswith("/"))
async def on_token(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext, bot: Bot,
                   manager: BotManager, settings: Settings, sm: SessionMaker) -> None:
    # The token is a secret: it leaves the chat before anything else (it is never logged nor shown).
    try:
        await message.delete()
    except TelegramAPIError:
        log.debug("The token message of %s could not be deleted", ctx.user_id)
    if not ctx.is_main:
        await state.clear()
        return
    token = (message.text or "").strip()
    if not token:
        await _ask_token(message, ctx, ctx.t("cl.err.text"))
        return
    try:
        rec, is_new = await clones.connect_clone(manager, session, settings, token, ctx.user_id)
    except BotTokenError as exc:
        code = str(exc)
        error = ctx.t(f"cl.err.{code}", limit=await _limit_text(ctx, session))
        if code in FINAL_ERRORS:
            await state.clear()
            await show(message, error, kb(back_row(ctx.lang, "clone")))
        else:
            await _ask_token(message, ctx, error)
        return
    await state.clear()
    await show(message, *_result_view(ctx, rec))
    if rec.status == BotStatus.ACTIVE:
        await give_image(session, manager, sm, rec.id)
    if is_new and ctx.user is not None:
        await clones.notify_new_clone(bot, session, settings, rec, owner_name=ctx.user.full_name,
                                      owner_username=ctx.user.username, managed=False,
                                      markup=approval_markup(rec))


# ---------------------------------------------------------------- Managed Bots
@router.managed_bot(MainBotFilter())
async def on_managed_bot(event: ManagedBotUpdated, bot: Bot, ctx: Ctx, session: AsyncSession,
                         manager: BotManager, settings: Settings, sm: SessionMaker) -> None:
    """A user created (or got a new token for) a bot through our ``t.me/newbot/...`` link."""
    creator, new_bot = event.user, event.bot_user
    username = new_bot.username or str(new_bot.id)
    try:
        token = await bot.get_managed_bot_token(user_id=new_bot.id)
        existing = await session.get(BotRecord, new_bot.id, populate_existing=True)
        if existing is not None and existing.owner_id == creator.id and existing.status == BotStatus.DISABLED:
            # New token of a bot that is stopped (by its owner or a super admin): kept for when it is enabled.
            existing.token_enc = manager.cipher.encrypt(token)
            log.info("New token stored for the stopped managed bot %s", new_bot.id)
            return
        rec, is_new = await clones.connect_clone(manager, session, settings, token, creator.id, managed=True)
    except (TelegramAPIError, BotTokenError) as exc:
        code = str(exc) if isinstance(exc, BotTokenError) else "network"
        log.warning("Managed bot @%s of %s could not be connected: %s", username, creator.id, code)
        text = ctx.t("cl.managed_failed", username=esc(username)) + "\n\n" + ctx.t(
            f"cl.err.{code}", limit=await _limit_text(ctx, session))
        await send_dm(bot, session, creator.id, text, kb([btn(ctx.t("cl.btn.clone"), MenuCB(screen="clone"))]))
        return
    await send_dm(bot, session, creator.id, *_result_view(ctx, rec))
    if rec.status == BotStatus.ACTIVE:
        await give_image(session, manager, sm, rec.id)
    if is_new:
        await clones.notify_new_clone(bot, session, settings, rec, owner_name=creator.full_name,
                                      owner_username=creator.username, managed=True, markup=approval_markup(rec))


# ------------------------------------------------------------------------ Mis bots
async def _own_bot(call: CallbackQuery, ctx: Ctx, session: AsyncSession, bot_id: int,
                   page: int) -> BotRecord | None:
    """A clone of the user (never someone else's, even for a super admin: they use the 👑 panel)."""
    rec = await session.get(BotRecord, bot_id, populate_existing=True)
    if not ctx.is_main or (rec is not None and (rec.is_main or rec.owner_id != ctx.user_id)):
        await alert(call, ctx.t("common.no_permission"))
        return None
    if rec is None or clones.is_removed(rec):
        await alert(call, ctx.t("common.not_found"))
        await open_screen("mybots", call, ctx, session, arg=page)
        return None
    return rec


async def _admin_locked(call: CallbackQuery, ctx: Ctx, session: AsyncSession, rec: BotRecord, page: int) -> bool:
    """Disabled by a super admin: only a super admin brings it back (disconnecting would lift the lock too)."""
    if not clones.is_admin_locked(rec):
        return False
    await alert(call, ctx.t("cl.admin_locked"))
    await open_screen("mybots", call, ctx, session, arg=page)
    return True


@router.callback_query(CloneCB.filter(F.action == "pause"))
async def on_pause(call: CallbackQuery, callback_data: CloneCB, ctx: Ctx, session: AsyncSession,
                   manager: BotManager) -> None:
    rec = await _own_bot(call, ctx, session, callback_data.id, callback_data.page)
    if rec is None:
        return
    if rec.status == BotStatus.ACTIVE:
        await toast(call, ctx.t("cl.paused"))  # first: its posts are withdrawn before it stops, it can take a while
        await manager.disable_bot(rec.id, reason=clones.REASON_OWNER)
    await open_screen("mybots", call, ctx, session, arg=callback_data.page)


@router.callback_query(CloneCB.filter(F.action == "resume"))
async def on_resume(call: CallbackQuery, callback_data: CloneCB, ctx: Ctx, session: AsyncSession,
                    manager: BotManager) -> None:
    rec = await _own_bot(call, ctx, session, callback_data.id, callback_data.page)
    if rec is None or await _admin_locked(call, ctx, session, rec, callback_data.page):
        return
    if clones.status_key(rec) == "paused":
        if await manager.enable_bot(rec.id):
            await toast(call, ctx.t("cl.resumed"))
        else:
            await alert(call, ctx.t("cl.resume_failed"))
    await open_screen("mybots", call, ctx, session, arg=callback_data.page)


@router.callback_query(CloneCB.filter(F.action == "remove"))
async def on_remove(call: CallbackQuery, callback_data: CloneCB, ctx: Ctx, session: AsyncSession) -> None:
    rec = await _own_bot(call, ctx, session, callback_data.id, callback_data.page)
    if rec is None or await _admin_locked(call, ctx, session, rec, callback_data.page):
        return
    key = "cl.confirm_withdraw" if rec.status == BotStatus.PENDING else "cl.confirm_remove"
    markup = kb([
        btn(ctx.t("cl.btn.remove_yes"), CloneCB(action="remove_ok", id=rec.id, page=callback_data.page),
            style="danger"),
        btn(ctx.t("common.no"), MenuCB(screen="mybots", arg=callback_data.page)),
    ])
    await show(call, ctx.t(key, username=esc(rec.username)), markup)


@router.callback_query(CloneCB.filter(F.action == "remove_ok"))
async def on_remove_ok(call: CallbackQuery, callback_data: CloneCB, ctx: Ctx, session: AsyncSession,
                       manager: BotManager) -> None:
    rec = await _own_bot(call, ctx, session, callback_data.id, callback_data.page)
    if rec is None or await _admin_locked(call, ctx, session, rec, callback_data.page):
        return
    if rec.status == BotStatus.PENDING:
        # It never ran: the request is withdrawn (a new connection asks for approval again).
        await session.delete(rec)
        await session.flush()
        await toast(call, ctx.t("cl.withdrawn"))
        log.info("Pending clone %s (@%s) withdrawn by its owner %s", rec.id, rec.username, ctx.user_id)
    else:
        await toast(call, ctx.t("cl.removed"))  # first: its posts are withdrawn before it stops, it can take a while
        await manager.disable_bot(rec.id, reason=clones.REASON_REMOVED)
        log.info("Clone %s (@%s) disconnected by its owner %s", rec.id, rec.username, ctx.user_id)
    await open_screen("mybots", call, ctx, session, arg=callback_data.page)
