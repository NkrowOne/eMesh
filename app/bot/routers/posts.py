"""📝 Posts ("Mensajes", spec 5.5): the list, the create wizard, the detail panel and its actions (preview, send now,
withdraw, update the published copies, duplicate, pause, delete) and the screens of content, targets, schedule,
options and the default options of new posts. The buttons editor lives in ``post_buttons.py``.

Every row belongs to the workspace (``ctx.ws_id``); only admins of the network get here.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Coroutine
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.db.base import utcnow
from app.db.models import DEFAULT_DELETE_AFTER, ChatGroup, Post, PostStatus, SchedMode
from app.db.session import session_scope
from app.services import audience, content, freq, limits
from app.services import publisher as pubsvc
from app.telegram.context import set_low_priority
from app.telegram.errors import short
from app.ui import fmt
from app.ui.callbacks import MenuCB
from app.ui.common import (
    alert,
    back_row,
    btn,
    choice_label,
    grid,
    kb,
    nav_row,
    paginate,
    prompt,
    show,
    toast,
    toggle_label,
)
from app.ui.screens import open_screen, screen

if TYPE_CHECKING:
    from app.db.models import Bot as BotRecord
    from app.db.session import SessionMaker
    from app.services.publisher import Publisher
    from app.services.scheduler import Scheduler
    from app.telegram.manager import BotManager

log = logging.getLogger(__name__)

router = Router(name="posts")

Event = Message | CallbackQuery
PRIVATE = F.chat.type == "private"
NOT_COMMAND = ~F.text.startswith("/")


# ---------------------------------------------------------------------------------------------
# Callback data and FSM states
# ---------------------------------------------------------------------------------------------
class PoCB(CallbackData, prefix="po"):
    """Posts. ``a`` action, ``id`` post (0 = the default options of new posts), ``v`` value, ``t`` target token."""

    a: str
    id: int = 0
    v: int = 0
    t: str = ""


class PwCB(CallbackData, prefix="pw"):
    """Create wizard."""

    a: str
    v: int = 0
    t: str = ""


class PostsFSM(StatesGroup):
    new_content = State()
    new_buttons = State()
    new_targets = State()
    new_when = State()
    new_date = State()
    new_delete = State()
    content = State()
    text = State()
    name = State()
    send_at = State()
    starts_on = State()
    ends_on = State()
    delete_after = State()


# ---------------------------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------------------------
PAGE = 10
NAME_MAX = 64
TEXT_SHOW_MAX = 300  # the text of a post shown in its content screen
# Groups of chats in the targets of a post: at most this many names (cut) in the list and in the detail, then «+N»
# (a list of 10 posts must fit in one message), and at most this many buttons in the picker (a keyboard holds 100).
TARGET_NAME_MAX = 30
LIST_GROUPS = 2
DETAIL_GROUPS = 10
PICKER_GROUPS = 60  # above groups.MAX_GROUPS: a network may have more groups from before that limit
STATUS_ICON = {PostStatus.ACTIVE: "▶️", PostStatus.PAUSED: "⏸", PostStatus.DONE: "✅"}
MODE_ICON = {SchedMode.ROTATION: "🔁", SchedMode.OWN: "⏰", SchedMode.ONCE: "📢", SchedMode.MANUAL: "✋"}
MODES = (SchedMode.ROTATION, SchedMode.OWN, SchedMode.ONCE, SchedMode.MANUAL)
OPTIONS = ("pin", "silent", "protect", "link_preview", "caption_above", "spoiler", "delete_previous")
DEFAULT_OPTIONS = ("pin", "silent", "protect", "link_preview", "delete_previous")  # Bot.post_defaults (+ delete_after)
OPTION_DEFAULTS: dict[str, Any] = {"pin": False, "silent": False, "protect": False, "link_preview": False,
                                   "caption_above": False, "spoiler": False, "delete_previous": True,
                                   "delete_after": DEFAULT_DELETE_AFTER}
AUTO_DELETE = (0, 60, 180, 360, 720, 1440, 2880)  # minutes (0 = never)
DAY = 1440  # minutes: auto delete choices of whole days read «1 día», «2 días»
MIN_DELETE_AFTER = 15
MAX_DELETE_AFTER = 2880  # Telegram doesn't let bots delete messages older than 48 h
COPY_FIELDS = ("kind", "text", "media_name", "mode", "send_at", "starts_on", "ends_on", *OPTIONS, "delete_after")


# ---------------------------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------------------------
def with_notice(text: str, notice: str | None) -> str:
    return f"{notice}\n\n{text}" if notice else text


async def deny(event: Event, ctx: Ctx) -> None:
    await alert(event, ctx.t("common.no_permission"))


async def expired(event: Event, ctx: Ctx) -> None:
    await toast(event, ctx.t("core.expired_button"))


async def can_manage(event: Event, ctx: Ctx, session: AsyncSession) -> bool:
    """Admins of the network only (the hub main bot runs no network: its home instead)."""
    if not ctx.is_admin:
        await deny(event, ctx)
        return False
    if ctx.is_hub:
        await open_screen("home", event, ctx, session)
        return False
    return True


async def load_post(session: AsyncSession, ctx: Ctx, post_id: int) -> Post | None:
    if post_id <= 0:
        return None
    post = await session.get(Post, post_id)
    return post if post is not None and post.bot_id == ctx.ws_id else None


async def admin_post(event: Event, ctx: Ctx, session: AsyncSession, post_id: int,
                     state: FSMContext | None = None) -> Post | None:
    """The post of an admin action, or None after telling the user why it can't be used. With ``state``, any
    half-finished text input is dropped (a button of another panel was pressed)."""
    if not await can_manage(event, ctx, session):
        return None
    if state is not None:
        await state.clear()
    post = await load_post(session, ctx, post_id)
    if post is None:
        await alert(event, ctx.t("common.not_found"))
        await render_posts(event, ctx, session)
    return post


async def state_post(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> Post | None:
    """The post of a text input (its id is in the FSM data); the input ends when the post can't be used."""
    data = await state.get_data()
    post = await admin_post(message, ctx, session, _int(data.get("id")))
    if post is None:
        await state.clear()
    return post


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def limit_text(ctx: Ctx, session: AsyncSession) -> str:
    return ctx.t("po.limit", max=await limits.max_posts(session, ctx.settings, ctx.ws_rec))


def refresh(post: Post, ctx: Ctx, scheduler: Scheduler) -> None:
    """After every schedule change: the next send of own / once posts, and the scheduler looks again."""
    freq.refresh_post(post, ctx.bot_tz, utcnow())
    scheduler.wake()


_tasks: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any]) -> None:
    """Runs ``coro`` in the background (low priority), keeping a reference to the task."""
    async def run() -> None:
        set_low_priority()
        try:
            await coro
        except Exception:  # noqa: BLE001
            log.exception("Background task of the posts module failed")

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def drop_panel(event: Event) -> None:
    """Deletes the panel a button belongs to (before it is sent again below newer messages)."""
    if isinstance(event, CallbackQuery) and isinstance(event.message, Message):
        try:
            await event.message.delete()
        except TelegramAPIError:
            pass


def fsm_context(event: Event, ctx: Ctx) -> FSMContext | None:
    """The FSM context of the user's private chat, for a screen opened without one (``MenuCB``)."""
    bot = event.bot
    if ctx.manager is None or bot is None or not ctx.user_id:
        return None
    return ctx.manager.dp.fsm.get_context(bot=bot, chat_id=ctx.user_id, user_id=ctx.user_id)


# ---------------------------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------------------------
def kind_icon(kind: str) -> str:
    return content.kind_label(kind, "es").split(" ", 1)[0]


