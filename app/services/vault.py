"""💎 Premium copies of posts for channels: the canal almacén.

Telegram doesn't let bots send custom (premium) emoji to channels, but it keeps them in forwarded messages. So:

1. the bot sends the post to the admin's private chat, where custom emoji are allowed (the bot's owner has
   Telegram Premium) — :func:`remember_pending` keeps who asked for it;
2. the admin forwards that message to an own channel of the network, the **canal almacén** (``Chat.vault``: it
   receives nothing from the network);
3. the bot sees it arrive (``channel_post`` with ``forward_origin`` = the bot and the date of step 1) and links it to
   the post (:func:`link`): ``Post.vault_chat_id`` / ``vault_msg_id`` / ``vault_sig``;
4. the publisher forwards that copy to the channels (``content.vault_copy``); groups get the normal message.

A copy made from other content (``content.signature``) is out of date and is not used.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, MessageOrigin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat, ChatOrigin, ChatStatus, ChatType, Post
from app.services import content, kv
from app.telegram.errors import short

log = logging.getLogger(__name__)

PENDING_MAX = 20  # prepared messages remembered per network (the newest)

LINKED = "linked"
NOT_OWN = "not_own"  # not an own channel of the network
OTHER_VAULT = "other_vault"  # the network already has another canal almacén
CHANGED = "changed"  # the post changed (or was deleted) after the message was prepared
NO_EMOJI = "no_emoji"  # the custom emoji didn't reach the channel
NO_BUTTONS = "no_buttons"  # the buttons didn't reach it and couldn't be put back


def _key(ws_id: int) -> str:
    return f"vault:wait:{ws_id}"


def _stamp(value: Any) -> str:
    return str(int(value.timestamp()))


async def vault_chat(session: AsyncSession, ws_id: int) -> Chat | None:
    """The canal almacén of the network (it may be out of the network: check ``status``)."""
    q = select(Chat).where(Chat.bot_id == ws_id, Chat.vault.is_(True)).order_by(Chat.id).limit(1)
    return (await session.execute(q)).scalars().first()


def usable(chat: Chat | None) -> bool:
    return chat is not None and chat.status == ChatStatus.APPROVED


async def remember_pending(session: AsyncSession, ws_id: int, sent: Message, post: Post, user_id: int) -> None:
    """The bot sent ``sent`` (the premium message of ``post``) to ``user_id``, who will forward it to the canal
    almacén: it is recognised by its sender and date (``forward_origin``)."""
    pending = dict(await kv.get(session, _key(ws_id), {}) or {})
    pending[_stamp(sent.date)] = {"post": post.id, "user": user_id, "bot": sent.from_user.id if sent.from_user
                                  else None, "sig": content.signature(post)}
    for stamp in sorted(pending, key=int)[:-PENDING_MAX]:
        pending.pop(stamp)
    await kv.put(session, _key(ws_id), pending)


async def take_pending(session: AsyncSession, ws_id: int, origin: MessageOrigin | None) -> dict[str, Any] | None:
    """The prepared message a forward comes from (and forgets it), or None when it isn't one."""
    sender = getattr(origin, "sender_user", None)
    if origin is None or origin.type != "user" or sender is None or not sender.is_bot:
        return None
    pending = dict(await kv.get(session, _key(ws_id), {}) or {})
    entry = pending.get(_stamp(origin.date))
    if not isinstance(entry, dict) or entry.get("bot") != sender.id:
        return None
    pending.pop(_stamp(origin.date))
    await kv.put(session, _key(ws_id), pending)
    return entry


@dataclass
class Outcome:
    result: str
    post: Post | None = None
    chat: Chat | None = None
    vault: Chat | None = None  # the canal almacén (OTHER_VAULT: the one already chosen)
    new_vault: bool = False  # the channel has just become the canal almacén
    old: tuple[int, int] | None = None  # the previous copy (to delete)


async def link(bot: Bot, session: AsyncSession, message: Message, entry: dict[str, Any]) -> Outcome:
    """Links the forwarded ``message`` (a channel post) to the post of ``entry`` when it can be used."""
    post = await session.get(Post, int(entry.get("post") or 0))
    if post is None or post.bot_id != bot.id or entry.get("sig") != content.signature(post):
        return Outcome(CHANGED, post)
    chat = await _chat(session, bot.id, message.chat.id)
    if chat is None or chat.type != ChatType.CHANNEL or chat.origin != ChatOrigin.OWN or not usable(chat):
        return Outcome(NOT_OWN, post, chat)
    current = await vault_chat(session, bot.id)
    if current is not None and current.id != chat.id and usable(current):
        return Outcome(OTHER_VAULT, post, chat, current)
    if "<tg-emoji" in (post.text or "") and not content.custom_emoji_in(message):
        return Outcome(NO_EMOJI, post, chat)
    if content.clean_rows(post.buttons) and not (message.reply_markup and message.reply_markup.inline_keyboard):
        try:  # the buttons didn't come with the forward: an admin with "edit messages" can put them back
            await bot.edit_message_reply_markup(chat_id=chat.chat_id, message_id=message.message_id,
                                                reply_markup=content.build_markup(post.buttons))
        except TelegramAPIError as exc:
            log.info("Buttons of post %s can't be put on its premium copy: %s", post.id, short(exc))
            return Outcome(NO_BUTTONS, post, chat)
    if current is not None and current.id != chat.id:
        current.vault = False  # the old canal almacén is out of the network
    new_vault = not chat.vault
    chat.vault = True
    old = (post.vault_chat_id, post.vault_msg_id) if post.vault_chat_id and post.vault_msg_id else None
    post.vault_chat_id, post.vault_msg_id, post.vault_sig = chat.chat_id, message.message_id, content.signature(post)
    return Outcome(LINKED, post, chat, chat, new_vault, old)


async def _chat(session: AsyncSession, ws_id: int, chat_id: int) -> Chat | None:
    q = select(Chat).where(Chat.bot_id == ws_id, Chat.chat_id == chat_id)
    return (await session.execute(q)).scalars().first()


async def delete_message(bot: Bot, chat_id: int, message_id: int) -> None:
    """Best effort (Telegram doesn't let bots delete messages older than 48 h)."""
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError as exc:
        log.info("Message %s of %s not deleted: %s", message_id, chat_id, short(exc))


def unlink(post: Post) -> None:
    post.vault_chat_id = post.vault_msg_id = post.vault_sig = None


def release(chat: Chat) -> None:
    """The channel stops being the canal almacén (it receives the network's posts again)."""
    chat.vault = False


__all__ = ["CHANGED", "LINKED", "NOT_OWN", "NO_BUTTONS", "NO_EMOJI", "OTHER_VAULT", "Outcome", "delete_message",
           "link", "release", "remember_pending", "take_pending", "unlink", "usable", "vault_chat"]
