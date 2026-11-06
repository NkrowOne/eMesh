"""🎯 Who receives what: targets of posts, groups of chats and the rotation of each chat.

Targets of a post (``Post.targets``, a list of tokens):

* ``"all"``: every chat of the bot; ``"own"``: its own chats; ``"ext"``: the partners' chats (external);
* ``"g<id>"``: the chats of the 🗂 group ``<id>``.

The audience is the union of its targets. Only *sendable* chats receive posts: approved, with the required rights
and not paused (by an admin or by its owner).

Frequencies: a chat follows the frequency of the first of its groups (by ``sort``, then id) that has its own one,
otherwise the global frequency of the bot. That frequency is its *source*. At each slot of a source every chat
following it gets the next post of its rotation: the active rotation posts that target it, inside their dates.
"""
from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from app.db.base import utcnow
from app.db.models import Chat, ChatGroup, ChatOrigin, ChatStatus, GroupChat, Post, PostStatus, RotationOrder, SchedMode
from app.services import freq as freq_svc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ALL = "all"
OWN = "own"
EXT = "ext"
VIRTUAL = (ALL, OWN, EXT)
GLOBAL_SOURCE = "global"


# --------------------------------------------------------------------------- tokens
def group_token(group_id: int) -> str:
    return f"g{int(group_id)}"


def split_targets(tokens: Iterable[str] | None) -> tuple[set[str], set[int]]:
    """``(virtual targets, group ids)`` of a list of tokens; unknown tokens are ignored."""
    virtual: set[str] = set()
    groups: set[int] = set()
    for token in tokens or []:
        token = str(token)
        if token in VIRTUAL:
            virtual.add(token)
        elif token.startswith("g") and token[1:].isdigit():
            groups.add(int(token[1:]))
    return virtual, groups


def make_targets(virtual: Iterable[str], group_ids: Iterable[int]) -> list[str]:
    """Tokens in a stable order: ``all`` makes the rest redundant."""
    v = set(virtual)
    if ALL in v:
        return [ALL]
    if OWN in v and EXT in v:
        return [ALL]
    return [x for x in VIRTUAL if x in v] + [group_token(g) for g in sorted(set(group_ids))]


def source_key(group: ChatGroup | None) -> str:
    """``"global"`` or ``"g<id>"`` (Run.source of rotation runs)."""
    return GLOBAL_SOURCE if group is None else group_token(group.id)


# --------------------------------------------------------------------------- chats
def is_sendable(chat: Chat, now: datetime | None = None) -> bool:
    return chat.status == ChatStatus.APPROVED and chat.rights_ok and not chat.is_paused(now)


async def bot_chats(session: AsyncSession, bot_id: int, *, statuses: Sequence[str] | None = None) -> list[Chat]:
    q = select(Chat).where(Chat.bot_id == bot_id)
    if statuses:
        q = q.where(Chat.status.in_(list(statuses)))
    return list((await session.execute(q.order_by(Chat.id))).scalars())


async def sendable_chats(session: AsyncSession, bot_id: int, now: datetime | None = None) -> list[Chat]:
    now = now or utcnow()
    return [c for c in await bot_chats(session, bot_id, statuses=[ChatStatus.APPROVED]) if is_sendable(c, now)]


async def bot_groups(session: AsyncSession, bot_id: int) -> list[ChatGroup]:
    q = select(ChatGroup).where(ChatGroup.bot_id == bot_id).order_by(ChatGroup.sort, ChatGroup.id)
    return list((await session.execute(q)).scalars())


async def memberships(session: AsyncSession, bot_id: int) -> dict[int, set[int]]:
    """``{chat pk: {group ids}}`` of the bot's chats that are in some group."""
    q = (select(GroupChat.chat_pk, GroupChat.group_id)
         .join(ChatGroup, ChatGroup.id == GroupChat.group_id)
         .where(ChatGroup.bot_id == bot_id))
    out: dict[int, set[int]] = defaultdict(set)
    for chat_pk, group_id in (await session.execute(q)).all():
        out[chat_pk].add(group_id)
    return dict(out)


