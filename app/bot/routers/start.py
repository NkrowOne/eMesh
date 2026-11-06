"""STUB: replaced by the start module (see docs/ARCHITECTURE.md). A minimal home so the app runs."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.filters import PrivateFilter
from app.ui.common import show
from app.ui.screens import open_screen, screen

router = Router(name="start")


@screen("home")
async def home_screen(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0,
                      **_: object) -> None:
    await show(event, "🕸 eMesh")


@router.message(CommandStart(), PrivateFilter())
async def on_start(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await open_screen("home", message, ctx, session)
