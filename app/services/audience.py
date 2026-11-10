"""🎯 Who receives what: targets of posts and groups of chats.

Targets of a post (``Post.targets``, a list of tokens):

* ``"all"``: every chat of the bot; ``"own"``: its own chats; ``"ext"``: the partners' chats (external);
* ``"g<id>"``: the chats of the 🗂 group ``<id>``.

The audience is the union of its targets. Only *sendable* chats receive posts: approved, with the required rights
and not paused (by an admin or by its owner).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from app.db.base import utcnow
from app.db.models import Chat, ChatGroup, ChatOrigin, ChatStatus, GroupChat, Post

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ALL = "all"
OWN = "own"
EXT = "ext"
VIRTUAL = (ALL, OWN, EXT)


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


# --------------------------------------------------------------------------- chats
def is_sendable(chat: Chat, now: datetime | None = None) -> bool:
    return chat.status == ChatStatus.APPROVED and chat.rights_ok and not chat.vault and not chat.is_paused(now)


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
