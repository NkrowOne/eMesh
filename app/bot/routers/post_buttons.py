"""🔘 Buttons editor of a post (screen ``post_buttons``): the keyboard drawn with its real colors, where each button
opens its editor (name, link, color, move, remove); adding a button step by step (name → link → color → place) and
writing them all at once in the text syntax of ``content.parse_buttons``.

Buttons are rows of dicts (see ``services/content.py``); the column is JSON, so every change stores new lists.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.routers.posts import (
    NOT_COMMAND,
    PRIVATE,
    Event,
    admin_post,
    can_manage,
    drop_panel,
    expired,
    send_preview,
    state_post,
    units,
    with_notice,
)
from app.db.models import Post
from app.services import content
from app.services import publisher as pubsvc
from app.ui import fmt
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, choice_label, kb, prompt, show, toast
from app.ui.screens import screen

if TYPE_CHECKING:
    from app.db.session import SessionMaker
    from app.telegram.manager import BotManager

router = Router(name="post_buttons")

Rows = list[list[dict[str, str]]]


class PbCB(CallbackData, prefix="pb"):
    """Buttons editor. ``id`` post, ``r`` / ``c`` row and position of a button, ``v`` value (color, direction,
    place)."""

    a: str
    id: int
    r: int = 0
    c: int = 0
    v: int = 0


class PostButtonsFSM(StatesGroup):
    add_name = State()
    add_link = State()
    add_color = State()
    add_place = State()
    name = State()
    link = State()
    bulk = State()


COLORS = content.COLORS  # default (⬜), primary (🔵), success (🟢), danger (🔴)
LEFT, RIGHT, UP, DOWN = range(4)
ARROWS = ("⬅️", "➡️", "⬆️", "⬇️")
BULK_SHOW_MAX = 3000  # the current buttons are echoed in the "write them all" prompt up to this size
_COPY_RE = re.compile(r"^(?:copiar|copy)\s*:\s*(?P<value>.+)$", re.IGNORECASE | re.DOTALL)
ADD_PREVIOUS: dict[str, State] = {
    PostButtonsFSM.add_link.state: PostButtonsFSM.add_name,
    PostButtonsFSM.add_color.state: PostButtonsFSM.add_link,
    PostButtonsFSM.add_place.state: PostButtonsFSM.add_color,
}


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------
def rows_of(post: Post) -> Rows:
    """A copy of the post's buttons (only valid ones) that can be changed freely."""
    return content.clean_rows(post.buttons)


def button_at(rows: Rows, r: int, c: int) -> dict[str, str] | None:
    if 0 <= r < len(rows) and 0 <= c < len(rows[r]):
        return rows[r][c]
    return None


def style_of(button: dict[str, str]) -> str:
    style = button.get("style", "")
    return style if style in content.STYLES else "default"


def with_style(button: dict[str, str], style: str) -> dict[str, str]:
    out = {k: v for k, v in button.items() if k != "style"}
    if style in content.STYLES:
        out["style"] = style
    return out


def color_style(name: str) -> str | None:
    return name if name in content.STYLES else None


def link_text(button: dict[str, str]) -> str:
    return f"copiar: {button['copy']}" if button.get("copy") else button.get("url", "")


def move(rows: Rows, r: int, c: int, direction: int) -> tuple[Rows, int, int] | str:
    """The rows after moving the button at (r, c) and its new position, or an i18n key when it can't move.

    ⬅️ ➡️ swap it with its neighbour; ⬆️ appends it to the row above and ⬇️ puts it first in the row below (at
    the top / bottom it leaves its row for a new one, when it isn't alone there)."""
    rows = [list(row) for row in rows]
    button = rows[r][c]
    if direction in (LEFT, RIGHT):
        other = c - 1 if direction == LEFT else c + 1
        if not 0 <= other < len(rows[r]):
            return "pb.edge"
        rows[r][c], rows[r][other] = rows[r][other], button
        return rows, r, other
    up = direction == UP
    edge = 0 if up else len(rows) - 1
    if r == edge:
        if len(rows[r]) == 1:
            return "pb.edge"
        rows[r].pop(c)
        if up:
            rows.insert(0, [button])
            return rows, 0, 0
        rows.append([button])
        return rows, len(rows) - 1, 0
    target = r - 1 if up else r + 1
    if len(rows[target]) >= content.MAX_PER_ROW:
        return "pb.row_full"
    rows[r].pop(c)
    if up:
        rows[target].append(button)
        new_r, new_c = target, len(rows[target]) - 1
    else:
        rows[target].insert(0, button)
        new_r, new_c = target, 0
    if not rows[r]:
        rows.pop(r)
        if not up:
            new_r -= 1  # the row below moved up into the empty one
    return rows, new_r, new_c


