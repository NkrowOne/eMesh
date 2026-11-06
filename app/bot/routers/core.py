"""Generic navigation: MenuCB -> screens, no-op buttons, input cancel, fallbacks and errors."""
from __future__ import annotations

import logging
import time
import traceback

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.ui.callbacks import CloseCB, InputCancelCB, MenuCB, NoopCB
from app.ui.common import toast
from app.ui.fmt import esc
from app.ui.screens import open_screen

log = logging.getLogger(__name__)

router = Router(name="core")
fallback_router = Router(name="fallback")


@router.callback_query(MenuCB.filter())
async def on_menu(call: CallbackQuery, callback_data: MenuCB, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await open_screen(callback_data.screen, call, ctx, session, arg=callback_data.arg)


@router.callback_query(CloseCB.filter())
async def on_close(call: CallbackQuery) -> None:
    if isinstance(call.message, Message):
        try:
            await call.message.delete()
        except TelegramAPIError:
            pass


@router.callback_query(NoopCB.filter())
async def on_noop(call: CallbackQuery) -> None:
    return None


@router.callback_query(InputCancelCB.filter())
async def on_input_cancel(
    call: CallbackQuery, callback_data: InputCancelCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    await state.clear()
    await toast(call, ctx.t("common.cancelled"))
    await open_screen(callback_data.screen, call, ctx, session, arg=callback_data.arg)


@fallback_router.callback_query()
async def on_unknown_callback(call: CallbackQuery, ctx: Ctx) -> None:
    await toast(call, ctx.t("core.expired_button"), alert=False)


@fallback_router.message(F.chat.type == "private")
async def on_unknown_message(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    # Unknown command or unexpected input: leave any half-finished flow so the next message isn't
    # taken as its input.
    await state.clear()
    await open_screen("home", message, ctx, session)


_last_error_report: dict[str, float] = {}


async def on_error(event: ErrorEvent, ctx: Ctx | None = None) -> bool:
    exc = event.exception
    log.error("Handler error: %s", exc, exc_info=exc)
    update = event.update
    call = update.callback_query
    if call is not None and ctx is not None:
        try:
            await toast(call, ctx.t("common.error"), alert=True)
        except Exception:  # noqa: BLE001
            pass
    elif update.message is not None and update.message.chat.type == "private" and ctx is not None:
        try:
            await update.message.answer(ctx.t("common.error"))
        except Exception:  # noqa: BLE001
            pass
    # Report to super admins at most once per minute per error type.
    if ctx is not None:
        key = f"{type(exc).__name__}:{str(exc)[:80]}"
        now = time.monotonic()
        if now - _last_error_report.get(key, 0) > 60:
            _last_error_report[key] = now
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]
            bot = event.update.bot
            if bot is not None:
                for admin_id in ctx.settings.super_admin_ids:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"⚠️ <b>Error</b> en @{esc(ctx.bot_rec.username)}\n<pre>{esc(tb)}</pre>",
                        )
                    except Exception:  # noqa: BLE001
                        pass
    return True
