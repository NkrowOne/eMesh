"""The bot added to / promoted in / removed from channels and groups (``my_chat_member``), and the events inside
them: the "pinned" service messages of the bot's own pins, group -> supergroup migrations and the discovery of chats
where the bot already is an administrator.

The bot that receives these updates IS the network's bot (a super admin's workspace only changes their private
chat), so the network here is ``ctx.bot_rec`` and the chat calls go through the update's bot.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Chat as TgChat
from aiogram.types import ChatMember, ChatMemberUpdated, InlineKeyboardMarkup, Message
from aiogram.types import User as TgUser
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import Ctx
from app.config import Settings
from app.db.models import Bot as BotRecord
from app.db.models import BotStatus, Chat, ChatOrigin, ChatStatus, ChatType, Delivery, DeliveryStatus
from app.db.session import SessionMaker, session_scope
from app.services import chats as chat_svc
from app.services import chatstate, clones, limits
from app.services.chatinfo import apply_rights, chat_type_of, missing_rights
from app.services.notify import send_dm
from app.telegram.context import set_low_priority
from app.telegram.errors import short
from app.ui.callbacks import MenuCB
from app.ui.common import btn, kb
from app.ui.fmt import esc, num

log = logging.getLogger(__name__)

router = Router(name="chat_events")

GROUP_TYPES = {"group", "supergroup"}
PRESENT = {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER}


def _hub(ctx: Ctx, settings: Settings) -> bool:
    """The main bot in hub mode runs no network (whatever network its super admin is managing)."""
    return ctx.bot_rec.is_main and settings.MAIN_BOT_MODE == "hub"


def _present(member: ChatMember) -> bool:
    if member.status in PRESENT:
        return True
    return member.status == ChatMemberStatus.RESTRICTED and bool(getattr(member, "is_member", False))


def _actor(event: ChatMemberUpdated) -> TgUser | None:
    user = event.from_user
    return user if user is not None and not user.is_bot else None


def _apply_info(chat: Chat, tg_chat: TgChat) -> None:
    chat.title = (tg_chat.title or chat.title or "")[:256]
    chat.username = tg_chat.username
    chat.type = chat_type_of(tg_chat.type)


async def _leave(bot: Bot, chat_id: int) -> None:
    try:
        await bot.leave_chat(chat_id)
    except TelegramAPIError as exc:
        log.info("leaveChat %s failed: %s", chat_id, short(exc))


async def _description(bot: Bot, chat_id: int) -> str | None:
    try:
        return (await bot.get_chat(chat_id)).description
    except TelegramAPIError as exc:
        log.info("getChat %s failed: %s", chat_id, short(exc))
        return None


# --------------------------------------------------------------------------- my_chat_member
# An update older than the last one applied to the chat (both queued while the bot was down) is dropped.
_member_dates: dict[tuple[int, int], datetime] = {}
MEMBER_DATES_MAX = 100_000


@router.my_chat_member(F.chat.type.in_(chat_svc.CHAT_TYPES))
async def on_my_chat_member(event: ChatMemberUpdated, bot: Bot, ctx: Ctx, session: AsyncSession,
                            settings: Settings) -> None:
    key = (bot.id, event.chat.id)
    async with chat_svc.chat_lock(*key):
        last = _member_dates.get(key)
        if last is not None and event.date < last:
            log.info("my_chat_member of %s from %s ignored: %s was already applied", event.chat.id, event.date, last)
            return
        if _hub(ctx, settings):
            if _present(event.new_chat_member):
                await _hub_refuse(event, bot, ctx, session)
        elif _present(event.new_chat_member):
            await _on_present(event, bot, ctx, session, settings)
        else:
            await _on_removed(event, bot, ctx, session)
        await session.commit()
        if len(_member_dates) >= MEMBER_DATES_MAX:
            _member_dates.clear()
        _member_dates[key] = event.date


async def _hub_refuse(event: ChatMemberUpdated, bot: Bot, ctx: Ctx, session: AsyncSession) -> None:
    await _leave(bot, event.chat.id)
    actor = _actor(event)
    if actor is not None:
        markup = kb([btn(ctx.t("ce.btn.create_bot"), MenuCB(screen="clone"), style="success")])
        await send_dm(bot, session, actor.id, ctx.t("ce.dm.hub"), markup)


async def _own_bot_markup(ctx: Ctx, session: AsyncSession,
                          settings: Settings) -> InlineKeyboardMarkup | None:
    """[🤖 Crea tu propio bot] when clones can be created: the clone screen in the main bot, a link to the main
    bot from a clone."""
    if (await limits.platform(session, settings)).clone_policy == "closed":
        return None
    if ctx.is_main:
        return kb([btn(ctx.t("ce.btn.own_bot"), MenuCB(screen="clone"))])
    main = await clones.main_username(session, settings)
    return kb([btn(ctx.t("ce.btn.own_bot"), url=f"https://t.me/{main}?start=clone")]) if main else None


async def _on_present(event: ChatMemberUpdated, bot: Bot, ctx: Ctx, session: AsyncSession,
                      settings: Settings) -> None:
    net = ctx.bot_rec
    actor = _actor(event)
    chat = await chat_svc.chat_row(session, net.id, event.chat.id)
    if chat is not None and chat.status in chat_svc.ACTIVE:
        await _on_rights(event, bot, ctx, session, chat)
        return
    kind = ctx.t("common.channel_word" if event.chat.type == "channel" else "common.group_word")
    name = esc(event.chat.title or event.chat.id)
    if chat is not None and chat.status == ChatStatus.BANNED:
        await _leave(bot, event.chat.id)
        if actor is not None:
            await send_dm(bot, session, actor.id, ctx.t("ce.dm.banned", kind=kind, chat=name))
        return
    # New, or back after the bot left / was rejected: it keeps its origin and its groups.
    origin = chat.origin if chat is not None else (ChatOrigin.OWN if ctx.is_admin else ChatOrigin.EXTERNAL)
    if origin == ChatOrigin.EXTERNAL and not net.join_open and not ctx.is_admin:
        await _leave(bot, event.chat.id)
        if actor is not None:
            await send_dm(bot, session, actor.id, ctx.t("ce.dm.closed", chat=name),
                          await _own_bot_markup(ctx, session, settings))
        return
    if not await limits.can_add_chat(session, settings, net):
        await _leave(bot, event.chat.id)
        if actor is not None:
            limit = await limits.max_chats(session, settings, net)
            await send_dm(bot, session, actor.id, ctx.t("ce.dm.limit", n=num(limit), kind=kind, chat=name))
        return
    if chat is None:
        chat = Chat(bot_id=net.id, chat_id=event.chat.id, origin=origin)
        session.add(chat)
    if actor is not None:
        chat.owner_user_id = actor.id
    chat.status = ChatStatus.PENDING
    chat.reject_reason = None
    _apply_info(chat, event.chat)
    missing = apply_rights(chat, event.new_chat_member)
    # A new row has no count yet: one that can't be read must not reject it.
    counted = await chat_svc.count_members(bot, chat) or chat.members_at is not None
    await session.flush()
    if chat.is_external and not ctx.is_admin:
        description = await _description(bot, chat.chat_id)
        if not await chat_svc.check_external(bot, session, net, chat, description=description, counted=counted):
            return
    if missing:
        await chat_svc.dm_missing_rights(bot, session, chat, missing)
        return
    await chat_svc.admit(bot, session, net, chat, added_by_admin=ctx.is_admin)


async def _on_rights(event: ChatMemberUpdated, bot: Bot, ctx: Ctx, session: AsyncSession, chat: Chat) -> None:
    """The bot is still in a chat of the network and its rights may have changed."""
    _apply_info(chat, event.chat)
    missing = missing_rights(event.new_chat_member, chat.type)
    if chat.status == ChatStatus.APPROVED:
        if missing:
            await chatstate.mark_rights(bot, session, ctx.bot_rec, chat, missing)
        else:
            await chatstate.rights_restored(bot, session, ctx.bot_rec, chat)
        return
    was_ok = chat.rights_ok
    chat.rights_ok = not missing
    chat.missing_rights = ",".join(missing)[:256]
    if missing:
        await chat_svc.dm_missing_rights(bot, session, chat, missing)
    elif not was_ok:  # the rights it was waiting for: it goes on with its admission
        await chat_svc.admit(bot, session, ctx.bot_rec, chat, added_by_admin=ctx.is_admin)


async def _on_removed(event: ChatMemberUpdated, bot: Bot, ctx: Ctx, session: AsyncSession) -> None:
    chat = await chat_svc.chat_row(session, ctx.bot_id, event.chat.id)
    if chat is None:
        return
    if event.from_user is not None and event.from_user.id == bot.id:
        return  # the bot left by itself: whatever made it leave (rejected, removed, banned) set the status
    # A conditional UPDATE, never a flush of the row read above: an admin's decision committed meanwhile
    # (removed, banned, rejected) must win.
    res = await session.execute(
        update(Chat).where(Chat.id == chat.id, Chat.status.in_(list(chat_svc.ACTIVE)))
        .values(status=ChatStatus.LEFT, rights_ok=False)
        .execution_options(synchronize_session=False)
    )
    if not res.rowcount:
        return
    await chat_svc.close_notices(bot, session, chat, "rq.closed.left")
    await chatstate.mark_left(bot, session, ctx.bot_rec, chat)
    chat.rights_ok = False


# --------------------------------------------------------------------------- pinned service messages
# A channel's service message doesn't say who pinned: the delivery may still be uncommitted by the engine when it
# arrives, so it is looked up again once after this delay.
PIN_RECHECK_DELAY = 3.0
_tasks: set[asyncio.Task[Any]] = set()


async def _is_live(session: AsyncSession, bot_id: int, chat_id: int, message_id: int) -> bool:
    q = select(Delivery.id).where(Delivery.bot_id == bot_id, Delivery.chat_id == chat_id,
                                  Delivery.message_id == message_id, Delivery.status == DeliveryStatus.SENT).limit(1)
    return (await session.execute(q)).first() is not None


async def _delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError as exc:
        log.info("Pin service message %s/%s not deleted: %s", chat_id, message_id, short(exc))


async def _recheck_pin(bot: Bot, sm: SessionMaker, chat_id: int, service_id: int, pinned_id: int) -> None:
    set_low_priority()
    try:
        await asyncio.sleep(PIN_RECHECK_DELAY)
        async with session_scope(sm) as session:
            live = await _is_live(session, bot.id, chat_id, pinned_id)
        if live:
            await _delete(bot, chat_id, service_id)
    except Exception:  # noqa: BLE001 - background task: never let it die silently
        log.exception("Pin service message re-check failed for %s/%s", chat_id, service_id)


@router.channel_post(F.pinned_message)
@router.message(F.pinned_message, F.chat.type.in_(GROUP_TYPES))
async def on_pinned(message: Message, bot: Bot, session: AsyncSession, sm: SessionMaker) -> None:
    """Deletes the "pinned a message" notice of the bot's own pins. In a group it comes from whoever pinned; a
    channel doesn't say, so only the pins of the bot's live deliveries count."""
    pinned = message.pinned_message
    if pinned is None:
        return
    if message.chat.type in GROUP_TYPES:
        if message.from_user is not None and message.from_user.id == bot.id:
            await _delete(bot, message.chat.id, message.message_id)
        return
    if await chat_svc.chat_row(session, bot.id, message.chat.id) is None:
        return
    if await _is_live(session, bot.id, message.chat.id, pinned.message_id):
        await _delete(bot, message.chat.id, message.message_id)
        return
    task = asyncio.create_task(_recheck_pin(bot, sm, message.chat.id, message.message_id, pinned.message_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# --------------------------------------------------------------------------- group -> supergroup
async def _migrate(bot: Bot, session: AsyncSession, bot_id: int, old_id: int, new_id: int) -> None:
    old = await chat_svc.chat_row(session, bot_id, old_id)
    if old is None:
        return
    duplicate = await chat_svc.chat_row(session, bot_id, new_id)
    if duplicate is not None and duplicate.id != old.id:
        # The bot was registered again in the new supergroup before this message arrived: the original row
        # (status, groups, history) stays.
        await chat_svc.close_notices(bot, session, duplicate, "rq.closed.removed")
        await session.delete(duplicate)
        await session.flush()
    log.info("Chat %s migrated to %s", old_id, new_id)
    old.chat_id = new_id
    old.type = ChatType.GROUP


@router.message(F.migrate_to_chat_id, F.chat.type.in_(GROUP_TYPES))
async def on_migrate_to(message: Message, bot: Bot, session: AsyncSession) -> None:
    if message.migrate_to_chat_id:
        await _migrate(bot, session, bot.id, message.chat.id, message.migrate_to_chat_id)


@router.message(F.migrate_from_chat_id, F.chat.type.in_(GROUP_TYPES))
async def on_migrate_from(message: Message, bot: Bot, session: AsyncSession) -> None:
    if message.migrate_from_chat_id:
        await _migrate(bot, session, bot.id, message.migrate_from_chat_id, message.chat.id)


# --------------------------------------------------------------------------- discovery
# Telegram can't list the chats where a bot is admin: a bot connected after working elsewhere finds them when they
# post. Each chat is looked up at most once per DISCOVERY_TTL seconds, DISCOVERY_DELAY seconds later: the
# my_chat_member update of a bot just added (who added it decides how it enters) always goes first.
DISCOVERY_TTL = 3600.0
DISCOVERY_DELAY = 5.0
DISCOVERY_CACHE_MAX = 100_000
_discovered: dict[tuple[int, int], float] = {}


def _first_look(bot_id: int, chat_id: int) -> bool:
    """True when the chat wasn't looked up recently (marked before any await, so two updates of the same chat
    don't both look it up)."""
    now = time.monotonic()
    key = (bot_id, chat_id)
    if _discovered.get(key, 0.0) > now:
        return False
    if len(_discovered) >= DISCOVERY_CACHE_MAX:
        _discovered.clear()
    _discovered[key] = now + DISCOVERY_TTL
    return True