def day_text(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "—"


def short_dt(ctx: Ctx, value: datetime | None) -> str:
    return fmt.to_local(value, ctx.tz).strftime("%d/%m %H:%M") if value else "—"


def delete_after_text(ctx: Ctx, minutes: int) -> str:
    return ctx.t("po.ad.after", t=freq.every_text(minutes, ctx.lang)) if minutes else ctx.t("po.ad.never")


def auto_delete_label(ctx: Ctx, minutes: int) -> str:
    """A choice of the auto delete: ``Nunca``, ``6 h``, ``1 día``, ``2 días``, ``1 h 30 min``."""
    if not minutes:
        return ctx.t("po.ad.b.never")
    if minutes % DAY == 0:
        return units(ctx, minutes // DAY, "days")
    return freq.every_text(minutes, ctx.lang)


def units(ctx: Ctx, n: int, name: str) -> str:
    """``12 chats`` / ``1 chat`` (i18n ``po.unit.<name>`` and its singular ``po.unit.<name>.1``)."""
    return ctx.t(f"po.unit.{name}.1" if n == 1 else f"po.unit.{name}", n=fmt.num(n))


def buttons_text(ctx: Ctx, rows: Any) -> str:
    n = content.count_buttons(rows)
    return ctx.t("po.d.buttons", buttons=units(ctx, n, "buttons")) if n else ctx.t("po.d.no_buttons")


def campaign_text(ctx: Ctx, post: Post) -> str | None:
    if post.starts_on and post.ends_on:
        return ctx.t("po.camp.both", start=day_text(post.starts_on), end=day_text(post.ends_on))
    if post.starts_on:
        return ctx.t("po.camp.from", start=day_text(post.starts_on))
    if post.ends_on:
        return ctx.t("po.camp.to", end=day_text(post.ends_on))
    return None


async def groups_by_id(session: AsyncSession, ctx: Ctx) -> dict[int, ChatGroup]:
    return {g.id: g for g in await audience.bot_groups(session, ctx.ws_id)}


def targets_text(ctx: Ctx, tokens: list[str] | None, groups: dict[int, ChatGroup], *, icons: bool = True,
                 max_groups: int = DETAIL_GROUPS) -> str:
    """``🌐 Todos`` / ``🏠 Propios, 🗂 Cine`` / ``🗂 Cine, 🗂 Series +3 más``: the names of at most ``max_groups``
    groups of chats, cut when long (empty when it targets nobody)."""
    virtual, group_ids = audience.split_targets(tokens)
    prefix = "po.tgs." if icons else "po.tgl."
    parts = [ctx.t(prefix + token) for token in audience.VIRTUAL if token in virtual]
    names = [groups[g].name for g in sorted(group_ids) if g in groups]
    parts += [("🗂 " if icons else "") + fmt.esc(fmt.truncate(name, TARGET_NAME_MAX)) for name in names[:max_groups]]
    more = len(names) - max_groups
    return ", ".join(parts) + (ctx.t("po.tg.more", n=more) if more > 0 else "")


# ---------------------------------------------------------------------------------------------
# Targets (wizard step 3 and the 🎯 Destino screen)
# ---------------------------------------------------------------------------------------------
def valid_token(token: str, group_ids: set[int]) -> bool:
    if token in audience.VIRTUAL:
        return True
    return token.startswith("g") and token[1:].isdigit() and int(token[1:]) in group_ids


def clean_targets(tokens: Any, group_ids: set[int]) -> list[str]:
    virtual, groups = audience.split_targets(tokens if isinstance(tokens, list) else [])
    return audience.make_targets(virtual, groups & group_ids)


def toggle_target(tokens: list[str] | None, token: str, group_ids: set[int]) -> list[str]:
    """The targets after tapping ``token``: 🌐 Todos alone, or a combination of the others (picking one of them
    drops 🌐 Todos). The result may be empty: the callers refuse it."""
    virtual, groups = audience.split_targets(tokens)
    groups &= group_ids
    if token == audience.ALL:
        return [] if audience.ALL in virtual else [audience.ALL]
    virtual.discard(audience.ALL)
    if token in audience.VIRTUAL:
        virtual ^= {token}
    else:
        groups ^= {int(token[1:])}
    return audience.make_targets(virtual, groups)


async def targets_block(ctx: Ctx, session: AsyncSession, tokens: list[str]) -> str:
    chats, members = await audience.targets_size(session, ctx.ws_id, list(tokens))
    lines = [ctx.t("po.tg.hint"), "", ctx.t("po.tg.count", chats=units(ctx, chats, "chats"), members=fmt.num(members)),
             ctx.t("po.tg.count_hint")]
    return "\n".join(lines)


async def target_rows(ctx: Ctx, session: AsyncSession, tokens: list[str],
                      make_cb: Callable[[str], CallbackData]) -> list[list[InlineKeyboardButton]]:
    virtual, group_ids = audience.split_targets(tokens)
    rows = [
        [btn(choice_label(ctx.t("po.tg.all"), audience.ALL in virtual), make_cb(audience.ALL))],
        [btn(choice_label(ctx.t(f"po.tg.{token}"), token in virtual), make_cb(token))
         for token in (audience.OWN, audience.EXT)],
    ]
    counts = await audience.group_counts(session, ctx.ws_id)
    shown = await audience.bot_groups(session, ctx.ws_id)
    if len(shown) > PICKER_GROUPS:  # the chosen ones always show (they can be unchosen)
        shown = sorted(shown, key=lambda g: g.id not in group_ids)[:PICKER_GROUPS]
    groups = [
        btn(fmt.truncate(choice_label(ctx.t("po.tg.group", name=g.name, n=counts.get(g.id, 0)), g.id in group_ids), 64),
            make_cb(audience.group_token(g.id)))
        for g in shown
    ]
    return rows + grid(groups, 2)


# ---------------------------------------------------------------------------------------------
# Options (⚙️ Opciones of a post and the defaults of new posts)
# ---------------------------------------------------------------------------------------------
def option_names(kind: str | None) -> list[str]:
    """Toggles that apply to a post of this kind (None: the default options of new posts)."""
    if kind is None:
        return list(DEFAULT_OPTIONS)
    names = ["pin", "silent", "protect"]
    if kind == "text":
        names.append("link_preview")
    if kind in content.VISUAL_KINDS:
        names += ["caption_above", "spoiler"]
    names.append("delete_previous")
    return names


def clean_minutes(value: Any) -> int:
    minutes = _int(value)
    return minutes if 0 <= minutes <= MAX_DELETE_AFTER else 0


def defaults_of(ws_rec: BotRecord) -> dict[str, Any]:
    """The default options of new posts (``Bot.post_defaults``, missing keys take the model defaults: deleted after
    one day)."""
    stored = ws_rec.post_defaults if isinstance(ws_rec.post_defaults, dict) else {}
    values: dict[str, Any] = {name: bool(stored.get(name, OPTION_DEFAULTS[name])) for name in DEFAULT_OPTIONS}
    minutes = stored.get("delete_after")
    values["delete_after"] = clean_minutes(DEFAULT_DELETE_AFTER if minutes is None else minutes)
    return values


def apply_defaults(post: Post, ws_rec: BotRecord) -> None:
    for name, value in {**OPTION_DEFAULTS, **defaults_of(ws_rec)}.items():
        setattr(post, name, value)


def option_values(ctx: Ctx, post: Post | None) -> dict[str, Any]:
    if post is None:
        return defaults_of(ctx.ws_rec)
    return {name: getattr(post, name) for name in (*OPTIONS, "delete_after")}


def save_option(ctx: Ctx, post: Post | None, name: str, value: Any) -> None:
    if post is None:
        ctx.ws_rec.post_defaults = {**defaults_of(ctx.ws_rec), name: value}  # a new dict: JSON column
    else:
        setattr(post, name, value)


def options_lines(ctx: Ctx, values: dict[str, Any], names: list[str], *, hints: bool) -> list[str]:
    lines: list[str] = []
    for name in (*names, "delete_after"):
        if name == "delete_after":
            value = delete_after_text(ctx, clean_minutes(values.get(name)))
        else:
            value = fmt.onoff(bool(values.get(name)))
        lines.append(ctx.t(f"po.o.{name}", v=value))
        if hints:
            lines.append(ctx.t(f"po.oh.{name}"))
    return lines


_UNITS_RE = re.compile(r"(?:(?P<h>\d+(?:\.\d+)?)(?:h|hr|hrs|hora|horas|hour|hours))?"
                       r"(?:(?P<m>\d+)(?:m|min|mins|minuto|minutos|minute|minutes)?)?")
_NEVER = {"0", "no", "nunca", "never"}


def parse_minutes(text: str) -> int:
    """Auto delete time: ``45 min``, ``2 h``, ``1h30``, ``1:30``, ``1.5 h``, ``36`` (a bare number up to 48 is hours,
    a bigger one minutes); ``0`` = never. Raises ValueError(i18n key)."""
    raw = (text or "").strip().lower().replace(",", ".")
    if raw in _NEVER:
        return 0
    minutes: float
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        value = float(raw)
        minutes = value * 60 if value <= MAX_DELETE_AFTER // 60 else value
    elif m := re.fullmatch(r"(\d{1,2}):(\d{2})", raw):
        minutes = int(m.group(1)) * 60 + int(m.group(2))
    else:
        m = _UNITS_RE.fullmatch(re.sub(r"\s+|\by\b|\band\b", "", raw))
        if not m or not (m.group("h") or m.group("m")):
            raise ValueError("po.err.duration")
        minutes = float(m.group("h") or 0) * 60 + float(m.group("m") or 0)
    # A huge number is inf (float() doesn't overflow): out of range, before int() is tried.
    if not MIN_DELETE_AFTER <= minutes <= MAX_DELETE_AFTER or minutes != int(minutes):
        raise ValueError("po.err.duration_range")
    return int(minutes)


def parse_when(ctx: Ctx, message: Message) -> tuple[datetime | None, str | None]:
    """``(date and time of a one-time send, error)`` (bot timezone)."""
    if not message.text:
        return None, ctx.t("po.err.text_only")
    try:
        return freq.parse_datetime(message.text, ctx.bot_tz, utcnow()), None
    except (ValueError, OverflowError) as exc:  # OverflowError: a date at the end of the calendar
        key = str(exc) if str(exc) in ("freq.err.datetime", "freq.err.past") else "freq.err.datetime"
        return None, ctx.t(key)


# ---------------------------------------------------------------------------------------------
# Screens: list and detail
# ---------------------------------------------------------------------------------------------
async def render_posts(event: Event, ctx: Ctx, session: AsyncSession, page: int = 0, *, hide: int = 0,
                       notice: str | None = None) -> None:
    """``hide``: a post being deleted in the background."""
    rows = (await session.execute(select(Post).where(Post.bot_id == ctx.ws_id).order_by(Post.id))).scalars().all()
    posts = sorted((p for p in rows if p.id != hide), key=lambda p: p.status == PostStatus.DONE)  # done ones last
    items, page, pages = paginate(posts, page, PAGE)
    groups = await groups_by_id(session, ctx)
    lines: list[str] = []
    for n, post in enumerate(items, page * PAGE + 1):
        if post.mode in (SchedMode.OWN, SchedMode.ONCE) and post.next_send_at is not None:
            extra = ctx.t("po.list.next", date=fmt.dt(post.next_send_at, ctx.tz))
        else:
            extra = ctx.t("po.list.runs", sends=units(ctx, post.runs_count or 0, "sends"))
        lines.append(ctx.t(
            "po.list.item", n=n, status=STATUS_ICON.get(post.status, "▶️"), mode=MODE_ICON.get(post.mode, "🔁"),
            name=fmt.esc(post.name), kind=kind_icon(post.kind),
            targets=targets_text(ctx, post.targets, groups, icons=False, max_groups=LIST_GROUPS) or ctx.t("po.tg.none"),
            extra=extra))
    parts = [ctx.t("po.list.title") + "\n" + ctx.t("po.list.legend"),
             "\n".join(lines) if lines else ctx.t("po.list.empty")]
    if pages > 1:
        parts.append(ctx.t("common.page", page=page + 1, pages=pages))
    buttons = [btn(fmt.truncate(f"#{n} {post.name}", 64), MenuCB(screen="post", arg=post.id))
               for n, post in enumerate(items, page * PAGE + 1)]
    markup = kb(
        *grid(buttons, 2),
        [btn(ctx.t("po.btn.new"), PwCB(a="start"), style="success")],
        [btn(ctx.t("po.btn.defaults"), MenuCB(screen="post_defaults"))],
        nav_row(page, pages, lambda p: MenuCB(screen="posts", arg=p), ctx.lang),
        back_row(ctx.lang, "home"),
    )
    await show(event, with_notice("\n\n".join(parts), notice), markup)


@screen("posts")
async def posts_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    if await can_manage(event, ctx, session):
        await render_posts(event, ctx, session, arg, notice=kw.get("notice"))


def mode_lines(ctx: Ctx, post: Post) -> list[str]:
    mode = post.mode if post.mode in MODES else SchedMode.ROTATION
    if mode == SchedMode.OWN:
        value = ctx.t("po.dm.own", freq=freq.describe(post.freq, ctx.lang))
    elif mode == SchedMode.ONCE:
        value = ctx.t("po.dm.once", date=fmt.dt(post.send_at, ctx.tz))
    else:
        value = ctx.t(f"po.dm.{mode}")
    return [ctx.t("po.d.mode", value=value), ctx.t(f"po.dh.{mode}")]


async def detail_text(ctx: Ctx, session: AsyncSession, post: Post) -> tuple[str, int]:
    """The detail panel and how many copies are published right now."""
    groups = await groups_by_id(session, ctx)
    status = post.status if post.status in STATUS_ICON else PostStatus.ACTIVE
    lines = [
        ctx.t("po.d.title", name=fmt.esc(post.name)),
        ctx.t("po.d.status", value=ctx.t(f"po.st.{status}")),
        ctx.t("po.d.kind", kind=content.kind_label(post.kind, ctx.lang), buttons=buttons_text(ctx, post.buttons)),
    ]
    targets = targets_text(ctx, post.targets, groups)
    if targets:
        chats, members = await audience.audience_size(session, post)
        lines.append(ctx.t("po.d.targets", targets=targets, chats=units(ctx, chats, "chats"), members=fmt.num(members)))
    else:
        lines.append(ctx.t("po.d.no_targets"))
    lines += mode_lines(ctx, post)
    if post.mode in (SchedMode.OWN, SchedMode.ONCE):
        lines.append(ctx.t("po.d.next", date=fmt.dt(post.next_send_at, ctx.tz)))
    campaign = campaign_text(ctx, post)
    if campaign:
        lines.append(ctx.t("po.d.campaign", value=campaign))
    if post.runs_count:
        lines.append(ctx.t("po.d.sent", times=units(ctx, post.runs_count, "times"),
                           deliveries=units(ctx, post.sent_count or 0, "deliveries"),
                           last=fmt.dt(post.last_sent_at, ctx.tz)))
    else:
        lines.append(ctx.t("po.d.never"))
    live = await pubsvc.live_count(session, post.id)
    if live:
        lines.append(ctx.t("po.d.live", chats=units(ctx, live, "chats")))
    options = options_lines(ctx, option_values(ctx, post), option_names(post.kind), hints=False)
    quote = "<blockquote expandable>" + "\n".join([ctx.t("po.d.opts"), *options]) + "</blockquote>"
    return "\n".join(lines) + "\n" + quote, live


def detail_markup(ctx: Ctx, post: Post, live: int) -> InlineKeyboardMarkup:
    pid = post.id
    stopped = post.status != PostStatus.ACTIVE
    return kb(
        [btn(ctx.t("po.b.preview"), PoCB(a="prev", id=pid)), btn(ctx.t("po.b.send"), PoCB(a="send", id=pid))],
        [btn(ctx.t("po.b.content"), MenuCB(screen="post_content", arg=pid)),
         btn(ctx.t("po.b.buttons"), MenuCB(screen="post_buttons", arg=pid))],
        [btn(ctx.t("po.b.targets"), MenuCB(screen="post_targets", arg=pid)),
         btn(ctx.t("po.b.sched"), MenuCB(screen="post_sched", arg=pid))],
        [btn(ctx.t("po.b.opts"), MenuCB(screen="post_opts", arg=pid)), btn(ctx.t("po.b.dup"), PoCB(a="dup", id=pid))],
        [btn(ctx.t("po.b.update", n=live), PoCB(a="upd", id=pid)),
         btn(ctx.t("po.b.retire", n=live), PoCB(a="ret", id=pid))] if live else None,
        [btn(ctx.t("po.b.play" if stopped else "po.b.pause"), PoCB(a="play" if stopped else "pause", id=pid),
             style="success" if stopped else None),
         btn(ctx.t("po.b.delete"), PoCB(a="del", id=pid), style="danger")],
        back_row(ctx.lang, "posts"),
    )


async def render_post(event: Event, ctx: Ctx, session: AsyncSession, post: Post, *, notice: str | None = None,
                      new: bool = False) -> None:
    """The detail panel. ``new`` sends it again below newer messages (after a preview)."""
    text, live = await detail_text(ctx, session, post)
    if new:
        await drop_panel(event)
    await show(event, with_notice(text, notice), detail_markup(ctx, post, live), new=new)


@screen("post")
async def post_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    post = await admin_post(event, ctx, session, arg)
    if post is not None:
        await render_post(event, ctx, session, post, notice=kw.get("notice"))


# ---------------------------------------------------------------------------------------------
# Detail actions
# ---------------------------------------------------------------------------------------------
async def send_preview(call: CallbackQuery, ctx: Ctx, post: Post, manager: BotManager | None,
                       sm: SessionMaker | None) -> bool:
    """👁 The real message, with its buttons, in the user's private chat. False (and an alert) when it failed."""
    try:
        await content.send_post(call.bot, ctx.user_id, post, manager, sm)
    except content.MediaError as exc:
        reason = str(exc) if str(exc) in ("too_big", "unavailable") else "unavailable"
        await alert(call, ctx.t(f"content.err.media_{reason}"))
        return False
    except TelegramAPIError as exc:
        log.warning("Preview of post %s failed: %s", post.id, short(exc))
        await alert(call, ctx.t("po.preview.failed"))
        return False
    return True


@router.callback_query(PoCB.filter(F.a == "prev"))
async def on_preview(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
                     manager: BotManager, sm: SessionMaker) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is not None and await send_preview(call, ctx, post, manager, sm):
        await render_post(call, ctx, session, post, new=True)


def confirm_markup(ctx: Ctx, post: Post, yes: InlineKeyboardButton) -> InlineKeyboardMarkup:
    return kb([yes, btn(ctx.t("po.no"), MenuCB(screen="post", arg=post.id))])


@router.callback_query(PoCB.filter(F.a == "send"))
async def on_send(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
                  publisher: Publisher) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return
    if publisher.is_busy(post.id):
        await alert(call, ctx.t("po.busy"))
        return
    if ctx.ws_rec.paused:
        await alert(call, ctx.t("po.send.paused"))
        return
    chats, members = await audience.audience_size(session, post)
    if not chats:
        await alert(call, ctx.t("po.send.nobody"))
        return
    yes = btn(ctx.t("po.send.yes"), PoCB(a="send_ok", id=post.id), style="success")
    await show(call, ctx.t("po.send.confirm", name=fmt.esc(post.name), chats=units(ctx, chats, "chats"),
                     members=fmt.num(members)),
               confirm_markup(ctx, post, yes))


@router.callback_query(PoCB.filter(F.a == "send_ok"))
async def on_send_confirm(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                          state: FSMContext, publisher: Publisher) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return
    if publisher.is_busy(post.id):
        await alert(call, ctx.t("po.busy"))
    elif ctx.ws_rec.paused:
        await alert(call, ctx.t("po.send.paused"))
    elif await publisher.send_now(post.id, user_id=ctx.user_id) is None:
        await alert(call, ctx.t("po.busy" if publisher.is_busy(post.id) else "po.send.nobody"))
    else:
        log.info("Post %s sent now by %s", post.id, ctx.user_id)
        await toast(call, ctx.t("po.send.started"))
    await render_post(call, ctx, session, post)


async def live_post(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext, publisher: Publisher,
                    post_id: int) -> tuple[Post, int] | None:
    """The post for 🔚 / 🔄 (something published and no send running), or None after telling why not."""
    post = await admin_post(call, ctx, session, post_id, state)
    if post is None:
        return None
    if publisher.is_busy(post.id):
        await alert(call, ctx.t("po.busy"))
        return None
    live = await pubsvc.live_count(session, post.id)
    if not live:
        await alert(call, ctx.t("po.nothing_live"))
        await render_post(call, ctx, session, post)
        return None
    return post, live


@router.callback_query(PoCB.filter(F.a.in_({"ret", "upd"})))
async def on_live_action(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
                         publisher: Publisher) -> None:
    found = await live_post(call, ctx, session, state, publisher, callback_data.id)
    if found is None:
        return
    post, live = found
    if callback_data.a == "ret":
        text = ctx.t("po.retire.confirm", name=fmt.esc(post.name), chats=units(ctx, live, "chats"))
        yes = btn(ctx.t("po.retire.yes"), PoCB(a="ret_ok", id=post.id), style="danger")
    else:
        text = ctx.t("po.update.confirm", name=fmt.esc(post.name), copies=units(ctx, live, "copies"))
        yes = btn(ctx.t("po.update.yes"), PoCB(a="upd_ok", id=post.id), style="success")
    await show(call, text, confirm_markup(ctx, post, yes))


@router.callback_query(PoCB.filter(F.a.in_({"ret_ok", "upd_ok"})))
async def on_live_action_confirm(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                                 state: FSMContext, publisher: Publisher) -> None:
    found = await live_post(call, ctx, session, state, publisher, callback_data.id)
    if found is None:
        return
    post, _ = found
    if callback_data.a == "ret_ok":
        log.info("Post %s withdrawn by %s", post.id, ctx.user_id)
        spawn(publisher.retire(post.id))
        await toast(call, ctx.t("po.retire.started"))
    else:
        log.info("Published copies of post %s updated by %s", post.id, ctx.user_id)
        spawn(publisher.update_live(post.id))
        await toast(call, ctx.t("po.update.started"))
    await render_post(call, ctx, session, post)


def copy_name(ctx: Ctx, name: str) -> str:
    """``Promo Cine (copia)``, cut so it fits the 64 characters of the name."""
    full = ctx.t("po.dup.name", name=name)
    if len(full) <= NAME_MAX:
        return full
    return ctx.t("po.dup.name", name=fmt.truncate(name, max(1, NAME_MAX - (len(full) - len(name)))))


@router.callback_query(PoCB.filter(F.a == "dup"))
async def on_duplicate(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                       state: FSMContext) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return
    if not await limits.can_add_post(session, ctx.settings, ctx.ws_rec):
        await alert(call, await limit_text(ctx, session))
        return
    # Paused, so nothing is sent before the copy is reviewed.
    copy = Post(bot_id=post.bot_id, name=copy_name(ctx, post.name), status=PostStatus.PAUSED, created_by=ctx.user_id,
                media=dict(post.media or {}), buttons=content.clean_rows(post.buttons),
                targets=list(post.targets or []), freq=dict(post.freq) if post.freq else None)
    for name in COPY_FIELDS:
        setattr(copy, name, getattr(post, name))
    session.add(copy)
    await session.flush()
    freq.refresh_post(copy, ctx.bot_tz, utcnow())
    log.info("Post %s duplicated as %s by %s", post.id, copy.id, ctx.user_id)
    await toast(call, ctx.t("po.dup.done"))
    await render_post(call, ctx, session, copy)


@router.callback_query(PoCB.filter(F.a == "del"))
async def on_delete(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                    state: FSMContext) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return
    live = await pubsvc.live_count(session, post.id)
    text = ctx.t("po.del.confirm", name=fmt.esc(post.name))
    if live:
        text += "\n\n" + ctx.t("po.del.live", chats=units(ctx, live, "chats"))
        rows = [[btn(ctx.t("po.del.all", n=live), PoCB(a="del_all", id=post.id), style="danger")],
                [btn(ctx.t("po.del.only"), PoCB(a="del_one", id=post.id), style="danger")]]
    else:
        rows = [[btn(ctx.t("po.del.yes"), PoCB(a="del_one", id=post.id), style="danger")]]
    await show(call, text, kb(*rows, [btn(ctx.t("po.no"), MenuCB(screen="post", arg=post.id))]))


async def _withdraw_and_delete(publisher: Publisher, sm: SessionMaker, post_id: int) -> None:
    await publisher.retire(post_id)
    async with session_scope(sm) as s:
        post = await s.get(Post, post_id)
        if post is not None:
            await s.delete(post)


@router.callback_query(PoCB.filter(F.a.in_({"del_one", "del_all"})))
async def on_delete_confirm(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                            state: FSMContext, publisher: Publisher, sm: SessionMaker) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return
    if publisher.is_busy(post.id):
        await alert(call, ctx.t("po.busy"))
        return
    log.info("Post %s (%s) deleted by %s (%s)", post.id, post.name, ctx.user_id, callback_data.a)
    if callback_data.a == "del_all":
        # Nothing new is sent meanwhile; the row goes once its copies are withdrawn (their deliveries need it).
        post.status = PostStatus.PAUSED
        post.next_send_at = None
        await session.commit()
        spawn(_withdraw_and_delete(publisher, sm, post.id))
        await toast(call, ctx.t("po.del.retiring"))
        await render_posts(call, ctx, session, hide=post.id)
        return
    await session.delete(post)  # the copies already sent stay (their auto delete still happens)
    await session.flush()
    await toast(call, ctx.t("po.del.done"))
    await render_posts(call, ctx, session)


@router.callback_query(PoCB.filter(F.a.in_({"pause", "play"})))
async def on_pause(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
                   scheduler: Scheduler) -> None:
    """``pause`` / ``play`` (not a toggle): a double tap doesn't undo the first one."""
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return
    now = utcnow()
    if callback_data.a == "pause":
        if post.status == PostStatus.ACTIVE:
            post.status = PostStatus.PAUSED
            refresh(post, ctx, scheduler)
        await toast(call, ctx.t("po.paused"))
        await render_post(call, ctx, session, post)
        return
    if post.status != PostStatus.ACTIVE:
        if freq.ended(post, ctx.bot_tz, now):
            await alert(call, ctx.t("po.ended"))
            return
        if post.status == PostStatus.DONE and not await limits.can_add_post(session, ctx.settings, ctx.ws_rec):
            await alert(call, await limit_text(ctx, session))
            return
        if post.mode == SchedMode.ONCE and (post.send_at is None or post.send_at <= now):
            await ask_send_at(call, ctx, state, post, activate=True)
            return
        post.status = PostStatus.ACTIVE
        refresh(post, ctx, scheduler)
    await toast(call, ctx.t("po.activated"))
    await render_post(call, ctx, session, post)


# ---------------------------------------------------------------------------------------------
# Create wizard (the row is only created at the end)
# ---------------------------------------------------------------------------------------------
WIZARD_PREVIOUS: dict[str, State] = {
    PostsFSM.new_buttons.state: PostsFSM.new_content,
    PostsFSM.new_targets.state: PostsFSM.new_buttons,
    PostsFSM.new_when.state: PostsFSM.new_targets,
    PostsFSM.new_date.state: PostsFSM.new_when,
    PostsFSM.new_delete.state: PostsFSM.new_when,
}
# Steps answered with buttons only: a text sent there asks to use them.
WIZARD_BUTTON_STEPS: dict[str, State] = {
    step.state: step for step in (PostsFSM.new_targets, PostsFSM.new_when, PostsFSM.new_delete)
}


def lifetime_rows(ctx: Ctx, current: int) -> list[list[InlineKeyboardButton]]:
    """Step 5: ``[1 h][3 h][6 h]`` ``[12 h][1 día][2 días]`` ``[♾ No borrar]``, ``current`` (the network's default)
    pre-selected; a default written with ✏️ Otro (``36 h``) gets its own choice next to ♾."""
    def choice(minutes: int, label: str) -> InlineKeyboardButton:
        return btn(choice_label(label, minutes == current), PwCB(a="del", v=minutes))

    rows = grid([choice(m, auto_delete_label(ctx, m)) for m in AUTO_DELETE if m], 3)
    custom = [choice(current, auto_delete_label(ctx, current))] if current not in AUTO_DELETE else []
    rows.append([*custom, choice(0, ctx.t("po.w.no_delete"))])
    return rows


async def wizard_prompt(event: Event, ctx: Ctx, session: AsyncSession, step: State, data: dict[str, Any],
                        error: str | None = None) -> None:
    rows: list[list[InlineKeyboardButton]] = []
    if step == PostsFSM.new_content:
        text = ctx.t("po.w.content")
    elif step == PostsFSM.new_buttons:
        text = ctx.t("po.w.buttons", help=ctx.t("po.help.buttons"))
        rows = [[btn(ctx.t("po.w.no_buttons"), PwCB(a="nobtn"))]]
    elif step == PostsFSM.new_targets:
        tokens = list(data.get("targets") or [])
        text = ctx.t("po.w.targets") + "\n\n" + await targets_block(ctx, session, tokens)
        rows = await target_rows(ctx, session, tokens, lambda token: PwCB(a="tg", t=token))
        rows.append([btn(ctx.t("po.w.continue"), PwCB(a="tgok"), style="success")])
    elif step == PostsFSM.new_when:
        text = ctx.t("po.w.when", freq=freq.describe(ctx.ws_rec.freq, ctx.lang))
        rows = [[btn(ctx.t(f"po.mode.{mode}"),
                     PwCB(a="mode", v=i))] for i, mode in enumerate(MODES)]
    elif step == PostsFSM.new_delete:
        text = ctx.t("po.w.delete")
        rows = lifetime_rows(ctx, defaults_of(ctx.ws_rec)["delete_after"])
    else:  # the date of a one-off broadcast, or right now
        text = ctx.t("po.w.date", ask=ctx.t("po.date.ask", tz=fmt.esc(ctx.bot_tz)))
        rows = [[btn(ctx.t("po.w.now"), PwCB(a="now"), style="success")]]
    back = None if step == PostsFSM.new_content else PwCB(a="back")
    await prompt(event, ctx, with_notice(text, error), cancel_screen="posts", extra_rows=rows, back=back)


async def wizard_goto(event: Event, ctx: Ctx, session: AsyncSession, state: FSMContext, step: State) -> None:
    await state.set_state(step)
    await wizard_prompt(event, ctx, session, step, await state.get_data())


async def wizard_retry(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext, step: State,
                       error: str) -> None:
    await wizard_prompt(message, ctx, session, step, await state.get_data(), error)


async def wizard_admin(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> bool:
    if ctx.is_admin and not ctx.is_hub:
        return True
    await state.clear()
    await can_manage(message, ctx, session)
    return False


async def wizard_data(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext,
                      step: State) -> dict[str, Any] | None:
    """FSM data when the button belongs to the current step of the wizard."""
    if not await can_manage(call, ctx, session):
        return None
    if await state.get_state() != step.state:
        await expired(call, ctx)
        return None
    return await state.get_data()


async def start_wizard(event: Event, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not await can_manage(event, ctx, session):
        return
    if not await limits.can_add_post(session, ctx.settings, ctx.ws_rec):
        await alert(event, await limit_text(ctx, session))
        return
    await state.clear()
    await state.set_data({"ws": ctx.ws_id, "targets": [audience.ALL]})
    await wizard_goto(event, ctx, session, state, PostsFSM.new_content)


@screen("post_new")
async def post_new_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    state = kw.get("state") or fsm_context(event, ctx)
    if state is not None:
        await start_wizard(event, ctx, session, state)


@router.callback_query(PwCB.filter(F.a == "start"))
async def on_wizard_start(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    await start_wizard(call, ctx, session, state)


@router.callback_query(PwCB.filter(F.a == "back"))
async def on_wizard_back(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    """🔙 Regresar: the previous step, keeping the answers given so far."""
    if not await can_manage(call, ctx, session):
        return
    previous = WIZARD_PREVIOUS.get(await state.get_state() or "")
    if previous is None:
        await expired(call, ctx)
        return
    await wizard_goto(call, ctx, session, state, previous)


@router.message(PostsFSM.new_content, PRIVATE, NOT_COMMAND)
async def on_wizard_content(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not await wizard_admin(message, ctx, session, state):
        return
    c = content.from_message(message)
    key = "content.err.unsupported" if c is None else content.content_error(c)
    if key or c is None:
        await wizard_retry(message, ctx, session, state, PostsFSM.new_content, ctx.t(key or "content.err.unsupported"))
        return
    await state.update_data(kind=c.kind, text=c.text, file_id=c.file_id, file_name=c.file_name)
    await wizard_goto(message, ctx, session, state, PostsFSM.new_buttons)


@router.message(PostsFSM.new_buttons, PRIVATE, NOT_COMMAND)
async def on_wizard_buttons(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not await wizard_admin(message, ctx, session, state):
        return
    if not message.text:
        await wizard_retry(message, ctx, session, state, PostsFSM.new_buttons, ctx.t("po.err.text_only"))
        return
    try:
        rows = content.parse_buttons(message.text)
    except content.ButtonsError as exc:
        await wizard_retry(message, ctx, session, state, PostsFSM.new_buttons, ctx.t(exc.key, line=exc.line))
        return
    await state.update_data(buttons=rows)
    await wizard_goto(message, ctx, session, state, PostsFSM.new_targets)


@router.callback_query(PwCB.filter(F.a == "nobtn"))
async def on_wizard_no_buttons(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if await wizard_data(call, ctx, session, state, PostsFSM.new_buttons) is None:
        return
    await state.update_data(buttons=[])
    await wizard_goto(call, ctx, session, state, PostsFSM.new_targets)


@router.callback_query(PwCB.filter(F.a == "tg"))
async def on_wizard_target(call: CallbackQuery, callback_data: PwCB, ctx: Ctx, session: AsyncSession,
                           state: FSMContext) -> None:
    data = await wizard_data(call, ctx, session, state, PostsFSM.new_targets)
    if data is None:
        return
    group_ids = set(await groups_by_id(session, ctx))
    if not valid_token(callback_data.t, group_ids):
        await expired(call, ctx)
        return
    tokens = toggle_target(data.get("targets"), callback_data.t, group_ids)
    if not tokens:
        await alert(call, ctx.t("po.tg.need_one"))
        return
    await state.update_data(targets=tokens)
    await wizard_prompt(call, ctx, session, PostsFSM.new_targets, {**data, "targets": tokens})


@router.callback_query(PwCB.filter(F.a == "tgok"))
async def on_wizard_targets_done(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    data = await wizard_data(call, ctx, session, state, PostsFSM.new_targets)
    if data is None:
        return
    if not clean_targets(data.get("targets"), set(await groups_by_id(session, ctx))):
        await alert(call, ctx.t("po.tg.need_one"))
        return
    await wizard_goto(call, ctx, session, state, PostsFSM.new_when)


@router.message(StateFilter(*WIZARD_BUTTON_STEPS.values()), PRIVATE, NOT_COMMAND)
async def on_wizard_use_buttons(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext,
                                raw_state: str | None) -> None:
    if not await wizard_admin(message, ctx, session, state):
        return
    step = WIZARD_BUTTON_STEPS.get(raw_state or "", PostsFSM.new_when)
    await wizard_retry(message, ctx, session, state, step, ctx.t("po.err.use_buttons"))


@router.callback_query(PwCB.filter(F.a == "mode"))
async def on_wizard_mode(call: CallbackQuery, callback_data: PwCB, ctx: Ctx, session: AsyncSession,
                         state: FSMContext) -> None:
    if await wizard_data(call, ctx, session, state, PostsFSM.new_when) is None:
        return
    if not 0 <= callback_data.v < len(MODES):
        await expired(call, ctx)
        return
    mode = MODES[callback_data.v]
    if mode == SchedMode.ONCE:  # its date first (still step 4)
        await wizard_goto(call, ctx, session, state, PostsFSM.new_date)
        return
    await state.update_data(mode=mode, send_at=None)
    await wizard_goto(call, ctx, session, state, PostsFSM.new_delete)


@router.message(PostsFSM.new_date, PRIVATE, NOT_COMMAND)
async def on_wizard_date(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not await wizard_admin(message, ctx, session, state):
        return
    when, error = parse_when(ctx, message)
    if when is None:
        await wizard_retry(message, ctx, session, state, PostsFSM.new_date, error or "")
        return
    await state.update_data(mode=SchedMode.ONCE, send_at=when.isoformat(), now=False)  # FSM data is JSON
    await wizard_goto(message, ctx, session, state, PostsFSM.new_delete)


@router.callback_query(PwCB.filter(F.a == "now"))
async def on_wizard_now(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    """📢 Difusión puntual › 🚀 Ahora mismo: it is sent once as soon as the wizard ends."""
    if await wizard_data(call, ctx, session, state, PostsFSM.new_date) is None:
        return
    await state.update_data(mode=SchedMode.ONCE, send_at=None, now=True)
    await wizard_goto(call, ctx, session, state, PostsFSM.new_delete)


@router.callback_query(PwCB.filter(F.a == "del"))
async def on_wizard_delete_after(call: CallbackQuery, callback_data: PwCB, ctx: Ctx, session: AsyncSession,
                                 state: FSMContext, scheduler: Scheduler) -> None:
    """Step 5, the last one: how long the post stays published. The post is created now."""
    if await wizard_data(call, ctx, session, state, PostsFSM.new_delete) is None:
        return
    minutes = callback_data.v
    if minutes not in AUTO_DELETE and minutes != defaults_of(ctx.ws_rec)["delete_after"]:  # not one of the choices
        await expired(call, ctx)
        return
    await finish_wizard(call, ctx, session, state, scheduler, minutes)


def stored_datetime(value: Any) -> datetime | None:
    """A date and time kept in the FSM data (ISO text)."""
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


async def finish_wizard(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext,
                        scheduler: Scheduler, delete_after: int) -> None:
    """Creates the post: the default options of the network first, then the answers of the wizard."""
    data = await state.get_data()
    mode = str(data.get("mode") or "")
    if data.get("ws") != ctx.ws_id or str(data.get("kind")) not in content.KINDS or mode not in MODES:
        await state.clear()
        await expired(call, ctx)
        return
    targets = clean_targets(data.get("targets"), set(await groups_by_id(session, ctx)))
    if not targets:  # its groups of chats were deleted meanwhile: never widen the audience by itself
        await state.update_data(targets=[])
        await state.set_state(PostsFSM.new_targets)
        await wizard_prompt(call, ctx, session, PostsFSM.new_targets, {**data, "targets": []},
                            ctx.t("po.tg.need_one"))
        return
    right_now = mode == SchedMode.ONCE and bool(data.get("now"))
    send_at = (utcnow() if right_now else stored_datetime(data.get("send_at"))) if mode == SchedMode.ONCE else None
    if mode == SchedMode.ONCE and not right_now and (send_at is None or send_at <= utcnow()):  # date passed meanwhile
        await state.set_state(PostsFSM.new_date)
        await wizard_prompt(call, ctx, session, PostsFSM.new_date, data, ctx.t("freq.err.past"))
        return
    await state.clear()
    if not await limits.can_add_post(session, ctx.settings, ctx.ws_rec):
        await alert(call, await limit_text(ctx, session))
        await render_posts(call, ctx, session)
        return
    post = Post(bot_id=ctx.ws_id, status=PostStatus.ACTIVE, created_by=ctx.user_id, mode=mode, send_at=send_at)
    found = content.Content(str(data["kind"]), data.get("text"), data.get("file_id"), data.get("file_name"))
    content.apply(post, found, ctx.bot_id)  # the media belongs to the bot that received it
    post.name = content.default_name(post, ctx.lang)[:NAME_MAX]
    apply_defaults(post, ctx.ws_rec)
    post.delete_after = delete_after
    post.buttons = content.clean_rows(data.get("buttons"))
    post.targets = targets
    if mode == SchedMode.OWN:
        post.freq = freq.normalize(ctx.ws_rec.freq)  # starts as a copy of the global frequency
    session.add(post)
    await session.flush()
    refresh(post, ctx, scheduler)
    log.info("Post %s created by %s in bot %s (%s, deleted after %s min)", post.id, ctx.user_id, ctx.ws_id, mode,
             delete_after)
    if mode == SchedMode.OWN:
        await toast(call, ctx.t("po.saved"))
        await open_screen("freq_edit", call, ctx, session, arg=-post.id)
        return
    await render_post(call, ctx, session, post, notice=ctx.t("po.saved"))


# ---------------------------------------------------------------------------------------------
# ✏️ Contenido
# ---------------------------------------------------------------------------------------------
async def render_content(event: Event, ctx: Ctx, session: AsyncSession, post: Post, *,
                         notice: str | None = None) -> None:
    snippet = " ".join(content.plain(post.text).split())
    lines = [
        ctx.t("po.c.title", name=fmt.esc(post.name)),
        "",
        ctx.t("po.c.name", name=fmt.esc(post.name)),
        ctx.t("po.c.name_hint"),
        ctx.t("po.c.kind", kind=content.kind_label(post.kind, ctx.lang)),
        ctx.t("po.c.text", text=fmt.esc(fmt.truncate(snippet, TEXT_SHOW_MAX))) if snippet else ctx.t("po.c.no_text"),
    ]
    pid = post.id
    markup = kb(
        [btn(ctx.t("po.c.b.change"), PoCB(a="cmsg", id=pid))],
        [btn(ctx.t("po.c.b.text"), PoCB(a="ctxt", id=pid))],
        [btn(ctx.t("po.c.b.name"), PoCB(a="cname", id=pid))],
        [btn(ctx.t("po.c.b.nomedia"), PoCB(a="nomedia", id=pid), style="danger")]
        if post.kind in content.MEDIA_KINDS else None,
        back_row(ctx.lang, "post", pid),
    )
    await show(event, with_notice("\n".join(lines), notice), markup)


@screen("post_content")
async def content_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    post = await admin_post(event, ctx, session, arg)
    if post is not None:
        await render_content(event, ctx, session, post, notice=kw.get("notice"))


async def saved_notice(ctx: Ctx, session: AsyncSession, post: Post) -> str:
    """✅ Guardado, plus how to apply the change to the copies already published."""
    notice = ctx.t("common.saved")
    if await pubsvc.live_count(session, post.id):
        notice += "\n" + ctx.t("po.c.live_hint")
    return notice


async def ask_input(event: Event, ctx: Ctx, state: FSMContext, step: State, post_id: int, text: str,
                    cancel_screen: str, error: str | None = None, **data: Any) -> None:
    """A text input of a post (Cancel reopens ``cancel_screen``)."""
    await state.set_state(step)
    await state.set_data({"id": post_id, **data})
    await prompt(event, ctx, with_notice(text, error), cancel_screen=cancel_screen, cancel_arg=post_id)


async def ask_content(event: Event, ctx: Ctx, state: FSMContext, post: Post, error: str | None = None) -> None:
    await ask_input(event, ctx, state, PostsFSM.content, post.id, ctx.t("po.c.ask_content", name=fmt.esc(post.name)),
                    "post_content", error)


async def ask_text(event: Event, ctx: Ctx, state: FSMContext, post: Post, error: str | None = None) -> None:
    key = "po.c.ask_caption" if post.kind in content.MEDIA_KINDS else "po.c.ask_text"
    await ask_input(event, ctx, state, PostsFSM.text, post.id, ctx.t(key, name=fmt.esc(post.name)), "post_content",
                    error)


async def ask_name(event: Event, ctx: Ctx, state: FSMContext, post: Post, error: str | None = None) -> None:
    await ask_input(event, ctx, state, PostsFSM.name, post.id, ctx.t("po.c.ask_name", name=fmt.esc(post.name)),
                    "post_content", error)


@router.callback_query(PoCB.filter(F.a.in_({"cmsg", "ctxt", "cname"})))
async def on_content_edit(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                          state: FSMContext) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return
    ask = {"cmsg": ask_content, "ctxt": ask_text, "cname": ask_name}[callback_data.a]
    await ask(call, ctx, state, post)


def keeps_auto_name(ctx: Ctx, post: Post) -> bool:
    """The name was never changed by hand (it follows the first words of the text)."""
    return post.name == content.default_name(post, ctx.lang)[:NAME_MAX]


@router.message(PostsFSM.content, PRIVATE, NOT_COMMAND)
async def on_content_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    post = await state_post(message, ctx, session, state)
    if post is None:
        return
    c = content.from_message(message)
    key = "content.err.unsupported" if c is None else content.content_error(c)
    if key or c is None:
        await ask_content(message, ctx, state, post, ctx.t(key or "content.err.unsupported"))
        return
    await state.clear()
    auto_name = keeps_auto_name(ctx, post)
    content.apply(post, c, ctx.bot_id)
    if auto_name:
        post.name = content.default_name(post, ctx.lang)[:NAME_MAX]
    await render_content(message, ctx, session, post, notice=await saved_notice(ctx, session, post))


@router.message(PostsFSM.text, PRIVATE, NOT_COMMAND)
async def on_text_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    post = await state_post(message, ctx, session, state)
    if post is None:
        return
    if not message.text:
        await ask_text(message, ctx, state, post, ctx.t("po.err.text_only"))
        return
    html_text = message.html_text
    key = content.content_error(content.Content(post.kind, html_text))
    if key:
        await ask_text(message, ctx, state, post, ctx.t(key))
        return
    await state.clear()
    auto_name = keeps_auto_name(ctx, post)
    content.set_text(post, html_text)
    if auto_name:
        post.name = content.default_name(post, ctx.lang)[:NAME_MAX]
    await render_content(message, ctx, session, post, notice=await saved_notice(ctx, session, post))


@router.message(PostsFSM.name, PRIVATE, NOT_COMMAND)
async def on_name_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    post = await state_post(message, ctx, session, state)
    if post is None:
        return
    name = " ".join((message.text or "").split())
    if not name or len(name) > NAME_MAX:
        error = ctx.t("common.too_long", max=NAME_MAX) if name else ctx.t("po.err.text_only")
        await ask_name(message, ctx, state, post, error)
        return
    await state.clear()
    post.name = name
    await render_content(message, ctx, session, post, notice=ctx.t("common.saved"))


@router.callback_query(PoCB.filter(F.a.in_({"nomedia", "nomedia_ok"})))
async def on_remove_media(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                          state: FSMContext) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return
    if post.kind not in content.MEDIA_KINDS:
        await render_content(call, ctx, session, post)
        return
    if content.content_error(content.Content("text", post.text)):
        await alert(call, ctx.t("po.c.nomedia.no_text"))
        return
    if callback_data.a == "nomedia":
        markup = kb([btn(ctx.t("po.c.nomedia.yes"), PoCB(a="nomedia_ok", id=post.id), style="danger"),
                     btn(ctx.t("po.no"), MenuCB(screen="post_content", arg=post.id))])
        await show(call, ctx.t("po.c.nomedia.confirm", name=fmt.esc(post.name)), markup)
        return
    post.kind = "text"
    post.media = {}
    post.media_name = None
    await toast(call, ctx.t("po.c.nomedia.done"))
    await render_content(call, ctx, session, post)


# ---------------------------------------------------------------------------------------------
# 🎯 Destino
# ---------------------------------------------------------------------------------------------
async def render_targets(event: Event, ctx: Ctx, session: AsyncSession, post: Post) -> None:
    tokens = list(post.targets or [])
    text = ctx.t("po.targets.title", name=fmt.esc(post.name)) + "\n\n" + await targets_block(ctx, session, tokens)
    rows = await target_rows(ctx, session, tokens, lambda token: PoCB(a="tg", id=post.id, t=token))
    await show(event, text, kb(*rows, back_row(ctx.lang, "post", post.id)))


@screen("post_targets")
async def targets_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **_: Any) -> None:
    post = await admin_post(event, ctx, session, arg)
    if post is not None:
        await render_targets(event, ctx, session, post)


@router.callback_query(PoCB.filter(F.a == "tg"))
async def on_target(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                    state: FSMContext) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return
    group_ids = set(await groups_by_id(session, ctx))
    if not valid_token(callback_data.t, group_ids):
        await expired(call, ctx)
        await render_targets(call, ctx, session, post)
        return
    tokens = toggle_target(post.targets, callback_data.t, group_ids)
    if not tokens:
        await alert(call, ctx.t("po.tg.need_one"))
        return
    post.targets = tokens
    await render_targets(call, ctx, session, post)


# ---------------------------------------------------------------------------------------------
# ⏰ Programación
# ---------------------------------------------------------------------------------------------
async def render_sched(event: Event, ctx: Ctx, session: AsyncSession, post: Post, *,
                       notice: str | None = None) -> None:
    lines = [ctx.t("po.s.title", name=fmt.esc(post.name)), "",
             ctx.t("po.s.modes", freq=freq.describe(ctx.ws_rec.freq, ctx.lang)), ""]
    if post.mode in (SchedMode.OWN, SchedMode.ONCE):
        lines.append(ctx.t("po.d.next", date=fmt.dt(post.next_send_at, ctx.tz)))
    lines += [ctx.t("po.s.campaign", value=campaign_text(ctx, post) or ctx.t("po.s.no_campaign")),
              ctx.t("po.s.campaign_hint")]
    pid = post.id
    rows = [[btn(choice_label(ctx.t(f"po.mode.{mode}"), post.mode == mode), PoCB(a="mode", id=pid, v=i))]
            for i, mode in enumerate(MODES)]
    if post.mode == SchedMode.OWN:
        label = ctx.t("po.s.b.own", freq=freq.describe(post.freq, ctx.lang))
        rows.append([btn(fmt.truncate(label, 64), MenuCB(screen="freq_edit", arg=-pid))])
    elif post.mode == SchedMode.ONCE:
        rows.append([btn(ctx.t("po.s.b.date", date=short_dt(ctx, post.send_at)), PoCB(a="date", id=pid))])
    rows.append([btn(ctx.t("po.s.b.from", date=day_text(post.starts_on)), PoCB(a="from", id=pid)),
                 btn(ctx.t("po.s.b.to", date=day_text(post.ends_on)), PoCB(a="to", id=pid))])
    await show(event, with_notice("\n".join(lines), notice), kb(*rows, back_row(ctx.lang, "post", pid)))


@screen("post_sched")
async def sched_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    post = await admin_post(event, ctx, session, arg)
    if post is not None:
        await render_sched(event, ctx, session, post, notice=kw.get("notice"))


@router.callback_query(PoCB.filter(F.a == "mode"))
async def on_mode(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
                  scheduler: Scheduler) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return
    if not 0 <= callback_data.v < len(MODES):
        await expired(call, ctx)
        return
    mode = MODES[callback_data.v]
    if mode != post.mode:
        if mode == SchedMode.ONCE and (post.send_at is None or post.send_at <= utcnow()):
            await ask_send_at(call, ctx, state, post, set_mode=True)  # a once post needs its date first
            return
        post.mode = mode
        if mode == SchedMode.OWN and not post.freq:
            post.freq = freq.normalize(ctx.ws_rec.freq)
        refresh(post, ctx, scheduler)
        await toast(call, ctx.t("common.saved"))
    await render_sched(call, ctx, session, post)


async def ask_send_at(event: Event, ctx: Ctx, state: FSMContext, post: Post, *, activate: bool = False,
                      set_mode: bool = False, error: str | None = None) -> None:
    """The date of a one-time send. ``activate``: asked by ▶️ Activar (Cancel goes back to the post);
    ``set_mode``: the mode becomes 📆 once the date is valid."""
    ask = ctx.t("po.date.ask", tz=fmt.esc(ctx.bot_tz))
    text = ctx.t("po.activate.date" if activate else "po.s.ask_date", name=fmt.esc(post.name), ask=ask)
    await ask_input(event, ctx, state, PostsFSM.send_at, post.id, text, "post" if activate else "post_sched", error,
                    activate=activate, set_mode=set_mode)


@router.callback_query(PoCB.filter(F.a == "date"))
async def on_date(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                  state: FSMContext) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is not None:
        await ask_send_at(call, ctx, state, post)


@router.message(PostsFSM.send_at, PRIVATE, NOT_COMMAND)
async def on_send_at_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext,
                           scheduler: Scheduler) -> None:
    data = await state.get_data()
    post = await state_post(message, ctx, session, state)
    if post is None:
        return
    activate, set_mode = bool(data.get("activate")), bool(data.get("set_mode"))
    when, error = parse_when(ctx, message)
    if when is None:
        await ask_send_at(message, ctx, state, post, activate=activate, set_mode=set_mode, error=error)
        return
    await state.clear()
    post.send_at = when
    if set_mode:
        post.mode = SchedMode.ONCE
    notice = ctx.t("common.saved")
    if activate and post.status != PostStatus.ACTIVE:
        if post.status == PostStatus.DONE and not await limits.can_add_post(session, ctx.settings, ctx.ws_rec):
            notice = await limit_text(ctx, session)
        else:
            post.status = PostStatus.ACTIVE
            notice = ctx.t("po.activated")
    refresh(post, ctx, scheduler)
    if activate:
        await render_post(message, ctx, session, post, notice=notice)
    else:
        await render_sched(message, ctx, session, post, notice=notice)


async def ask_campaign(event: Event, ctx: Ctx, state: FSMContext, post: Post, which: str,
                       error: str | None = None) -> None:
    start = which == "from"
    text = ctx.t("po.s.ask_start" if start else "po.s.ask_end", name=fmt.esc(post.name),
                 current=day_text(post.starts_on if start else post.ends_on))
    await ask_input(event, ctx, state, PostsFSM.starts_on if start else PostsFSM.ends_on, post.id, text, "post_sched",
                    error)


@router.callback_query(PoCB.filter(F.a.in_({"from", "to"})))
async def on_campaign(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                      state: FSMContext) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is not None:
        await ask_campaign(call, ctx, state, post, callback_data.a)


@router.message(StateFilter(PostsFSM.starts_on, PostsFSM.ends_on), PRIVATE, NOT_COMMAND)
async def on_campaign_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext,
                            raw_state: str | None, scheduler: Scheduler) -> None:
    post = await state_post(message, ctx, session, state)
    if post is None:
        return
    which = "from" if raw_state == PostsFSM.starts_on.state else "to"
    raw = (message.text or "").strip()
    value: date | None = None
    error: str | None = None
    if not raw:
        error = ctx.t("po.err.text_only")
    elif raw not in ("0", "-"):
        try:
            value = freq.parse_date(raw, ctx.bot_tz, utcnow())
        except ValueError:
            error = ctx.t("freq.err.date")
    if error is None:
        start, end = (value, post.ends_on) if which == "from" else (post.starts_on, value)
        if which == "to" and value is not None and value < fmt.to_local(utcnow(), ctx.bot_tz).date():
            error = ctx.t("freq.err.past")
        elif start and end and end < start:
            error = ctx.t("po.s.err.order")
    if error:
        await ask_campaign(message, ctx, state, post, which, error)
        return
    await state.clear()
    if which == "from":
        post.starts_on = value
    else:
        post.ends_on = value
    refresh(post, ctx, scheduler)
    await render_sched(message, ctx, session, post, notice=ctx.t("common.saved"))


# ---------------------------------------------------------------------------------------------
# ⚙️ Opciones (id 0: the default options of new posts)
# ---------------------------------------------------------------------------------------------
async def render_options(event: Event, ctx: Ctx, post: Post | None, *, notice: str | None = None) -> None:
    values = option_values(ctx, post)
    names = option_names(post.kind if post is not None else None)
    pid = post.id if post is not None else 0
    head = ctx.t("po.opts.title", name=fmt.esc(post.name)) if post is not None else ctx.t("po.defaults.title")
    text = head + "\n\n" + "\n".join(options_lines(ctx, values, names, hints=True))
    toggles = [btn(toggle_label(ctx.t(f"po.ob.{name}"), bool(values[name])),
                   PoCB(a="opt", id=pid, v=OPTIONS.index(name))) for name in names]
    current = clean_minutes(values.get("delete_after"))
    presets = [btn(choice_label(auto_delete_label(ctx, m), m == current), PoCB(a="ad", id=pid, v=m))
               for m in AUTO_DELETE]
    custom = current not in AUTO_DELETE  # a value written with ✏️ Otro shows on that button
    other = choice_label(auto_delete_label(ctx, current), True) if custom else ctx.t("po.ad.b.other")
    presets.append(btn(other, PoCB(a="ado", id=pid)))
    back = back_row(ctx.lang, "post", pid) if post is not None else back_row(ctx.lang, "posts")
    await show(event, with_notice(text, notice), kb(*grid(toggles, 2), *grid(presets, 4), back))


@screen("post_opts")
async def options_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    post = await admin_post(event, ctx, session, arg)
    if post is not None:
        await render_options(event, ctx, post, notice=kw.get("notice"))


@screen("post_defaults")
async def defaults_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    if await can_manage(event, ctx, session):
        await render_options(event, ctx, None, notice=kw.get("notice"))


async def option_target(event: Event, ctx: Ctx, session: AsyncSession, post_id: int,
                        state: FSMContext | None = None) -> tuple[bool, Post | None]:
    """``(usable, post)``: ``post_id`` 0 is the default options of new posts (post None)."""
    if post_id == 0:
        if not await can_manage(event, ctx, session):
            return False, None
        if state is not None:
            await state.clear()
        return True, None
    post = await admin_post(event, ctx, session, post_id, state)
    return post is not None, post


@router.callback_query(PoCB.filter(F.a == "opt"))
async def on_option(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                    state: FSMContext) -> None:
    usable, post = await option_target(call, ctx, session, callback_data.id, state)
    if not usable:
        return
    names = option_names(post.kind if post is not None else None)
    if not 0 <= callback_data.v < len(OPTIONS) or OPTIONS[callback_data.v] not in names:
        await expired(call, ctx)
        return
    name = OPTIONS[callback_data.v]
    value = not bool(option_values(ctx, post)[name])
    save_option(ctx, post, name, value)
    await toast(call, toggle_label(ctx.t(f"po.ob.{name}"), value))
    await render_options(call, ctx, post)


@router.callback_query(PoCB.filter(F.a == "ad"))
async def on_auto_delete(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                         state: FSMContext) -> None:
    usable, post = await option_target(call, ctx, session, callback_data.id, state)
    if not usable:
        return
    if callback_data.v not in AUTO_DELETE:
        await expired(call, ctx)
        return
    save_option(ctx, post, "delete_after", callback_data.v)
    await toast(call, ctx.t("common.saved"))
    await render_options(call, ctx, post)


async def ask_delete_after(event: Event, ctx: Ctx, state: FSMContext, post: Post | None,
                           error: str | None = None) -> None:
    pid = post.id if post is not None else 0
    await ask_input(event, ctx, state, PostsFSM.delete_after, pid, ctx.t("po.ad.ask"),
                    "post_opts" if post is not None else "post_defaults", error)


@router.callback_query(PoCB.filter(F.a == "ado"))
async def on_auto_delete_other(call: CallbackQuery, callback_data: PoCB, ctx: Ctx, session: AsyncSession,
                               state: FSMContext) -> None:
    usable, post = await option_target(call, ctx, session, callback_data.id, state)
    if usable:
        await ask_delete_after(call, ctx, state, post)


@router.message(PostsFSM.delete_after, PRIVATE, NOT_COMMAND)
async def on_auto_delete_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    usable, post = await option_target(message, ctx, session, _int(data.get("id"))) if "id" in data else (False, None)
    if not usable:
        await state.clear()
        return
    try:
        minutes = parse_minutes(message.text or "")
    except ValueError as exc:
        await ask_delete_after(message, ctx, state, post, ctx.t(str(exc)))
        return
    await state.clear()
    save_option(ctx, post, "delete_after", minutes)
    await render_options(message, ctx, post, notice=ctx.t("common.saved"))