async def chat_group_ids(session: AsyncSession, chat_pk: int) -> set[int]:
    rows = await session.execute(select(GroupChat.group_id).where(GroupChat.chat_pk == chat_pk))
    return {g for (g,) in rows}


async def group_chat_pks(session: AsyncSession, group_id: int) -> set[int]:
    rows = await session.execute(select(GroupChat.chat_pk).where(GroupChat.group_id == group_id))
    return {c for (c,) in rows}


async def group_counts(session: AsyncSession, bot_id: int) -> dict[int, int]:
    """``{group id: number of chats}`` of the network: approved and pending ones (a chat that left or was banned
    stays in its groups, but isn't counted)."""
    q = (select(GroupChat.group_id, func.count())
         .join(ChatGroup, ChatGroup.id == GroupChat.group_id)
         .join(Chat, Chat.id == GroupChat.chat_pk)
         .where(ChatGroup.bot_id == bot_id, Chat.status.in_([ChatStatus.APPROVED, ChatStatus.PENDING]))
         .group_by(GroupChat.group_id))
    return {g: int(n) for g, n in (await session.execute(q)).all()}


async def set_member(session: AsyncSession, group_id: int, chat_pk: int, on: bool) -> bool:
    """Adds / removes a chat from a group. Returns True when something changed. The caller checks that both rows
    belong to the same bot."""
    row = await session.get(GroupChat, (group_id, chat_pk))
    if on and row is None:
        session.add(GroupChat(group_id=group_id, chat_pk=chat_pk))
        await session.flush()
        return True
    if not on and row is not None:
        await session.delete(row)
        await session.flush()
        return True
    return False


async def join_open_groups(session: AsyncSession, bot_id: int, chat_pk: int) -> list[ChatGroup]:
    """Puts a new external chat in every 🤝 open group of the bot. Returns the groups it joined."""
    joined: list[ChatGroup] = []
    for group in await bot_groups(session, bot_id):
        if group.open and await set_member(session, group.id, chat_pk, True):
            joined.append(group)
    return joined


async def leave_all_groups(session: AsyncSession, chat_pk: int) -> None:
    await session.execute(delete(GroupChat).where(GroupChat.chat_pk == chat_pk))


# --------------------------------------------------------------------------- audience
def targets_chat(tokens: Iterable[str] | None, chat: Chat, chat_groups: set[int]) -> bool:
    virtual, groups = split_targets(tokens)
    if ALL in virtual:
        return True
    if OWN in virtual and chat.origin == ChatOrigin.OWN:
        return True
    if EXT in virtual and chat.origin == ChatOrigin.EXTERNAL:
        return True
    return bool(groups & chat_groups)


async def audience(session: AsyncSession, post: Post, *, sendable_only: bool = True,
                   now: datetime | None = None) -> list[Chat]:
    """The chats a post goes to (only the sendable ones unless ``sendable_only`` is False: then every approved
    chat it targets, paused or not)."""
    now = now or utcnow()
    chats = (await sendable_chats(session, post.bot_id, now) if sendable_only
             else await bot_chats(session, post.bot_id, statuses=[ChatStatus.APPROVED]))
    groups = await memberships(session, post.bot_id)
    return [c for c in chats if targets_chat(post.targets, c, groups.get(c.id, set()))]


async def audience_size(session: AsyncSession, post: Post, now: datetime | None = None) -> tuple[int, int]:
    """``(chats, members)`` that would receive the post now."""
    chats = await audience(session, post, now=now)
    return len(chats), sum(c.members or 0 for c in chats)


async def targets_size(session: AsyncSession, bot_id: int, tokens: list[str],
                       now: datetime | None = None) -> tuple[int, int]:
    """``(chats, members)`` of a list of tokens (sendable chats only): for the target picker."""
    now = now or utcnow()
    groups = await memberships(session, bot_id)
    chats = [c for c in await sendable_chats(session, bot_id, now) if targets_chat(tokens, c, groups.get(c.id, set()))]
    return len(chats), sum(c.members or 0 for c in chats)


