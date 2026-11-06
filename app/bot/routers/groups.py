"""🗂 Grupos de canales: custom sets of chats of the network. A group of chats is a target for posts (``g<id>``) and
may have its own frequency (edited in ``freq_edit``, see ``freqs.py``). Screens: ``groups``, ``group``,
``group_chats``.
"""
from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.bot.routers.freqs import describe, guard, with_notice
from app.db.base import utcnow
from app.db.models import Chat, ChatGroup, ChatStatus, GroupChat, Post
from app.services import audience
from app.services import freq as freq_svc
from app.services.scheduler import Scheduler
from app.ui import fmt
from app.ui.callbacks import MenuCB
from app.ui.common import alert, back_row, btn, grid, kb, nav_row, paginate, prompt, show, toast, toggle_label
from app.ui.screens import open_screen, screen

router = Router(name="groups")

Event = Message | CallbackQuery


class GrCB(CallbackData, prefix="gr"):
    """``id`` group of chats, ``c`` chat pk, ``p`` page of ``group_chats``."""

    a: str
    id: int = 0
    c: int = 0
    p: int = 0


class GroupsFSM(StatesGroup):
    name = State()
    rename = State()


NAME_MAX = 64
GROUPS_PAGE = 10
CHATS_PAGE = 10
ORPHANS_SHOWN = 15
NETWORK = (ChatStatus.APPROVED, ChatStatus.PENDING)  # the chats a group of chats can be made of


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------
async def load_group(event: Event, ctx: Ctx, session: AsyncSession, group_id: int) -> ChatGroup | None:
    """The group of the workspace, or None after telling the user it doesn't exist."""
    group = await session.get(ChatGroup, group_id) if group_id > 0 else None
    if group is not None and group.bot_id == ctx.ws_id:
        return group
    await alert(event, ctx.t("common.not_found"))
    await open_screen("groups", event, ctx, session)
    return None


async def admin_group(call: CallbackQuery, data: GrCB, ctx: Ctx, session: AsyncSession,
                      state: FSMContext) -> ChatGroup | None:
    if not await guard(call, ctx):
        return None
    await state.clear()
    return await load_group(call, ctx, session, data.id)


async def network_chats(session: AsyncSession, ws_id: int) -> list[Chat]:
    return await audience.bot_chats(session, ws_id, statuses=NETWORK)


async def posts_using(session: AsyncSession, ws_id: int, group_id: int) -> list[Post]:
    token = audience.group_token(group_id)
    posts = (await session.execute(select(Post).where(Post.bot_id == ws_id).order_by(Post.id))).scalars()
    return [p for p in posts if token in (p.targets or [])]


def post_name(post: Post) -> str:
    return post.name or f"#{post.id}"


def clean_name(ctx: Ctx, message: Message) -> tuple[str, str | None]:
    """The name typed by the user (spaces collapsed), or an error."""
    name = " ".join((message.text or "").split())
    if not name:
        return "", ctx.t("gr.err.name")
    if len(name) > NAME_MAX:
        return "", ctx.t("common.too_long", max=NAME_MAX)
    return name, None


def chat_line(ctx: Ctx, n: int, chat: Chat) -> str:
    if chat.status == ChatStatus.PENDING:
        state = ctx.t("gr.c.pending")
    elif not chat.rights_ok:
        state = ctx.t("gr.c.no_rights")
    elif chat.is_paused():
        state = ctx.t("gr.c.paused")
    else:
        state = ""
    return ctx.t("gr.c.line", n=n, icon="📣" if chat.is_channel else "👥",
                 title=fmt.link(chat.public_link, chat.display_title), members=fmt.num(chat.members),
                 origin="🤝" if chat.is_external else "🏠", state=state)


