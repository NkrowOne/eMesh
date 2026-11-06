"""Telegram rate limiting for every outgoing Bot API request.

Limits (per bot token, from the official FAQ):
* ~30 messages per second in total (bulk). We keep a global bucket below that and
  a lower "bulk" bucket for background jobs so interactive replies always have headroom.
* 1 message per second per private chat (short bursts allowed).
* 20 messages per minute per group / channel.
* 429 responses carry ``retry_after``: the affected chat (or the whole bot when the
  flood is global) is paused for that long and the request is retried.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiohttp import ClientConnectorError
from aiogram.exceptions import (
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)

from app.telegram.context import Priority, request_priority

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.methods import Response, TelegramMethod

    from app.config import Settings

log = logging.getLogger(__name__)

# Methods that create or modify messages inside a specific chat (per chat limits apply).
CHAT_SCOPED = frozenset(
    {
        "sendMessage", "sendPhoto", "sendVideo", "sendAnimation", "sendAudio", "sendDocument",
        "sendVoice", "sendVideoNote", "sendSticker", "sendMediaGroup", "sendLocation", "sendVenue",
        "sendContact", "sendPoll", "sendDice", "sendInvoice", "sendPaidMedia", "sendLivePhoto",
        "sendRichMessage", "sendChecklist", "copyMessage", "copyMessages", "forwardMessage",
        "forwardMessages", "editMessageText", "editMessageCaption", "editMessageMedia",
        "editMessageReplyMarkup", "pinChatMessage",
    }
)
# Not retried after a network/5xx error: the request may have been applied already, and repeating it
# would duplicate a message or turn a successful delete into a false "already deleted".
NOT_IDEMPOTENT = frozenset(
    (CHAT_SCOPED - {"editMessageText", "editMessageCaption", "editMessageMedia", "editMessageReplyMarkup",
                    "pinChatMessage"})
    | {"deleteMessage", "deleteMessages", "createChatSubscriptionInviteLink"}
)
# Never throttled (long polling, webhook management).
EXEMPT = frozenset({"getUpdates", "setWebhook", "deleteWebhook", "getWebhookInfo", "getMe", "close", "logOut"})
# Their 429s say nothing about the messages the bot sends: only that method waits (never the whole bot), and a
# wait longer than MAX_LOOKUP_WAIT is handed to the caller at once (link checks, membership probes) instead of
# keeping it busy.
LOOKUPS = frozenset({
    "createChatInviteLink", "editChatInviteLink", "revokeChatInviteLink", "exportChatInviteLink",
    "getChat", "getChatMember", "getChatMemberCount", "getChatAdministrators",
})
MAX_LOOKUP_WAIT = 30.0


def _never_sent(exc: BaseException) -> bool:
    """The connection to Telegram couldn't even be opened: the request never got there, so it can be repeated."""
    return isinstance(exc, TelegramNetworkError) and isinstance(exc.__cause__, ClientConnectorError)


