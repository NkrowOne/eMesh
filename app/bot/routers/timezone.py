"""🗺 Timezone picker: continent -> country -> zone, or an IANA name typed by the user.

Admins change the timezone of the network (its frequencies and dates are in it, so every next time is recalculated);
users change their own (dates are shown in it). The owner of a new clone chooses it on the first /start, before the
home: Telegram doesn't tell bots the timezone of their owner.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.filters import PrivateFilter
from app.data.timezones import CONTINENTS, COUNTRIES, countries_of, resolve_zone, utc_offset_label, zone_label
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import Post
from app.services import audience, freq
from app.ui.common import back_row, btn, grid, kb, nav_row, paginate, prompt, show
from app.ui.fmt import esc, hm
from app.ui.screens import open_screen, screen

router = Router(name="timezone")

COUNTRIES_PER_PAGE = 20  # 10 rows of 2: Europe, Asia and Africa fit in 3 pages


class StartTimezoneFSM(StatesGroup):
    zone = State()


class TzCB(CallbackData, prefix="tz"):
    """``c`` countries of continent ``c`` (page ``p``), ``k`` country ``k``, ``z`` zone ``i`` of country ``k``,
    ``w`` type a zone."""

    a: str
    c: str = ""
    k: str = ""
    i: int = 0
    p: int = 0


def needs_timezone(ctx: Ctx) -> bool:
    """The owner of a new clone hasn't chosen its timezone yet: it is asked before the home."""
    rec = ctx.bot_rec
    return not rec.is_main and not rec.timezone_set and ctx.user_id == rec.owner_id


async def refresh_schedules(session: AsyncSession, ws_rec: BotRecord) -> None:
    """Recalculates every stored next time of a network after its timezone changed."""
    now = utcnow()
    freq.refresh_bot(ws_rec, now)
    for group in await audience.bot_groups(session, ws_rec.id):
        freq.refresh_group(group, ws_rec.timezone, now)
    for post in (await session.execute(select(Post).where(Post.bot_id == ws_rec.id))).scalars():
        freq.refresh_post(post, ws_rec.timezone, now)


def _current_zone(ctx: Ctx) -> tuple[str, bool]:
    """The zone that applies to this user and whether it is just the network's."""
    if ctx.is_admin:
        return ctx.bot_tz, False
    own = ctx.bu.timezone if ctx.bu else None
    return own or ctx.bot_tz, own is None


def _current_line(ctx: Ctx) -> str:
    zone, is_default = _current_zone(ctx)
    now = utcnow()
    return ctx.t("tz.current.default" if is_default else "tz.current", zone=esc(zone),
                 offset=utc_offset_label(zone, now), time=hm(now, zone))


async def _show_root(event: Message | CallbackQuery, ctx: Ctx) -> None:
    onboarding = needs_timezone(ctx)
    intro = ctx.t("tz.intro.onboarding" if onboarding else "tz.intro.admin" if ctx.is_admin else "tz.intro.user")
    # Onboarding: chosen from scratch (it can be anywhere), so no current zone is suggested and there is no way back.
    parts = [ctx.t("tz.title"), intro] if onboarding else [ctx.t("tz.title"), intro, _current_line(ctx)]
    rows: list[list[InlineKeyboardButton]] = [[btn(ctx.t(f"tz.cont.{key}"), TzCB(a="c", c=key))] for key in CONTINENTS]
    rows.append([btn(ctx.t("tz.btn.write"), TzCB(a="w"))])
    if not onboarding:
        rows.append(back_row(ctx.lang, "settings"))
    await show(event, "\n\n".join([*parts, ctx.t("tz.pick")]), kb(*rows))


async def _show_countries(event: Message | CallbackQuery, ctx: Ctx, continent: str, page: int) -> None:
    chunk, page, pages = paginate(countries_of(continent, ctx.lang), page, COUNTRIES_PER_PAGE)
    buttons = [btn(f"{c.flag} {c.name(ctx.lang)}", TzCB(a="k", c=continent, k=c.code, p=page)) for c in chunk]
    rows = grid(buttons, 2)
    rows.append(nav_row(page, pages, lambda p: TzCB(a="c", c=continent, p=p), ctx.lang))
    rows.append(back_row(ctx.lang, "timezone"))
    parts = [f"<b>{ctx.t(f'tz.cont.{continent}')}</b>", ctx.t("tz.countries")]
    if pages > 1:
        parts.append(ctx.t("common.page", page=page + 1, pages=pages))
    await show(event, "\n\n".join(parts), kb(*rows))