def parse_link(text: str) -> dict[str, str]:
    """``{"url": …}`` or ``{"copy": …}`` from ``https://…``, ``t.me/…``, ``@user`` or ``copiar: TEXTO``. Raises
    ValueError(i18n key)."""
    raw = (text or "").strip()
    copy = _COPY_RE.match(raw)
    if copy:
        value = copy.group("value").strip()
        if not value or len(value) > content.MAX_COPY_TEXT:
            raise ValueError("pb.err.copy")
        return {"copy": value}
    url = content.normalize_url(raw)
    if url is None:
        raise ValueError("pb.err.link")
    return {"url": url}


def clean_name(message: Message) -> str | None:
    name = " ".join((message.text or "").split())
    return name if 0 < len(name) <= content.MAX_BUTTON_TEXT else None


def color_buttons(ctx: Ctx, make_cb: Callable[[int], CallbackData],
                  selected: str | None = None) -> list[InlineKeyboardButton]:
    """⬜ 🔵 🟢 🔴, each one drawn with its own color."""
    return [btn(choice_label(ctx.t(f"color.{name}"), name == selected) if selected else ctx.t(f"color.{name}"),
                make_cb(i), style=color_style(name)) for i, name in enumerate(COLORS)]


# ---------------------------------------------------------------------------------------------
# Screen: the keyboard
# ---------------------------------------------------------------------------------------------
async def render_buttons(event: Event, ctx: Ctx, session: AsyncSession, post: Post, *, notice: str | None = None,
                         new: bool = False) -> None:
    rows = rows_of(post)
    parts = [ctx.t("pb.title", name=fmt.esc(post.name)), ctx.t("pb.hint") if rows else ctx.t("pb.none")]
    if rows:
        parts.append(ctx.t("pb.count", n=content.count_buttons(rows), max=content.MAX_BUTTONS))
        if await pubsvc.live_count(session, post.id):
            parts.append(ctx.t("pb.live_hint"))
    keyboard = [[btn(fmt.truncate(b["text"], 64), PbCB(a="b", id=post.id, r=r, c=c), style=color_style(style_of(b)))
                 for c, b in enumerate(row)] for r, row in enumerate(rows)]
    markup = kb(
        *keyboard,
        [btn(ctx.t("pb.b.add"), PbCB(a="add", id=post.id), style="success")],
        [btn(ctx.t("pb.b.bulk"), PbCB(a="bulk", id=post.id)),
         btn(ctx.t("pb.b.clear"), PbCB(a="clear", id=post.id), style="danger") if rows else None],
        [btn(ctx.t("pb.b.preview"), PbCB(a="prev", id=post.id))],
        back_row(ctx.lang, "post", post.id),
    )
    if new:
        await drop_panel(event)
    await show(event, with_notice("\n\n".join(parts), notice), markup, new=new)


@screen("post_buttons")
async def buttons_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    post = await admin_post(event, ctx, session, arg)
    if post is not None:
        await render_buttons(event, ctx, session, post, notice=kw.get("notice"))


@router.callback_query(PbCB.filter(F.a == "prev"))
async def on_preview(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession, state: FSMContext,
                     manager: BotManager, sm: SessionMaker) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is not None and await send_preview(call, ctx, post, manager, sm):
        await render_buttons(call, ctx, session, post, new=True)


