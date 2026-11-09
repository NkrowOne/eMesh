"""🗺 Timezone picker: continent (America -> region) -> country -> zone, or an IANA name typed by the user.

Admins change the timezone of the network (its frequencies and dates are in it, so every next time is recalculated);
users change their own (dates are shown in it). Telegram doesn't tell bots anyone's timezone, so it is asked once, and
a zone the person already chose anywhere (eButtons, which rules, or eMesh: ``services.zones``) is used instead:

* the owner of a new clone, on the first /start, before the setup wizard and the home (``needs_timezone``);
* a user (partner or visitor) of a bot that runs a network, on the first visit, before the home or the join screen of
  /start join (``must_choose_timezone``; ``timezone`` arg ``ASK_HOME`` / ``ASK_JOIN``; required: no way back).

Every step shows the photo of this menu when a super admin chose one: one image for the whole platform
(``brand.TZ``), set from the picker itself.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.filters import PrivateFilter
from app.bot.routers.settings import with_notice
from app.data.timezones import CONTINENTS, COUNTRIES, countries_of, resolve_zone, utc_offset_label, zone_label
from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import Post
from app.services import audience, brand, freq, zones
from app.ui.common import alert, back_row, btn, grid, kb, nav_row, paginate, prompt, toast
from app.ui.fmt import esc, hm
from app.ui.photos import show_with_photo
from app.ui.screens import open_screen, screen

log = logging.getLogger(__name__)

router = Router(name="timezone")

COUNTRIES_PER_PAGE = 20  # 10 rows of 2: Europe, Asia and Africa fit in 3 pages
ASK_HOME = 1  # ``timezone`` arg: a user's first visit, asked before the home (required: no way back)
ASK_JOIN = 2  # the same, before the join screen of /start join
ORIGINS = {ASK_HOME: "home", ASK_JOIN: "join"}  # first visit: the screen opened once the zone is chosen
AMERICA = ("nam", "cam", "sam")  # regions of America: chosen after tapping 🌎 América
ROOT = ("ame", "eur", "asi", "afr", "oce")  # first screen: "ame" opens the regions above


class StartTimezoneFSM(StatesGroup):
    zone = State()
    photo = State()


class TzCB(CallbackData, prefix="tz"):
    """``c`` countries of continent ``c`` (page ``p``), ``r`` the regions of America, ``k`` country ``k``, ``z`` zone
    ``i`` of country ``k``, ``w`` type a zone, ``m`` / ``x`` set / remove the photo of the menu (super admins).
    ``o``: the first-visit question the picker was opened for (``ORIGINS``; 0 = the settings)."""

    a: str
    c: str = ""
    k: str = ""
    i: int = 0
    p: int = 0
    o: int = 0


def _origin(value: int) -> int:
    return value if value in ORIGINS else 0


def needs_timezone(ctx: Ctx) -> bool:
    """The owner of a new clone hasn't chosen its timezone yet: it is asked before the home."""
    rec = ctx.bot_rec
    return not rec.is_main and not rec.timezone_set and ctx.user_id == rec.owner_id


def needs_user_timezone(ctx: Ctx) -> bool:
    """A user (partner or visitor) of a bot that runs a network who never chose a timezone. Admins and owners see the
    network's zone (``ctx.tz``), so they are never asked."""
    return not ctx.is_hub and not ctx.is_admin and ctx.bu is not None and not ctx.bu.timezone


async def must_choose_timezone(session: AsyncSession, ctx: Ctx) -> bool:
    """Whether to ask this user their timezone now (before the home or the join screen). A zone they already chose
    anywhere (any bot of eMesh, a clone of theirs, eButtons) is stored silently instead: it is asked once in the whole
    ecosystem."""
    if not needs_user_timezone(ctx):
        return False
    zone = await zones.known_zone(session, ctx.settings, ctx.user_id)
    if zone is None:
        return True
    ctx.bu.timezone = zone  # type: ignore[union-attr]  (needs_user_timezone checked it)
    return False


async def adopt_known_zone(session: AsyncSession, ctx: Ctx) -> str | None:
    """The owner of a new clone already chose a zone somewhere: it becomes the network's zone, without asking. None:
    nothing known (the onboarding asks it)."""
    zone = await zones.known_zone(session, ctx.settings, ctx.user_id)
    if zone is not None:
        await _set_network_zone(session, ctx, zone, own=True)
    return zone