async def _show_zones(event: Message | CallbackQuery, ctx: Ctx, continent: str, code: str, page: int) -> None:
    country = COUNTRIES[code]
    current = None if needs_timezone(ctx) else _current_zone(ctx)[0]  # onboarding: nothing chosen yet
    now = utcnow()
    rows = []
    for index, zone in enumerate(country.zones):
        mark = "✅" if zone == current else "🕐"
        rows.append([btn(f"{mark} {zone_label(zone, ctx.lang)} ({utc_offset_label(zone, now)})",
                         TzCB(a="z", k=code, i=index))])
    rows.append([btn(ctx.t("common.back"), TzCB(a="c", c=continent, p=page))])
    await show(event, f"{country.flag} <b>{esc(country.name(ctx.lang))}</b>\n\n{ctx.t('tz.zones')}", kb(*rows))


async def _apply_zone(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, zone: str) -> None:
    if ctx.is_admin:
        first = needs_timezone(ctx)
        ws = ctx.ws_rec
        ws.timezone = zone
        ws.timezone_set = True
        await refresh_schedules(session, ws)
        if first:  # onboarding done: on to the home
            await open_screen("home", event, ctx, session, notice=ctx.t("tz.saved.first", zone=esc(zone)))
        else:
            await open_screen("settings", event, ctx, session, notice=ctx.t("tz.saved.admin", zone=esc(zone)))
    elif ctx.bu is not None:
        ctx.bu.timezone = zone
        await open_screen("settings", event, ctx, session, notice=ctx.t("tz.saved.user", zone=esc(zone)))
    else:
        await open_screen("home", event, ctx, session)


@screen("timezone")
async def timezone_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, **_: object
) -> None:
    await _show_root(event, ctx)


@router.callback_query(TzCB.filter(F.a == "c"))
async def on_continent(call: CallbackQuery, callback_data: TzCB, ctx: Ctx, state: FSMContext) -> None:
    await state.clear()
    if callback_data.c in CONTINENTS:
        await _show_countries(call, ctx, callback_data.c, callback_data.p)
    else:
        await _show_root(call, ctx)


@router.callback_query(TzCB.filter(F.a == "k"))
async def on_country(
    call: CallbackQuery, callback_data: TzCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    await state.clear()
    country = COUNTRIES.get(callback_data.k)
    if country is None or callback_data.c not in CONTINENTS:
        await _show_root(call, ctx)
    elif len(country.zones) == 1:
        await _apply_zone(call, ctx, session, country.zones[0])
    else:
        await _show_zones(call, ctx, callback_data.c, country.code, callback_data.p)


@router.callback_query(TzCB.filter(F.a == "z"))
async def on_zone(
    call: CallbackQuery, callback_data: TzCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    await state.clear()
    country = COUNTRIES.get(callback_data.k)
    if country is None or not 0 <= callback_data.i < len(country.zones):
        await _show_root(call, ctx)
        return
    await _apply_zone(call, ctx, session, country.zones[callback_data.i])


@router.callback_query(TzCB.filter(F.a == "w"))
async def on_write(call: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    await state.set_state(StartTimezoneFSM.zone)
    await prompt(call, ctx, ctx.t("tz.write.prompt"), cancel_screen="timezone")


@router.message(StartTimezoneFSM.zone, PrivateFilter(), ~F.text.startswith("/"))
async def on_zone_text(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    zone = resolve_zone(message.text or "")
    if zone is None:
        await prompt(message, ctx, f"{ctx.t('tz.write.invalid')}\n\n{ctx.t('tz.write.prompt')}",
                     cancel_screen="timezone")
        return
    await state.clear()
    await _apply_zone(message, ctx, session, zone)