@router.callback_query(PbCB.filter(F.a.in_({"clear", "clear_ok"})))
async def on_clear(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession,
                   state: FSMContext) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return
    count = content.count_buttons(post.buttons)
    if count and callback_data.a == "clear":
        markup = kb([btn(ctx.t("pb.clear.yes"), PbCB(a="clear_ok", id=post.id), style="danger"),
                     btn(ctx.t("po.no"), MenuCB(screen="post_buttons", arg=post.id))])
        text = ctx.t("pb.clear.confirm", name=fmt.esc(post.name), buttons=units(ctx, count, "buttons"))
        await show(call, text, markup)
        return
    if count:
        post.buttons = []
        await toast(call, ctx.t("pb.cleared"))
    await render_buttons(call, ctx, session, post)


# ---------------------------------------------------------------------------------------------
# Editor of one button
# ---------------------------------------------------------------------------------------------
async def render_button(event: Event, ctx: Ctx, session: AsyncSession, post: Post, r: int, c: int, *,
                        notice: str | None = None) -> None:
    """The editor of the button at (r, c); the keyboard again when it no longer exists."""
    rows = rows_of(post)
    button = button_at(rows, r, c)
    if button is None:
        await expired(event, ctx)
        await render_buttons(event, ctx, session, post)
        return
    style = style_of(button)
    target = (ctx.t("pb.e.copy", v=fmt.esc(button["copy"])) if button.get("copy")
              else ctx.t("pb.e.url", v=fmt.esc(button["url"])))
    lines = [
        ctx.t("pb.e.title", name=fmt.esc(post.name)),
        "",
        ctx.t("pb.e.name", v=fmt.esc(button["text"])),
        target,
        ctx.t("pb.e.color", v=ctx.t(f"color.{style}")),
        ctx.t("pb.e.pos", row=r + 1, col=c + 1),
        ctx.t("pb.e.hint"),
    ]
    pid = post.id
    arrows = [btn(arrow, PbCB(a="mv", id=pid, r=r, c=c, v=i)) for i, arrow in enumerate(ARROWS)]
    markup = kb(
        [btn(ctx.t("pb.e.b.name"), PbCB(a="name", id=pid, r=r, c=c)),
         btn(ctx.t("pb.e.b.link"), PbCB(a="link", id=pid, r=r, c=c))],
        color_buttons(ctx, lambda i: PbCB(a="col", id=pid, r=r, c=c, v=i), style),
        arrows[:2],  # ⬅️ ➡️ inside the row
        arrows[2:],  # ⬆️ ⬇️ to another row
        [btn(ctx.t("pb.e.b.del"), PbCB(a="del", id=pid, r=r, c=c), style="danger")],
        back_row(ctx.lang, "post_buttons", pid),
    )
    await show(event, with_notice("\n".join(lines), notice), markup)


async def edited_button(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext,
                        callback_data: PbCB) -> tuple[Post, Rows] | None:
    """The post and its rows when the button of ``callback_data`` still exists."""
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None:
        return None
    rows = rows_of(post)
    if button_at(rows, callback_data.r, callback_data.c) is None:
        await expired(call, ctx)
        await render_buttons(call, ctx, session, post)
        return None
    return post, rows


@router.callback_query(PbCB.filter(F.a == "b"))
async def on_button(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession,
                    state: FSMContext) -> None:
    found = await edited_button(call, ctx, session, state, callback_data)
    if found is not None:
        await render_button(call, ctx, session, found[0], callback_data.r, callback_data.c)


@router.callback_query(PbCB.filter(F.a == "col"))
async def on_color(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession,
                   state: FSMContext) -> None:
    found = await edited_button(call, ctx, session, state, callback_data)
    if found is None:
        return
    post, rows = found
    if not 0 <= callback_data.v < len(COLORS):
        await expired(call, ctx)
        return
    r, c = callback_data.r, callback_data.c
    rows[r][c] = with_style(rows[r][c], COLORS[callback_data.v])
    post.buttons = rows
    await render_button(call, ctx, session, post, r, c)