# ---------------------------------------------------------------------------------------------
# groups: the list
# ---------------------------------------------------------------------------------------------
async def render_groups(event: Event, ctx: Ctx, session: AsyncSession, page: int = 0, *,
                        notice: str | None = None) -> None:
    groups = await audience.bot_groups(session, ctx.ws_id)
    chats = {c.id for c in await network_chats(session, ctx.ws_id)}
    counts: dict[int, int] = {}
    for chat_pk, group_ids in (await audience.memberships(session, ctx.ws_id)).items():
        if chat_pk in chats:
            for gid in group_ids:
                counts[gid] = counts.get(gid, 0) + 1
    items, page, pages = paginate(groups, page, GROUPS_PAGE)
    lines = [
        ctx.t("gr.item", n=n, name=fmt.esc(g.name), chats=counts.get(g.id, 0),
              freq=ctx.t("gr.item_own", freq=describe(ctx, g.freq)) if g.freq else ctx.t("fq.global_short"),
              open=ctx.t("gr.item_open") if g.open else "")
        for n, g in enumerate(items, page * GROUPS_PAGE + 1)
    ]
    parts = [ctx.t("gr.title")]
    parts += ["\n".join(lines), ctx.t("gr.legend")] if lines else [ctx.t("gr.empty")]
    if pages > 1:
        parts.append(ctx.t("common.page", page=page + 1, pages=pages))
    buttons = [btn(fmt.truncate(ctx.t("gr.b.group", name=g.name), 40), MenuCB(screen="group", arg=g.id))
               for g in items]
    markup = kb(
        *grid(buttons, 2),
        nav_row(page, pages, lambda p: MenuCB(screen="groups", arg=p), ctx.lang),
        [btn(ctx.t("gr.b.new"), GrCB(a="new"), style="success")],
        back_row(ctx.lang, "home"),
    )
    await show(event, with_notice("\n\n".join(parts), notice), markup)


@screen("groups")
async def groups_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    if await guard(event, ctx):
        await render_groups(event, ctx, session, arg, notice=kw.get("notice"))


async def ask_name(event: Event, ctx: Ctx, state: FSMContext, error: str | None = None) -> None:
    await state.set_state(GroupsFSM.name)
    await prompt(event, ctx, with_notice(ctx.t("gr.new.prompt", max=NAME_MAX), error), cancel_screen="groups")