class TokenBucket:
    """FIFO async token bucket."""

    def __init__(self, rate: float, capacity: float) -> None:
        self.rate = max(rate, 0.001)
        self.capacity = max(capacity, 1.0)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.blocked_until = 0.0
        self._lock = asyncio.Lock()

    def _refill(self, now: float) -> None:
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                if now < self.blocked_until:
                    await asyncio.sleep(self.blocked_until - now)
                    continue
                self._refill(now)
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)

    def block(self, seconds: float) -> None:
        now = time.monotonic()
        self.blocked_until = max(self.blocked_until, now + seconds)
        self._refill(now)
        self.tokens = 0

    async def wait_blocked(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                if now < self.blocked_until:
                    await asyncio.sleep(self.blocked_until - now)
                    continue
                return


class SlidingWindow:
    """At most ``limit`` acquisitions in any ``window`` seconds."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit = max(limit, 1)
        self.window = window
        self.events: deque[float] = deque()
        self.blocked_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                if now < self.blocked_until:
                    await asyncio.sleep(self.blocked_until - now)
                    continue
                while self.events and now - self.events[0] >= self.window:
                    self.events.popleft()
                if len(self.events) < self.limit:
                    self.events.append(now)
                    return
                await asyncio.sleep(self.window - (now - self.events[0]) + 0.01)

    def block(self, seconds: float) -> None:
        self.blocked_until = max(self.blocked_until, time.monotonic() + seconds)

    async def wait_blocked(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                if now < self.blocked_until:
                    await asyncio.sleep(self.blocked_until - now)
                    continue
                return

    async def wait_free(self) -> None:
        """Waits until a slot is free, without taking it (the request then takes the global tokens and its slot
        together, so requests that waited for a busy chat don't all go out in one burst)."""
        while True:
            now = time.monotonic()
            if now < self.blocked_until:
                await asyncio.sleep(self.blocked_until - now)
                continue
            while self.events and now - self.events[0] >= self.window:
                self.events.popleft()
            if len(self.events) < self.limit:
                return
            await asyncio.sleep(self.window - (now - self.events[0]) + 0.01)


class RateLimiter:
    """All limiters of one bot token."""

    MAX_CHATS = 20_000

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Small bursts only: with capacity c and rate r a 1s window never sees more than c + r requests.
        g = settings.RL_GLOBAL_PER_SEC
        b = settings.RL_BULK_PER_SEC
        self.global_bucket = TokenBucket(g, max(1.0, round(g * 0.1)))
        self.bulk_bucket = TokenBucket(b, max(1.0, round(b * 0.1)))
        self._chats: OrderedDict[int, TokenBucket | SlidingWindow] = OrderedDict()
        self._recent_429: deque[tuple[float, int | None]] = deque()
        self._lookups_blocked: dict[str, float] = {}  # lookup method -> monotonic time its flood wait ends

    def chat_limiter(self, chat_id: int) -> TokenBucket | SlidingWindow:
        lim = self._chats.get(chat_id)
        if lim is None:
            if chat_id > 0:
                lim = TokenBucket(self.settings.RL_PRIVATE_PER_SEC, self.settings.RL_PRIVATE_BURST)
            else:
                lim = SlidingWindow(self.settings.RL_GROUP_PER_MIN, 60.0)
            self._chats[chat_id] = lim
            if len(self._chats) > self.MAX_CHATS:
                self._chats.popitem(last=False)
        else:
            self._chats.move_to_end(chat_id)
        return lim

    def on_retry_after(self, chat_id: int | None, seconds: float) -> None:
        now = time.monotonic()
        self._recent_429.append((now, chat_id))
        while self._recent_429 and now - self._recent_429[0][0] > 10:
            self._recent_429.popleft()
        distinct = {c for _, c in self._recent_429}
        if chat_id is not None:
            self.chat_limiter(chat_id).block(seconds)
        if chat_id is None or len(distinct) >= 3 or seconds >= 10:
            self.global_bucket.block(seconds)
            self.bulk_bucket.block(seconds)

    def block_lookup(self, name: str, seconds: float) -> None:
        self._lookups_blocked[name] = max(self._lookups_blocked.get(name, 0.0), time.monotonic() + seconds)

    def lookup_wait(self, name: str) -> float:
        """Seconds left of the flood wait of a lookup method (0 when it can be called)."""
        return max(0.0, self._lookups_blocked.get(name, 0.0) - time.monotonic())

    async def wait_chat_block(self, chat_id: int) -> None:
        lim = self._chats.get(chat_id)
        if lim is not None and lim.blocked_until > time.monotonic():
            await lim.wait_blocked()


class RateLimitMiddleware(BaseRequestMiddleware):
    """aiogram request middleware: throttles, retries 429 / 5xx / network errors."""

    def __init__(self, settings: Settings, on_unauthorized: Callable[[int], None] | None = None) -> None:
        self.settings = settings
        self.limiter = RateLimiter(settings)
        self.on_unauthorized = on_unauthorized

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[Any],
        bot: Bot,
        method: TelegramMethod[Any],
    ) -> Response[Any]:
        name = getattr(method, "__api_method__", "")
        if name in EXEMPT:
            return await make_request(bot, method)

        chat_id = getattr(method, "chat_id", None)
        int_chat = chat_id if isinstance(chat_id, int) else None
        scoped_chat = int_chat if name in CHAT_SCOPED else None
        low = request_priority.get() is Priority.LOW
        rate_attempts = 0
        net_attempts = 0
        lookup = name in LOOKUPS
        while True:
            if lookup:
                left = self.limiter.lookup_wait(name)
                if left > MAX_LOOKUP_WAIT:
                    raise TelegramRetryAfter(method=method, message=f"Flood control on {name} (waiting locally)",
                                             retry_after=math.ceil(left))
                if left:
                    await asyncio.sleep(left)
            chat_lim = self.limiter.chat_limiter(scoped_chat) if scoped_chat is not None else None
            if isinstance(chat_lim, SlidingWindow):
                await chat_lim.wait_free()
            elif chat_lim is None and int_chat is not None:
                await self.limiter.wait_chat_block(int_chat)
            if low:
                await self.limiter.bulk_bucket.acquire()
            await self.limiter.global_bucket.acquire()
            if chat_lim is not None:
                await chat_lim.acquire()
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as exc:
                rate_attempts += 1
                wait = float(exc.retry_after) + random.uniform(0.2, 0.8)
                if lookup:
                    # Only this method is limited: the bot keeps sending, and a long wait goes back to the caller.
                    self.limiter.block_lookup(name, wait)
                    log.warning("429 on %s chat=%s, retry_after %ss", name, chat_id, exc.retry_after)
                    if wait > MAX_LOOKUP_WAIT or rate_attempts > self.settings.RL_MAX_RETRIES:
                        raise
                    continue
                self.limiter.on_retry_after(int_chat, wait)
                log.warning("429 on %s chat=%s, retry in %.1fs (attempt %d)", name, chat_id, wait, rate_attempts)
                if rate_attempts > self.settings.RL_MAX_RETRIES:
                    raise
            except TelegramUnauthorizedError:
                if self.on_unauthorized is not None:
                    self.on_unauthorized(bot.id)
                raise
            except (TelegramServerError, TelegramNetworkError) as exc:
                net_attempts += 1
                if (name in NOT_IDEMPOTENT and not _never_sent(exc)) or net_attempts > self.settings.RL_NETWORK_RETRIES:
                    raise
                delay = min(2.0**net_attempts, 10.0) + random.uniform(0, 0.5)
                log.warning("%s on %s: %s; retry in %.1fs", type(exc).__name__, name, exc, delay)
                await asyncio.sleep(delay)