@router.callback_query(PbCB.filter(F.a == "mv"))
async def on_move(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession,
                  state: FSMContext) -> None:
    found = await edited_button(call, ctx, session, state, callback_data)
    if found is None:
        return
    post, rows = found
    if not 0 <= callback_data.v < len(ARROWS):
        await expired(call, ctx)
        return
    moved = move(rows, callback_data.r, callback_data.c, callback_data.v)
    if isinstance(moved, str):
        await alert(call, ctx.t(moved))
        return
    post.buttons, r, c = moved
    await render_button(call, ctx, session, post, r, c)


@router.callback_query(PbCB.filter(F.a == "del"))
async def on_remove(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession,
                    state: FSMContext) -> None:
    found = await edited_button(call, ctx, session, state, callback_data)
    if found is None:
        return
    post, rows = found
    rows[callback_data.r].pop(callback_data.c)
    post.buttons = [row for row in rows if row]
    await toast(call, ctx.t("pb.removed"))
    await render_buttons(call, ctx, session, post)


async def ask_edit(event: Event, ctx: Ctx, state: FSMContext, post: Post, r: int, c: int, step: State,
                   error: str | None = None) -> None:
    """Text input of the name or the link of the button at (r, c) (Cancel goes back to the keyboard)."""
    button = rows_of(post)[r][c]
    if step == PostButtonsFSM.name:
        text = ctx.t("pb.ask_name", name=fmt.esc(button["text"]))
    else:
        text = ctx.t("pb.ask_link_edit", name=fmt.esc(button["text"]), current=fmt.esc(link_text(button)),
                     ask=ctx.t("pb.ask_link"))
    await state.set_state(step)
    await state.set_data({"id": post.id, "r": r, "c": c})
    await prompt(event, ctx, with_notice(text, error), cancel_screen="post_buttons", cancel_arg=post.id)


@router.callback_query(PbCB.filter(F.a.in_({"name", "link"})))
async def on_edit(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession,
                  state: FSMContext) -> None:
    found = await edited_button(call, ctx, session, state, callback_data)
    if found is not None:
        step = PostButtonsFSM.name if callback_data.a == "name" else PostButtonsFSM.link
        await ask_edit(call, ctx, state, found[0], callback_data.r, callback_data.c, step)


@router.message(StateFilter(PostButtonsFSM.name, PostButtonsFSM.link), PRIVATE, NOT_COMMAND)
async def on_edit_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext,
                        raw_state: str | None) -> None:
    data = await state.get_data()
    post = await state_post(message, ctx, session, state)
    if post is None:
        return
    r, c = int(data.get("r") or 0), int(data.get("c") or 0)
    rows = rows_of(post)
    if button_at(rows, r, c) is None:
        await state.clear()
        await render_buttons(message, ctx, session, post, notice=ctx.t("core.expired_button"))
        return
    step = PostButtonsFSM.name if raw_state == PostButtonsFSM.name.state else PostButtonsFSM.link
    if step == PostButtonsFSM.name:
        name = clean_name(message)
        if name is None:
            await ask_edit(message, ctx, state, post, r, c, step, ctx.t("pb.err.name"))
            return
        rows[r][c] = {**rows[r][c], "text": name}
    else:
        try:
            target = parse_link(message.text or "")
        except ValueError as exc:
            await ask_edit(message, ctx, state, post, r, c, step, ctx.t(str(exc)))
            return
        rows[r][c] = {**{k: v for k, v in rows[r][c].items() if k not in ("url", "copy")}, **target}
    await state.clear()
    post.buttons = rows
    await render_button(message, ctx, session, post, r, c, notice=ctx.t("common.saved"))