async def refresh_schedules(session: AsyncSession, ws_rec: BotRecord) -> None:
    """Recalculates every stored next time of a network after its timezone changed."""
    now = utcnow()
    freq.refresh_bot(ws_rec, now)
    for group in await audience.bot_groups(session, ws_rec.id):
        freq.refresh_group(group, ws_rec.timezone, now)
    for post in (await session.execute(select(Post).where(Post.bot_id == ws_rec.id))).scalars():
        freq.refresh_post(post, ws_rec.timezone, now)


async def _set_network_zone(session: AsyncSession, ctx: Ctx, zone: str, *, own: bool) -> None:
    """The network's zone; ``own``: the owner's first one, which is also theirs (reused in every bot)."""
    ws = ctx.ws_rec
    ws.timezone = zone
    ws.timezone_set = True
    await refresh_schedules(session, ws)
    if own and ctx.bu is not None:
        ctx.bu.timezone = zone


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


# ---------------------------------------------------------------------------------------------------
# The photo of the menu
# ---------------------------------------------------------------------------------------------------
async def _photo(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession) -> str | BufferedInputFile | None:
    """What the bot of ``event`` sends as the photo of this menu (None: there is none)."""
    if event.bot is None:
        return None
    return await brand.photo_for(session, event.bot, brand.TZ, ctx.manager)


async def _remember(session: AsyncSession, event: Message | CallbackQuery, photo: str | BufferedInputFile,
                    sent: Message | None) -> None:
    """A bot without a file id of the photo uploaded it: the file id it got is used from now on."""
    if isinstance(photo, str) or event.bot is None or sent is None or not sent.photo:
        return
    await brand.remember(session, brand.TZ, event.bot.id, sent.photo[-1].file_id, source=brand.source_of(photo))


async def _show(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, text: str,
                markup: InlineKeyboardMarkup) -> None:
    """Every step of the picker, with the photo of the menu when there is one."""
    await show_with_photo(event, ctx, session, brand.TZ, text, markup)


async def _prompt(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, text: str,
                  origin: int = 0) -> None:
    """A text input of the picker: ``prompt`` with the photo of the menu when there is one."""
    photo = await _photo(event, ctx, session)
    if photo is not None:
        try:
            sent = await prompt(event, ctx, text, cancel_screen="timezone", cancel_arg=origin, media_id=photo,
                                media_type="photo")
        except TelegramBadRequest as exc:  # a file id Telegram no longer takes: asked without the photo
            log.warning("The photo of the timezone menu was refused through bot %s: %s", ctx.bot_id, exc)
        else:
            await _remember(session, event, photo, sent)
            return
    await prompt(event, ctx, text, cancel_screen="timezone", cancel_arg=origin)


# ---------------------------------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------------------------------
async def _show_root(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, *, origin: int = 0,
                     notice: str | None = None) -> None:
    onboarding = needs_timezone(ctx)
    first_visit = origin in ORIGINS
    # The owner's onboarding and a user's first visit: chosen from scratch, required (no way back).
    if onboarding:
        parts = [ctx.t("tz.intro.onboarding")]
    elif first_visit:
        parts = [ctx.t("tz.intro.welcome")]
    else:
        parts = [ctx.t("tz.title"), ctx.t("tz.intro.admin" if ctx.is_admin else "tz.intro.user"), _current_line(ctx)]
    parts.append(ctx.t("tz.pick"))
    rows: list[list[InlineKeyboardButton | None]] = [
        [btn(ctx.t(f"tz.cont.{key}"), TzCB(a="r", o=origin) if key == "ame" else TzCB(a="c", c=key, o=origin))]
        for key in ROOT
    ]
    rows.append([btn(ctx.t("tz.btn.write"), TzCB(a="w", o=origin))])
    if not (onboarding or first_visit):
        if ctx.is_super:  # the photo of this menu, the same in every bot
            has_photo = await brand.has_photo(session, brand.TZ)
            rows.append([btn(ctx.t("tz.btn.photo_change" if has_photo else "tz.btn.photo_set"), TzCB(a="m")),
                         btn(ctx.t("tz.btn.photo_del"), TzCB(a="x")) if has_photo else None])
        rows.append(back_row(ctx.lang, "settings"))
    await _show(event, ctx, session, with_notice("\n\n".join(parts), notice), kb(*rows))