# --------------------------------------------------------------------------- frequency sources
def source_of(chat_groups: set[int], groups_by_id: dict[int, ChatGroup]) -> ChatGroup | None:
    """The group whose own frequency the chat follows (the first by sort/id), None = the global one."""
    own = [groups_by_id[g] for g in chat_groups if g in groups_by_id and groups_by_id[g].freq]
    if not own:
        return None
    return min(own, key=lambda g: (g.sort, g.id))


async def chat_source(session: AsyncSession, chat: Chat) -> ChatGroup | None:
    groups = {g.id: g for g in await bot_groups(session, chat.bot_id)}
    return source_of(await chat_group_ids(session, chat.id), groups)


async def chats_of_source(session: AsyncSession, bot_id: int, source: ChatGroup | None,
                          now: datetime | None = None) -> list[Chat]:
    """The sendable chats that follow ``source`` (a group with its own frequency, or None = global)."""
    now = now or utcnow()
    groups = {g.id: g for g in await bot_groups(session, bot_id)}
    members = await memberships(session, bot_id)
    out: list[Chat] = []
    for chat in await sendable_chats(session, bot_id, now):
        src = source_of(members.get(chat.id, set()), groups)
        if (src is None and source is None) or (src is not None and source is not None and src.id == source.id):
            out.append(chat)
    return out


async def source_counts(session: AsyncSession, bot_id: int, now: datetime | None = None) -> dict[int | None, int]:
    """``{group id | None (global): sendable chats following it}``."""
    now = now or utcnow()
    groups = {g.id: g for g in await bot_groups(session, bot_id)}
    members = await memberships(session, bot_id)
    out: dict[int | None, int] = defaultdict(int)
    for chat in await sendable_chats(session, bot_id, now):
        src = source_of(members.get(chat.id, set()), groups)
        out[src.id if src else None] += 1
    return dict(out)


# --------------------------------------------------------------------------- rotation
async def rotation_posts(session: AsyncSession, bot_id: int, tz: str, now: datetime | None = None) -> list[Post]:
    """Active rotation posts inside their dates, in rotation order (oldest first)."""
    now = now or utcnow()
    q = (select(Post).where(Post.bot_id == bot_id, Post.status == PostStatus.ACTIVE, Post.mode == SchedMode.ROTATION)
         .order_by(Post.id))
    return [p for p in (await session.execute(q)).scalars() if freq_svc.in_dates(p, tz, now)]


def rotation_pool(posts: Sequence[Post], chat: Chat, chat_groups: set[int]) -> list[Post]:
    """The rotation posts that target ``chat``, in rotation order."""
    return [p for p in posts if targets_chat(p.targets, chat, chat_groups)]


def next_in_rotation(pool: Sequence[Post], last_post_id: int | None, order: str = RotationOrder.SEQUENTIAL,
                     rng: random.Random | None = None) -> Post | None:
    """The post a chat gets now: the one after ``last_post_id`` (wrapping around), or a random one that isn't the
    last when there is a choice."""
    if not pool:
        return None
    if order == RotationOrder.RANDOM:
        choices = [p for p in pool if p.id != last_post_id] or list(pool)
        return (rng or random).choice(choices)
    if last_post_id is None:
        return pool[0]
    return next((p for p in pool if p.id > last_post_id), pool[0])


async def plan_slot(session: AsyncSession, bot_id: int, source: ChatGroup | None, tz: str, order: str,
                    now: datetime | None = None, rng: random.Random | None = None) -> dict[int, list[Chat]]:
    """What a slot of ``source`` sends: ``{post id: [chats]}`` (each chat gets the next post of its rotation)."""
    now = now or utcnow()
    posts = await rotation_posts(session, bot_id, tz, now)
    if not posts:
        return {}
    members = await memberships(session, bot_id)
    plan: dict[int, list[Chat]] = defaultdict(list)
    for chat in await chats_of_source(session, bot_id, source, now):
        post = next_in_rotation(rotation_pool(posts, chat, members.get(chat.id, set())), chat.rot_last_post_id,
                                order, rng)
        if post is not None:
            plan[post.id].append(chat)
    return dict(plan)