# ---------------------------------------------------------------------------------------------
# ➕ Añadir botón: name → link → color → place
# ---------------------------------------------------------------------------------------------
async def add_prompt(event: Event, ctx: Ctx, post: Post, step: State, data: dict[str, Any],
                     error: str | None = None) -> None:
    rows: list[list[InlineKeyboardButton]] = []
    if step == PostButtonsFSM.add_name:
        text = ctx.t("pb.a.name")
    elif step == PostButtonsFSM.add_link:
        text = ctx.t("pb.a.link", ask=ctx.t("pb.ask_link"))
    elif step == PostButtonsFSM.add_color:
        text = ctx.t("pb.a.color", name=fmt.esc(data.get("name", "")))
        rows = [color_buttons(ctx, lambda i: PbCB(a="acol", id=post.id, v=i))]
    else:
        text = ctx.t("pb.a.place", name=fmt.esc(data.get("name", "")))
        rows = [[btn(ctx.t("pb.a.new_row"), PbCB(a="aplace", id=post.id, v=0))],
                [btn(ctx.t("pb.a.same_row"), PbCB(a="aplace", id=post.id, v=1))]]
    back = None if step == PostButtonsFSM.add_name else PbCB(a="aback", id=post.id)
    await prompt(event, ctx, with_notice(text, error), cancel_screen="post_buttons", cancel_arg=post.id,
                 extra_rows=rows, back=back)


async def add_goto(event: Event, ctx: Ctx, state: FSMContext, post: Post, step: State) -> None:
    await state.set_state(step)
    await add_prompt(event, ctx, post, step, await state.get_data())


async def full(event: Event, ctx: Ctx, post: Post) -> bool:
    if content.count_buttons(post.buttons) < content.MAX_BUTTONS:
        return False
    await alert(event, ctx.t("pb.max", max=content.MAX_BUTTONS))
    return True


@router.callback_query(PbCB.filter(F.a == "add"))
async def on_add(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession,
                 state: FSMContext) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is None or await full(call, ctx, post):
        return
    await state.set_data({"id": post.id})
    await add_goto(call, ctx, state, post, PostButtonsFSM.add_name)


async def add_data(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext, callback_data: PbCB,
                   steps: tuple[State, ...]) -> tuple[Post, dict[str, Any], State] | None:
    """The post, FSM data and current step when the button belongs to the add flow in progress."""
    if not await can_manage(call, ctx, session):
        return None
    current = await state.get_state()
    data = await state.get_data()
    step = next((s for s in steps if s.state == current), None)
    if step is None or data.get("id") != callback_data.id:
        await expired(call, ctx)
        return None
    post = await admin_post(call, ctx, session, callback_data.id)
    if post is None:
        await state.clear()
        return None
    return post, data, step


@router.callback_query(PbCB.filter(F.a == "aback"))
async def on_add_back(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession,
                      state: FSMContext) -> None:
    """🔙 Regresar: the previous step of the new button, keeping the answers given so far."""
    steps = (PostButtonsFSM.add_link, PostButtonsFSM.add_color, PostButtonsFSM.add_place)
    found = await add_data(call, ctx, session, state, callback_data, steps)
    if found is not None:
        post, _, step = found
        await add_goto(call, ctx, state, post, ADD_PREVIOUS[step.state])