async def _show_regions(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, origin: int) -> None:
    rows = [[btn(ctx.t(f"tz.cont.{key}"), TzCB(a="c", c=key, o=origin))] for key in AMERICA]
    rows.append(back_row(ctx.lang, "timezone", origin))
    await _show(event, ctx, session, f"<b>{ctx.t('tz.cont.ame')}</b>\n\n{ctx.t('tz.regions')}", kb(*rows))


async def _show_countries(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, continent: str,
                          page: int, origin: int) -> None:
    chunk, page, pages = paginate(countries_of(continent, ctx.lang), page, COUNTRIES_PER_PAGE)
    buttons = [btn(f"{c.flag} {c.name(ctx.lang)}", TzCB(a="k", c=continent, k=c.code, p=page, o=origin))
               for c in chunk]
    rows = grid(buttons, 2)
    rows.append(nav_row(page, pages, lambda p: TzCB(a="c", c=continent, p=p, o=origin), ctx.lang))
    if continent in AMERICA:
        rows.append([btn(ctx.t("common.back"), TzCB(a="r", o=origin))])
    else:
        rows.append(back_row(ctx.lang, "timezone", origin))
    parts = [f"<b>{ctx.t(f'tz.cont.{continent}')}</b>", ctx.t("tz.countries")]
    if pages > 1:
        parts.append(ctx.t("common.page", page=page + 1, pages=pages))
    await _show(event, ctx, session, "\n\n".join(parts), kb(*rows))


async def _show_zones(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, continent: str, code: str,
                      page: int, origin: int) -> None:
    country = COUNTRIES[code]
    # The onboarding and a first visit: nothing chosen yet, so nothing is ticked.
    current = None if needs_timezone(ctx) or origin in ORIGINS else _current_zone(ctx)[0]
    now = utcnow()
    rows = []
    for index, zone in enumerate(country.zones):
        mark = "✅" if zone == current else "🕐"
        rows.append([btn(f"{mark} {zone_label(zone, ctx.lang)} ({utc_offset_label(zone, now)})",
                         TzCB(a="z", k=code, i=index, o=origin))])
    rows.append([btn(ctx.t("common.back"), TzCB(a="c", c=continent, p=page, o=origin))])
    await _show(event, ctx, session, f"{country.flag} <b>{esc(country.name(ctx.lang))}</b>\n\n{ctx.t('tz.zones')}",
                kb(*rows))


async def _apply_zone(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, zone: str,
                      origin: int) -> None:
    if ctx.is_admin:  # the network's zone
        first = needs_timezone(ctx)
        await _set_network_zone(session, ctx, zone, own=first)
        if first:  # onboarding: on to the home, which opens the setup wizard of a new bot first
            await open_screen("home", event, ctx, session, notice=ctx.t("tz.saved.first", zone=esc(zone)))
        else:
            await open_screen("settings", event, ctx, session, notice=ctx.t("tz.saved.admin", zone=esc(zone)))
    elif ctx.bu is None:
        await open_screen("home", event, ctx, session)
    elif origin in ORIGINS:  # a first visit: on to the screen it was asked for
        ctx.bu.timezone = zone
        await _go_on(event, ctx, session, ORIGINS[origin], ctx.t("tz.saved.welcome", zone=esc(zone)))
    else:
        ctx.bu.timezone = zone
        await open_screen("settings", event, ctx, session, notice=ctx.t("tz.saved.user", zone=esc(zone)))


async def _go_on(event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, target: str, notice: str) -> None:
    """The screen a first-visit question was asked for, with a short confirmation: on top of the home; for the join
    screen, a toast on buttons or a message before the panel on a typed zone (the panel stays at the bottom)."""
    if target == "home":
        await open_screen("home", event, ctx, session, notice=notice)
        return
    if isinstance(event, Message):
        await toast(event, notice)
    await open_screen(target, event, ctx, session)
    if isinstance(event, CallbackQuery):
        await toast(event, notice)


@screen("timezone")
async def timezone_screen(
    event: Message | CallbackQuery, ctx: Ctx, session: AsyncSession, arg: int = 0, **_: object
) -> None:
    """``arg``: 0 the picker (from ⚙️ Ajustes; the onboarding of a new clone's owner), ``ASK_HOME`` / ``ASK_JOIN``
    a user's first visit."""
    await _show_root(event, ctx, session, origin=_origin(arg))