def _membership_notice(message: Message) -> bool:
    """Service messages of members joining or leaving, or of a new chat: the my_chat_member update says it all."""
    return bool(message.new_chat_members or message.left_chat_member or message.group_chat_created
                or message.supergroup_chat_created or message.channel_chat_created)


async def _discover(bot: Bot, sm: SessionMaker, settings: Settings, chat_id: int) -> None:
    set_low_priority()
    try:
        await asyncio.sleep(DISCOVERY_DELAY)
        async with chat_svc.chat_lock(bot.id, chat_id), session_scope(sm) as session:
            if await chat_svc.chat_row(session, bot.id, chat_id) is not None:
                return
            rec = await session.get(BotRecord, bot.id)
            if rec is None or rec.status != BotStatus.ACTIVE:
                return
            outcome = await chat_svc.register_existing(bot, session, rec, chat_id, settings=settings)
        if outcome not in (chat_svc.NOT_ADMIN, chat_svc.NOT_FOUND):
            log.info("Discovered chat %s of bot %s: %s", chat_id, bot.id, outcome)
    except Exception:  # noqa: BLE001 - background task: never let it die silently
        log.exception("Discovery of chat %s failed for bot %s", chat_id, bot.id)


@router.channel_post()
@router.message(F.chat.type.in_(GROUP_TYPES))
async def on_chat_activity(message: Message, bot: Bot, ctx: Ctx, session: AsyncSession, settings: Settings,
                           sm: SessionMaker) -> None:
    if _hub(ctx, settings) or _membership_notice(message) or not _first_look(bot.id, message.chat.id):
        return
    if await chat_svc.chat_row(session, bot.id, message.chat.id) is not None:
        return
    task = asyncio.create_task(_discover(bot, sm, settings, message.chat.id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