@router.message(PostButtonsFSM.add_name, PRIVATE, NOT_COMMAND)
async def on_add_name(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    post = await state_post(message, ctx, session, state)
    if post is None:
        return
    name = clean_name(message)
    if name is None:
        await add_prompt(message, ctx, post, PostButtonsFSM.add_name, await state.get_data(), ctx.t("pb.err.name"))
        return
    await state.update_data(name=name)
    await add_goto(message, ctx, state, post, PostButtonsFSM.add_link)


@router.message(PostButtonsFSM.add_link, PRIVATE, NOT_COMMAND)
async def on_add_link(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    post = await state_post(message, ctx, session, state)
    if post is None:
        return
    try:
        target = parse_link(message.text or "")
    except ValueError as exc:
        await add_prompt(message, ctx, post, PostButtonsFSM.add_link, await state.get_data(), ctx.t(str(exc)))
        return
    await state.update_data(target=target)
    await add_goto(message, ctx, state, post, PostButtonsFSM.add_color)


@router.message(StateFilter(PostButtonsFSM.add_color, PostButtonsFSM.add_place), PRIVATE, NOT_COMMAND)
async def on_add_use_buttons(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext,
                             raw_state: str | None) -> None:
    post = await state_post(message, ctx, session, state)
    if post is None:
        return
    step = PostButtonsFSM.add_color if raw_state == PostButtonsFSM.add_color.state else PostButtonsFSM.add_place
    await add_prompt(message, ctx, post, step, await state.get_data(), ctx.t("po.err.use_buttons"))


@router.callback_query(PbCB.filter(F.a == "acol"))
async def on_add_color(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession,
                       state: FSMContext) -> None:
    found = await add_data(call, ctx, session, state, callback_data, (PostButtonsFSM.add_color,))
    if found is None:
        return
    post, data, _ = found
    if not 0 <= callback_data.v < len(COLORS):
        await expired(call, ctx)
        return
    await state.update_data(style=COLORS[callback_data.v])
    rows = rows_of(post)
    if rows and len(rows[-1]) < content.MAX_PER_ROW:
        await add_goto(call, ctx, state, post, PostButtonsFSM.add_place)
        return
    await finish_add(call, ctx, session, state, post, {**data, "style": COLORS[callback_data.v]}, same_row=False)


@router.callback_query(PbCB.filter(F.a == "aplace"))
async def on_add_place(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession,
                       state: FSMContext) -> None:
    found = await add_data(call, ctx, session, state, callback_data, (PostButtonsFSM.add_place,))
    if found is not None:
        post, data, _ = found
        await finish_add(call, ctx, session, state, post, data, same_row=callback_data.v == 1)


async def finish_add(call: CallbackQuery, ctx: Ctx, session: AsyncSession, state: FSMContext, post: Post,
                     data: dict[str, Any], *, same_row: bool) -> None:
    await state.clear()
    target = data.get("target") if isinstance(data.get("target"), dict) else {}
    name = str(data.get("name") or "")
    if not name or not (target.get("url") or target.get("copy")):
        await expired(call, ctx)
        await render_buttons(call, ctx, session, post)
        return
    if await full(call, ctx, post):
        await render_buttons(call, ctx, session, post)
        return
    button = with_style({"text": name, **{k: str(v) for k, v in target.items() if k in ("url", "copy")}},
                        str(data.get("style") or "default"))
    rows = rows_of(post)
    if same_row and rows and len(rows[-1]) < content.MAX_PER_ROW:
        rows[-1].append(button)
    else:
        rows.append([button])
    post.buttons = rows
    await toast(call, ctx.t("pb.added"))
    await render_buttons(call, ctx, session, post)


# ---------------------------------------------------------------------------------------------
# ✍️ Escribirlos todos
# ---------------------------------------------------------------------------------------------
async def ask_bulk(event: Event, ctx: Ctx, state: FSMContext, post: Post, error: str | None = None) -> None:
    parts = [ctx.t("pb.bulk.title", name=fmt.esc(post.name)), ctx.t("po.help.buttons")]
    rows = rows_of(post)
    if rows:
        current = content.format_buttons(rows)
        parts.append(ctx.t("pb.bulk.current", rows=fmt.esc(current)) if len(current) <= BULK_SHOW_MAX
                     else ctx.t("pb.bulk.too_long"))
        parts.append(ctx.t("pb.bulk.replace"))
    await state.set_state(PostButtonsFSM.bulk)
    await state.set_data({"id": post.id})
    await prompt(event, ctx, with_notice("\n\n".join(parts), error), cancel_screen="post_buttons", cancel_arg=post.id)


@router.callback_query(PbCB.filter(F.a == "bulk"))
async def on_bulk(call: CallbackQuery, callback_data: PbCB, ctx: Ctx, session: AsyncSession,
                  state: FSMContext) -> None:
    post = await admin_post(call, ctx, session, callback_data.id, state)
    if post is not None:
        await ask_bulk(call, ctx, state, post)


@router.message(PostButtonsFSM.bulk, PRIVATE, NOT_COMMAND)
async def on_bulk_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    post = await state_post(message, ctx, session, state)
    if post is None:
        return
    if not message.text:
        await ask_bulk(message, ctx, state, post, ctx.t("po.err.text_only"))
        return
    try:
        rows = content.parse_buttons(message.text)
    except content.ButtonsError as exc:
        await ask_bulk(message, ctx, state, post, ctx.t(exc.key, line=exc.line))
        return
    await state.clear()
    post.buttons = rows
    await render_buttons(message, ctx, session, post, notice=ctx.t("common.saved"))