@router.callback_query(GrCB.filter(F.a == "new"))
async def on_new(call: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    if await guard(call, ctx):
        await ask_name(call, ctx, state)


@router.message(GroupsFSM.name, F.chat.type == "private", ~F.text.startswith("/"))
async def on_name_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    if not await guard(message, ctx):
        await state.clear()
        return
    name, error = clean_name(ctx, message)
    if error:
        await ask_name(message, ctx, state, error)
        return
    await state.clear()
    group = ChatGroup(bot_id=ctx.ws_id, name=name)
    session.add(group)
    await session.flush()
    await render_group_chats(message, ctx, session, group, notice=ctx.t("gr.created", name=fmt.esc(name)))


# ---------------------------------------------------------------------------------------------
# group: the detail
# ---------------------------------------------------------------------------------------------
async def render_group(event: Event, ctx: Ctx, session: AsyncSession, group: ChatGroup, *,
                       notice: str | None = None) -> None:
    members = await audience.group_chat_pks(session, group.id)
    chats = [c for c in await network_chats(session, ctx.ws_id) if c.id in members]
    posts = await posts_using(session, ctx.ws_id, group.id)
    f = group.freq or ctx.ws_rec.freq
    nxt = freq_svc.next_slot(f, ctx.bot_tz, utcnow())
    lines = [
        ctx.t("gr.d.title", name=fmt.esc(group.name)),
        ctx.t("gr.d.chats", n=fmt.num(len(chats)), members=fmt.num(sum(c.members or 0 for c in chats))),
        ctx.t("gr.d.freq_own" if group.freq else "gr.d.freq_global", freq=describe(ctx, f)),
        ctx.t("fq.source_hint"),
        ctx.t("gr.d.next", when=fmt.dt(nxt, ctx.tz)),
        ctx.t("gr.d.posts", n=len(posts)),
        ctx.t("gr.d.open", value=fmt.onoff(group.open)),
        ctx.t("gr.d.open_hint" if group.open else "gr.d.closed_hint"),
    ]
    markup = kb(
        [btn(ctx.t("gr.b.chats"), MenuCB(screen="group_chats", arg=group.id)),
         btn(ctx.t("gr.b.freq"), MenuCB(screen="freq_edit", arg=group.id))],
        [btn(toggle_label(ctx.t("gr.b.open"), group.open), GrCB(a="open", id=group.id))],
        [btn(ctx.t("gr.b.rename"), GrCB(a="ren", id=group.id)),
         btn(ctx.t("gr.b.delete"), GrCB(a="del", id=group.id), style="danger")],
        back_row(ctx.lang, "groups"),
    )
    await show(event, with_notice("\n".join(lines), notice), markup)


@screen("group")
async def group_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    if not await guard(event, ctx):
        return
    group = await load_group(event, ctx, session, arg)
    if group is not None:
        await render_group(event, ctx, session, group, notice=kw.get("notice"))


@router.callback_query(GrCB.filter(F.a == "open"))
async def on_open(call: CallbackQuery, callback_data: GrCB, ctx: Ctx, session: AsyncSession,
                  state: FSMContext) -> None:
    group = await admin_group(call, callback_data, ctx, session, state)
    if group is None:
        return
    group.open = not group.open
    await toast(call, toggle_label(ctx.t("gr.b.open"), group.open))
    await render_group(call, ctx, session, group)


async def ask_rename(event: Event, ctx: Ctx, state: FSMContext, group: ChatGroup, error: str | None = None) -> None:
    await state.set_state(GroupsFSM.rename)
    await state.set_data({"id": group.id})
    text = ctx.t("gr.rename.prompt", name=fmt.esc(group.name), max=NAME_MAX)
    await prompt(event, ctx, with_notice(text, error), cancel_screen="group", cancel_arg=group.id)


@router.callback_query(GrCB.filter(F.a == "ren"))
async def on_rename(call: CallbackQuery, callback_data: GrCB, ctx: Ctx, session: AsyncSession,
                    state: FSMContext) -> None:
    group = await admin_group(call, callback_data, ctx, session, state)
    if group is not None:
        await ask_rename(call, ctx, state, group)


@router.message(GroupsFSM.rename, F.chat.type == "private", ~F.text.startswith("/"))
async def on_rename_input(message: Message, ctx: Ctx, session: AsyncSession, state: FSMContext) -> None:
    group_id = int((await state.get_data()).get("id") or 0)
    if not await guard(message, ctx):
        await state.clear()
        return
    group = await load_group(message, ctx, session, group_id)
    if group is None:
        await state.clear()
        return
    name, error = clean_name(ctx, message)
    if error:
        await ask_rename(message, ctx, state, group, error)
        return
    await state.clear()
    group.name = name
    await render_group(message, ctx, session, group, notice=ctx.t("common.saved"))


@router.callback_query(GrCB.filter(F.a == "del"))
async def on_delete(call: CallbackQuery, callback_data: GrCB, ctx: Ctx, session: AsyncSession,
                    state: FSMContext) -> None:
    group = await admin_group(call, callback_data, ctx, session, state)
    if group is None:
        return
    token = audience.group_token(group.id)
    posts = await posts_using(session, ctx.ws_id, group.id)
    orphans = [p for p in posts if not [t for t in p.targets if t != token]]
    lines = [ctx.t("gr.del.confirm", name=fmt.esc(group.name))]
    if posts:
        lines.append(ctx.t("gr.del.posts", n=len(posts)) if len(posts) > 1 else ctx.t("gr.del.posts_1"))
    if orphans:
        names = ", ".join(f"<b>{fmt.esc(post_name(p))}</b>" for p in orphans[:ORPHANS_SHOWN])
        if len(orphans) > ORPHANS_SHOWN:
            names += ctx.t("gr.del.more", n=len(orphans) - ORPHANS_SHOWN)
        lines.append(ctx.t("gr.del.orphans", names=names))
    if group.freq:
        lines.append(ctx.t("gr.del.freq"))
    markup = kb(
        [btn(ctx.t("gr.b.del_yes"), GrCB(a="del_ok", id=group.id), style="danger"),
         btn(ctx.t("common.no"), MenuCB(screen="group", arg=group.id))],
    )
    await show(call, "\n\n".join(lines), markup)


@router.callback_query(GrCB.filter(F.a == "del_ok"))
async def on_delete_confirm(call: CallbackQuery, callback_data: GrCB, ctx: Ctx, session: AsyncSession,
                            state: FSMContext, scheduler: Scheduler) -> None:
    group = await admin_group(call, callback_data, ctx, session, state)
    if group is None:
        return
    token = audience.group_token(group.id)
    for post in await posts_using(session, ctx.ws_id, group.id):
        post.targets = [t for t in post.targets if t != token]
    await session.execute(delete(GroupChat).where(GroupChat.group_id == group.id))
    await session.delete(group)
    await session.flush()
    scheduler.wake()  # its chats may follow another frequency now
    await toast(call, ctx.t("gr.deleted"))
    await render_groups(call, ctx, session)


# ---------------------------------------------------------------------------------------------
# group_chats: which chats are in the group
# ---------------------------------------------------------------------------------------------
async def render_group_chats(event: Event, ctx: Ctx, session: AsyncSession, group: ChatGroup, page: int = 0, *,
                             notice: str | None = None) -> None:
    chats = await network_chats(session, ctx.ws_id)
    members = await audience.group_chat_pks(session, group.id)
    items, page, pages = paginate(chats, page, CHATS_PAGE)
    first = page * CHATS_PAGE + 1
    lines = [chat_line(ctx, n, chat) for n, chat in enumerate(items, first)]
    buttons = [
        btn(fmt.truncate(f"{'✅' if chat.id in members else '⚪'} {n}. {chat.display_title}", 28),
            GrCB(a="tg", id=group.id, c=chat.id, p=page))
        for n, chat in enumerate(items, first)
    ]
    inside = sum(1 for c in chats if c.id in members)
    parts = [ctx.t("gr.c.title", name=fmt.esc(group.name), n=inside, total=len(chats))]
    parts.append("\n".join(lines) if lines else ctx.t("gr.c.empty"))
    if pages > 1:
        parts.append(ctx.t("common.page", page=page + 1, pages=pages))
    markup = kb(
        *grid(buttons, 2),
        nav_row(page, pages, lambda p: GrCB(a="pg", id=group.id, p=p), ctx.lang),
        [btn(ctx.t("gr.b.all"), GrCB(a="all", id=group.id, p=page)),
         btn(ctx.t("gr.b.none"), GrCB(a="none", id=group.id, p=page))] if chats else None,
        back_row(ctx.lang, "group", group.id),
    )
    await show(event, with_notice("\n\n".join(parts), notice), markup)


@screen("group_chats")
async def group_chats_screen(event: Event, ctx: Ctx, session: AsyncSession, arg: int = 0, **kw: Any) -> None:
    if not await guard(event, ctx):
        return
    group = await load_group(event, ctx, session, arg)
    if group is not None:
        await render_group_chats(event, ctx, session, group, notice=kw.get("notice"))


@router.callback_query(GrCB.filter(F.a == "pg"))
async def on_page(call: CallbackQuery, callback_data: GrCB, ctx: Ctx, session: AsyncSession,
                  state: FSMContext) -> None:
    group = await admin_group(call, callback_data, ctx, session, state)
    if group is not None:
        await render_group_chats(call, ctx, session, group, callback_data.p)


@router.callback_query(GrCB.filter(F.a == "tg"))
async def on_toggle_chat(call: CallbackQuery, callback_data: GrCB, ctx: Ctx, session: AsyncSession,
                         state: FSMContext) -> None:
    group = await admin_group(call, callback_data, ctx, session, state)
    if group is None:
        return
    chat = await session.get(Chat, callback_data.c)
    if chat is None or chat.bot_id != ctx.ws_id or chat.status not in NETWORK:
        await alert(call, ctx.t("common.not_found"))
    else:
        on = chat.id not in await audience.group_chat_pks(session, group.id)
        await audience.set_member(session, group.id, chat.id, on)
        await toast(call, ctx.t("gr.c.added" if on else "gr.c.removed", title=fmt.esc(chat.display_title)))
    await render_group_chats(call, ctx, session, group, callback_data.p)


@router.callback_query(GrCB.filter(F.a.in_({"all", "none"})))
async def on_all_or_none(call: CallbackQuery, callback_data: GrCB, ctx: Ctx, session: AsyncSession,
                         state: FSMContext) -> None:
    group = await admin_group(call, callback_data, ctx, session, state)
    if group is None:
        return
    on = callback_data.a == "all"
    members = await audience.group_chat_pks(session, group.id)
    network = {c.id for c in await network_chats(session, ctx.ws_id)}
    if on:
        new = sorted(network - members)
        session.add_all([GroupChat(group_id=group.id, chat_pk=pk) for pk in new])
        await session.flush()
        changed = len(new)
    else:  # "none" empties the group, also of the chats that are not in the network now
        await session.execute(delete(GroupChat).where(GroupChat.group_id == group.id))
        changed = len(members & network)
    await toast(call, ctx.t("gr.c.added_n" if on else "gr.c.removed_n", n=changed))
    await render_group_chats(call, ctx, session, group, callback_data.p)