# ---------------------------------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------------------------------
@router.callback_query(TzCB.filter(F.a == "c"))
async def on_continent(
    call: CallbackQuery, callback_data: TzCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    await state.clear()
    origin = _origin(callback_data.o)
    if callback_data.c in CONTINENTS:
        await _show_countries(call, ctx, session, callback_data.c, callback_data.p, origin)
    else:
        await _show_root(call, ctx, session, origin=origin)


@router.callback_query(TzCB.filter(F.a == "r"))
async def on_america(
    call: CallbackQuery, callback_data: TzCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    await state.clear()
    await _show_regions(call, ctx, session, _origin(callback_data.o))


@router.callback_query(TzCB.filter(F.a == "k"))
async def on_country(
    call: CallbackQuery, callback_data: TzCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    await state.clear()
    origin = _origin(callback_data.o)
    country = COUNTRIES.get(callback_data.k)
    if country is None or callback_data.c not in CONTINENTS:
        await _show_root(call, ctx, session, origin=origin)
    elif len(country.zones) == 1:
        await _apply_zone(call, ctx, session, country.zones[0], origin)
    else:
        await _show_zones(call, ctx, session, callback_data.c, country.code, callback_data.p, origin)


@router.callback_query(TzCB.filter(F.a == "z"))
async def on_zone(
    call: CallbackQuery, callback_data: TzCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    await state.clear()
    origin = _origin(callback_data.o)
    country = COUNTRIES.get(callback_data.k)
    if country is None or not 0 <= callback_data.i < len(country.zones):
        await _show_root(call, ctx, session, origin=origin)
        return
    await _apply_zone(call, ctx, session, country.zones[callback_data.i], origin)


@router.callback_query(TzCB.filter(F.a == "w"))
async def on_write(
    call: CallbackQuery, callback_data: TzCB, ctx: Ctx, session: AsyncSession, state: FSMContext
) -> None:
    origin = _origin(callback_data.o)
    await state.set_state(StartTimezoneFSM.zone)
    await state.update_data(tz_origin=origin)
    await _prompt(call, ctx, session, ctx.t("tz.write.prompt"), origin)


@router.message(StartTimezoneFSM.zone, PrivateFilter(), ~F.text.startswith("/"))
async def on_zone_text(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    origin = _origin(data.get("tz_origin") or 0)
    zone = resolve_zone(message.text or "")
    if zone is None:
        await _prompt(message, ctx, session, f"{ctx.t('tz.write.invalid')}\n\n{ctx.t('tz.write.prompt')}", origin)
        return
    await state.clear()
    await _apply_zone(message, ctx, session, zone, origin)


@router.callback_query(TzCB.filter(F.a == "m"))
async def on_photo(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    """🖼 Poner / Cambiar imagen: the photo of this menu, in every bot (super admins)."""
    if not ctx.is_super:
        await alert(call, ctx.t("common.no_permission"))
        return
    await state.set_state(StartTimezoneFSM.photo)
    await _prompt(call, ctx, session, ctx.t("tz.photo.prompt"))


@router.message(StartTimezoneFSM.photo, PrivateFilter(), ~F.text.startswith("/"))
async def on_photo_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not ctx.is_super:
        await state.clear()
        await open_screen("home", message, ctx, session)
        return
    if not message.photo:
        await _prompt(message, ctx, session, f"{ctx.t('tz.photo.invalid')}\n\n{ctx.t('tz.photo.prompt')}")
        return
    await state.clear()
    # Stored with the file id of the bot that received it; the other bots get it through it (brand.photo_for).
    await brand.set_photo(session, brand.TZ, ctx.bot_id, message.photo[-1].file_id)
    await _show_root(message, ctx, session, notice=ctx.t("tz.photo.saved"))


@router.callback_query(TzCB.filter(F.a == "x"))
async def on_photo_delete(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    """🗑 Quitar imagen (super admins)."""
    if not ctx.is_super:
        await alert(call, ctx.t("common.no_permission"))
        return
    await state.clear()
    await brand.clear_photo(session, brand.TZ)
    await _show_root(call, ctx, session)
    await toast(call, ctx.t("tz.photo.deleted"))
