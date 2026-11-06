"""Runs many Telegram bots (main bot + clones) inside one process."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.utils.token import TokenValidationError
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    AiogramError,
    ClientDecodeError,
    TelegramConflictError,
    TelegramNetworkError,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.types import BotCommand, Update
from pydantic import ValidationError
from sqlalchemy import select, update

from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import BotStatus
from app.db.session import SessionMaker, session_scope
from app.telegram.context import bot_scope
from app.telegram.crypto import TokenCipher
from app.telegram.ratelimit import RateLimitMiddleware

if TYPE_CHECKING:
    from aiohttp import web

    from app.config import Settings
    from app.services.publisher import Publisher

log = logging.getLogger(__name__)

ALLOWED_UPDATES = [
    "message",
    "callback_query",
    "my_chat_member",
    "channel_post",
    "managed_bot",
]

# A bot that stops for good (paused, disconnected, disabled, deleted) deletes its pending auto deletes first, for
# this long at most.
WITHDRAW_TIMEOUT = 60.0
# setWebhook isn't retried by the rate limiter: tried this many times while the bot starts, then again in the
# background, waiting WEBHOOK_RETRY_WAIT seconds after the first failure and twice as long after each next one.
WEBHOOK_ATTEMPTS = 3
WEBHOOK_RETRY_WAIT = 1.0
WEBHOOK_RETRY_MAX = 300.0
WEBHOOK_REQUEST_TIMEOUT = 20


class BotTokenError(Exception):
    """The token is invalid or the bot can't be used."""


class BotManager:
    def __init__(self, dp: Dispatcher, settings: Settings, sessionmaker: SessionMaker) -> None:
        self.dp = dp
        self.settings = settings
        self.sm = sessionmaker
        self.cipher = TokenCipher(settings)
        self.bots: dict[int, Bot] = {}
        self.main_bot_id: int | None = None  # BOT_TOKEN: sends the platform notices
        self.main_bot_ids: set[int] = set()  # the main bot and its copies (EXTRA_MAIN_TOKENS)
        self._bot_tasks: dict[int, asyncio.Task[None]] = {}  # per bot: its polling loop, or its pending setWebhook
        self._inflight: set[asyncio.Task[Any]] = set()
        self._semaphores: dict[int, asyncio.Semaphore] = {}
        self._stopping = False
        self._started = False  # start() is done: a bot started later resumes its pending publications itself
        self._retiring: set[int] = set()  # bots being stopped: the scheduler starts nothing new for them
        self._invalidating: set[int] = set()
        self._locks: dict[int, asyncio.Lock] = {}  # start / stop of one bot, one at a time
        self.on_bot_invalid: list[Callable[[int], Any]] = []

    # ------------------------------------------------------------------ bots
    def _api_server(self) -> TelegramAPIServer | None:
        if self.settings.TELEGRAM_API_BASE:
            return TelegramAPIServer.from_base(self.settings.TELEGRAM_API_BASE)
        return None

    def build_bot(self, token: str) -> Bot:
        api = self._api_server()
        session = AiohttpSession(api=api) if api else AiohttpSession()
        session.middleware(RateLimitMiddleware(self.settings, on_unauthorized=self._on_unauthorized))
        return Bot(
            token=token,
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
        )

    def _on_unauthorized(self, bot_id: int) -> None:
        """A running bot got 401: its token was revoked. Stop it and mark it invalid (once)."""
        if bot_id not in self.bots or bot_id in self._invalidating:
            return
        self._invalidating.add(bot_id)

        async def invalidate() -> None:
            try:
                await self.stop_bot(bot_id)
                await self._mark_invalid(bot_id, "unauthorized")
            finally:
                self._invalidating.discard(bot_id)

        self._spawn(invalidate())

    def get(self, bot_id: int) -> Bot | None:
        return self.bots.get(bot_id)

    @property
    def main_bot(self) -> Bot | None:  # noqa: D401
        return self.bots.get(self.main_bot_id) if self.main_bot_id else None

    def is_running(self, bot_id: int) -> bool:
        """Running and not being stopped (the scheduler starts work only for these)."""
        return bot_id in self.bots and bot_id not in self._retiring

    @property
    def _publisher(self) -> Publisher | None:
        """The publishing engine, shared with the handlers through the dispatcher (None in a bare manager)."""
        return self.dp.workflow_data.get("publisher")

    async def start(self) -> None:
        await self._ensure_main_bots()
        async with self.sm() as s:
            records = (await s.execute(
                select(BotRecord).where(BotRecord.status == BotStatus.ACTIVE)
                .order_by(BotRecord.is_main.desc(), BotRecord.id)
            )).scalars().all()
        for rec in records:  # main bot first: it sends the notices about the clones
            try:
                await self.start_bot(rec)
            except Exception:  # noqa: BLE001
                log.exception("Could not start bot %s (@%s)", rec.id, rec.username)
        self._started = True  # Publisher.resume() goes on with the publications of the bots started so far

    async def _get_me(self, token: str) -> Any:
        bot = self.build_bot(token)
        try:
            return await bot.get_me()
        finally:
            await bot.session.close()

    async def _ensure_main_bots(self) -> None:
        """Registers the main bot (BOT_TOKEN) and its copies (EXTRA_MAIN_TOKENS) as main bots.

        A copy works exactly like the main bot under another username. A bad copy token is logged and skipped;
        bots that are no longer listed stop being main bots.
        """
        owner = self.settings.primary_super_admin
        if owner is None:
            raise RuntimeError("SUPER_ADMIN_IDS must contain at least one Telegram user id")
        mains: list[tuple[str, Any]] = [(self.settings.BOT_TOKEN, await self._get_me(self.settings.BOT_TOKEN))]
        for token in self.settings.main_copy_tokens:
            try:
                me = await self._get_me(token)
            except Exception:  # noqa: BLE001 - one bad copy must not stop the platform
                log.error("A token of EXTRA_MAIN_TOKENS can't be used; that copy of the main bot is skipped",
                          exc_info=True)
                continue
            if all(me.id != other.id for _, other in mains):
                mains.append((token, me))
        ids = {me.id for _, me in mains}
        async with session_scope(self.sm) as s:
            for other in (await s.execute(select(BotRecord).where(BotRecord.is_main.is_(True)))).scalars():
                if other.id not in ids:
                    other.is_main = False
            for token, me in mains:
                rec = await s.get(BotRecord, me.id)
                if rec is None:
                    rec = BotRecord(id=me.id, owner_id=owner, token_enc="", timezone=self.settings.DEFAULT_TIMEZONE,
                                    timezone_set=True)
                    s.add(rec)
                rec.is_main = True
                rec.owner_id = owner
                rec.username = me.username or ""
                rec.name = me.full_name
                rec.token_enc = self.cipher.encrypt(token)
                rec.status = BotStatus.ACTIVE
                rec.status_reason = None
        self.main_bot_id = mains[0][1].id
        self.main_bot_ids = ids
        for _, me in mains:
            log.info("Main bot: @%s (%s)%s", me.username, me.id, "" if me.id == self.main_bot_id else " (copy)")

    async def validate_token(self, token: str) -> Any:
        """Returns ``getMe`` of the token or raises :class:`BotTokenError`."""
        token = token.strip()
        if ":" not in token or not token.split(":", 1)[0].isdigit():
            raise BotTokenError("format")
        try:
            bot = self.build_bot(token)
        except TokenValidationError as exc:  # e.g. spaces inside it
            raise BotTokenError("format") from exc
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError as exc:
            raise BotTokenError("unauthorized") from exc
        except Exception as exc:  # noqa: BLE001
            raise BotTokenError("network") from exc
        finally:
            await bot.session.close()
        if not me.is_bot:
            raise BotTokenError("not_bot")
        return me

    async def add_bot(self, token: str, owner_id: int, *, managed: bool = False, pending: bool = False) -> BotRecord:
        """Registers (or re-activates) a clone and starts it. ``pending``: it waits for a super admin's approval
        (stored but not started; ``enable_bot`` starts it)."""
        me = await self.validate_token(token)
        if me.id in self.main_bot_ids:
            raise BotTokenError("is_main")
        async with session_scope(self.sm) as s:
            rec = await s.get(BotRecord, me.id)
            if rec is not None and rec.owner_id != owner_id and rec.status != BotStatus.INVALID:
                raise BotTokenError("taken")
            if rec is None:
                rec = BotRecord(id=me.id, owner_id=owner_id, token_enc="", timezone=self.settings.DEFAULT_TIMEZONE)
                s.add(rec)
            rec.owner_id = owner_id
            rec.username = me.username or ""
            rec.name = me.full_name
            rec.token_enc = self.cipher.encrypt(token.strip())
            rec.managed = managed or rec.managed
            rec.status = BotStatus.PENDING if pending else BotStatus.ACTIVE
            rec.status_reason = None
        await self.stop_bot(me.id)
        if not pending:
            await self.start_bot(rec)
        return rec

    def _lock(self, bot_id: int) -> asyncio.Lock:
        lock = self._locks.get(bot_id)
        if lock is None:
            lock = self._locks[bot_id] = asyncio.Lock()
        return lock

    async def start_bot(self, rec: BotRecord) -> None:
        # Waits for a stop of the same bot in progress (e.g. ▶️ Activar while ⏸ still withdraws its posts): starting
        # it meanwhile would be undone when that stop drops it.
        async with self._lock(rec.id):
            await self._start_bot(rec)

    async def _start_bot(self, rec: BotRecord) -> None:
        if rec.id in self.bots:
            return
        token = self.cipher.decrypt(rec.token_enc)
        if not token:
            await self._mark_invalid(rec.id, "decrypt")
            return
        bot = self.build_bot(token)
        self.bots[rec.id] = bot
        self._semaphores[rec.id] = asyncio.Semaphore(self.settings.UPDATE_CONCURRENCY_PER_BOT)
        try:
            await bot.set_my_commands([BotCommand(command="start", description="Menu / Menú")])
        except TelegramUnauthorizedError:
            await self._drop(rec.id)
            await self._mark_invalid(rec.id, "unauthorized")  # once, also when the rate limiter reported it
            return
        except Exception:  # noqa: BLE001
            log.warning("set_my_commands failed for %s", rec.id, exc_info=True)
        if self.settings.MODE == "webhook":
            if not await self._start_webhook(bot):
                return
        else:
            self._bot_tasks[rec.id] = asyncio.create_task(self._poll(bot), name=f"poll-{rec.id}")
        log.info("Bot started: @%s (%s)", rec.username, rec.id)
        if self._started:
            await self._resume_publications(rec.id)

    async def _resume_publications(self, bot_id: int) -> None:
        """A bot started after the process start goes on with the runs it left half-done (at startup,
        ``Publisher.resume`` does it for every bot running then)."""
        publisher = self._publisher
        if publisher is None:
            return
        try:
            await publisher.resume_bot(bot_id)
        except Exception:  # noqa: BLE001 - the bot runs anyway; the scheduler retries its due deletions
            log.exception("Pending publications of bot %s could not be resumed", bot_id)

    async def stop_bot(self, bot_id: int, *, delete_webhook: bool = False, withdraw: bool = False) -> None:
        """Stops a running bot. ``withdraw``: it stops for good (paused, disconnected, disabled or deleted) while its
        token still works, so its live deliveries with an auto delete are deleted first: nothing deletes them while
        it isn't running."""
        async with self._lock(bot_id):
            await self._stop_bot(bot_id, delete_webhook=delete_webhook, withdraw=withdraw)

    async def _stop_bot(self, bot_id: int, *, delete_webhook: bool, withdraw: bool) -> None:
        self._retiring.add(bot_id)
        try:
            if withdraw and bot_id in self.bots:
                await self._withdraw(bot_id)
            task = self._bot_tasks.pop(bot_id, None)
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            bot = self.bots.get(bot_id)
            if bot and delete_webhook:
                try:
                    await bot.delete_webhook()
                except Exception:  # noqa: BLE001
                    pass
            await self._drop(bot_id)
        finally:
            self._retiring.discard(bot_id)

    async def _withdraw(self, bot_id: int) -> None:
        """Deletes the deliveries the bot has up in its chats waiting for an auto delete, within WITHDRAW_TIMEOUT."""
        publisher = self._publisher
        if publisher is None:
            return
        try:
            with bot_scope(bot_id):
                await publisher.withdraw_bot(bot_id, timeout=WITHDRAW_TIMEOUT)
        except Exception:  # noqa: BLE001 - the bot stops anyway
            log.exception("The posts of bot %s could not be withdrawn before it stopped", bot_id)

    async def _drop(self, bot_id: int) -> None:
        bot = self.bots.pop(bot_id, None)
        self._semaphores.pop(bot_id, None)
        if bot:
            await bot.session.close()

    async def disable_bot(self, bot_id: int, reason: str | None = None) -> None:
        """Stops a bot for good (paused or disconnected by its owner, disabled by a super admin). It is marked
        first, so it handles no update and starts no run while its deliveries are withdrawn."""
        async with session_scope(self.sm) as s:
            rec = await s.get(BotRecord, bot_id)
            if rec:
                rec.status = BotStatus.DISABLED
                rec.status_reason = reason
        await self.stop_bot(bot_id, delete_webhook=True, withdraw=True)

    async def enable_bot(self, bot_id: int) -> bool:
        async with session_scope(self.sm) as s:
            rec = await s.get(BotRecord, bot_id)
            if rec is None:
                return False
            rec.status = BotStatus.ACTIVE
            rec.status_reason = None
        if bot_id in self._retiring:
            # It is still being stopped (its posts are withdrawn, up to a minute): it starts as soon as that ends,
            # without keeping the caller (a button press) waiting.
            self._spawn(self.start_bot(rec))
            return True
        await self.start_bot(rec)
        return bot_id in self.bots

    async def _mark_invalid(self, bot_id: int, reason: str) -> None:
        """Marks the bot invalid and runs the ``on_bot_invalid`` callbacks (the owner's DM) only when it wasn't
        already: a revoked token is usually found by several requests at once."""
        async with session_scope(self.sm) as s:
            res = await s.execute(
                update(BotRecord).where(BotRecord.id == bot_id, BotRecord.status != BotStatus.INVALID)
                .values(status=BotStatus.INVALID, status_reason=reason)
            )
        if not res.rowcount:
            return
        log.error("Bot %s marked invalid: %s", bot_id, reason)
        for cb in self.on_bot_invalid:
            try:
                out = cb(bot_id)
                if asyncio.iscoroutine(out):
                    await out
            except Exception:  # noqa: BLE001
                log.exception("on_bot_invalid callback failed")

    # --------------------------------------------------------------- updates
    async def feed(self, bot: Bot, update: Update) -> None:
        sem = self._semaphores.get(bot.id)
        if sem is None:
            return
        async with sem:
            try:
                with bot_scope(bot.id):
                    await self.dp.feed_update(bot, update)
            except Exception:  # noqa: BLE001
                log.exception("Unhandled error while processing update %s for bot %s", update.update_id, bot.id)

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    @staticmethod
    def _read_update(bot: Bot, data: Any) -> Update | None:
        """``data`` as an :class:`Update`, or None (logged) when aiogram can't read it, e.g. when a field its models
        require is missing: that update is skipped instead of holding up the ones after it."""
        try:
            return Update.model_validate(data, context={"bot": bot})
        except ValidationError as exc:
            update_id = data.get("update_id") if isinstance(data, dict) else None
            errors = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])
            log.error("Update %s for bot %s can't be read and was skipped: %s", update_id, bot.id, errors)
            return None

    async def _get_updates(self, bot: Bot, offset: int | None) -> tuple[list[Update], int | None]:
        """``getUpdates``: the updates and the offset that confirms them."""
        try:
            updates = await bot.get_updates(
                offset=offset, timeout=50, allowed_updates=ALLOWED_UPDATES, request_timeout=65
            )
        except ClientDecodeError as exc:
            # One update aiogram can't read fails the whole answer, again on every call: the offset would never
            # get past it and the bot would receive nothing more. The answer is read update by update instead.
            items = exc.data.get("result") if isinstance(exc.data, dict) and exc.data.get("ok") else None
            if not isinstance(items, list):
                raise
            ids = [i["update_id"] for i in items if isinstance(i, dict) and isinstance(i.get("update_id"), int)]
            if not ids:
                raise
            read = [self._read_update(bot, item) for item in items]
            return [u for u in read if u is not None], max(ids) + 1
        return updates, (updates[-1].update_id + 1 if updates else offset)

    async def _poll(self, bot: Bot) -> None:
        offset: int | None = None
        backoff = 1.0
        try:
            await bot.delete_webhook(drop_pending_updates=False)
        except TelegramUnauthorizedError:
            await self._drop(bot.id)
            await self._mark_invalid(bot.id, "unauthorized")
            return
        except Exception:  # noqa: BLE001
            log.warning("delete_webhook failed for %s", bot.id, exc_info=True)
        while not self._stopping:
            try:
                updates, offset = await self._get_updates(bot, offset)
                backoff = 1.0
                for upd in updates:
                    sem = self._semaphores.get(bot.id)
                    if sem is None:
                        return
                    # Back-pressure: wait while this bot already processes many updates.
                    while sem.locked():
                        await asyncio.sleep(0.05)
                    self._spawn(self.feed(bot, upd))
            except asyncio.CancelledError:
                raise
            except TelegramUnauthorizedError:
                await self._drop(bot.id)
                await self._mark_invalid(bot.id, "unauthorized")
                return
            except TelegramConflictError:
                log.warning("Polling conflict for bot %s (another instance?). Retrying in 15s", bot.id)
                await asyncio.sleep(15)
            except (TelegramNetworkError, TelegramServerError, asyncio.TimeoutError) as exc:
                log.warning("Polling error for bot %s: %s. Retrying in %.0fs", bot.id, exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except Exception:  # noqa: BLE001
                log.exception("Unexpected polling error for bot %s", bot.id)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    # --------------------------------------------------------------- webhook
    def webhook_secret(self, bot_id: int) -> str:
        key = (self.settings.WEBHOOK_SECRET or self.settings.BOT_TOKEN).encode()
        return hmac.new(key, str(bot_id).encode(), hashlib.sha256).hexdigest()

    def webhook_url(self, bot_id: int) -> str:
        base = (self.settings.WEBHOOK_BASE_URL or "").rstrip("/")
        return f"{base}{self.settings.WEBHOOK_PATH_PREFIX}/{bot_id}"

    async def _set_webhook(self, bot: Bot) -> None:
        if not self.settings.WEBHOOK_BASE_URL:
            raise RuntimeError("WEBHOOK_BASE_URL is required in webhook mode")
        await bot.set_webhook(
            url=self.webhook_url(bot.id),
            secret_token=self.webhook_secret(bot.id),
            allowed_updates=ALLOWED_UPDATES,
            drop_pending_updates=False,
            request_timeout=WEBHOOK_REQUEST_TIMEOUT,
        )

    async def _start_webhook(self, bot: Bot) -> bool:
        """Points the bot's updates to us. Without its webhook a started bot would get no update until a restart:
        a failure is retried a few times now, then in the background until it works. False: token revoked."""
        wait = WEBHOOK_RETRY_WAIT
        for attempt in range(1, WEBHOOK_ATTEMPTS + 1):
            if attempt > 1:
                await asyncio.sleep(wait)
                wait = min(wait * 2, WEBHOOK_RETRY_MAX)
            try:
                await self._set_webhook(bot)
                return True
            except TelegramUnauthorizedError:
                await self._drop(bot.id)
                await self._mark_invalid(bot.id, "unauthorized")
                return False
            except AiogramError as exc:
                log.warning("setWebhook failed for bot %s (try %d/%d): %s", bot.id, attempt, WEBHOOK_ATTEMPTS, exc)
        log.warning("Bot %s gets no updates until its webhook is set: retrying in the background", bot.id)
        self._bot_tasks[bot.id] = asyncio.create_task(self._retry_webhook(bot, wait), name=f"webhook-{bot.id}")
        return True

    async def _retry_webhook(self, bot: Bot, wait: float) -> None:
        """setWebhook in the background, with growing waits, until it works or the bot stops."""
        while True:
            await asyncio.sleep(wait)
            wait = min(wait * 2, WEBHOOK_RETRY_MAX)
            try:
                await self._set_webhook(bot)
            except TelegramUnauthorizedError:
                await self._drop(bot.id)
                await self._mark_invalid(bot.id, "unauthorized")
                return
            except AiogramError as exc:
                log.warning("setWebhook failed for bot %s: %s. Next try in %.0fs", bot.id, exc, wait)
                continue
            log.info("Webhook of bot %s set: it receives updates now", bot.id)
            return

    def webhook_routes(self, app: web.Application) -> None:
        from aiohttp import web

        async def handle(request: web.Request) -> web.Response:
            try:
                bot_id = int(request.match_info["bot_id"])
            except ValueError:
                return web.Response(status=404)
            bot = self.bots.get(bot_id)
            if bot is None:
                return web.Response(status=404)
            secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not hmac.compare_digest(secret, self.webhook_secret(bot_id)):
                return web.Response(status=401)
            try:
                data = await request.json()
            except Exception:  # noqa: BLE001
                log.warning("Webhook request for bot %s without a JSON body", bot_id)
                return web.Response(status=400)
            update = self._read_update(bot, data)
            if update is not None:
                self._spawn(self.feed(bot, update))
            # An update that can't be read is acknowledged too: Telegram would only send it again, in vain.
            return web.Response(text="ok")

        app.router.add_post(f"{self.settings.WEBHOOK_PATH_PREFIX}/{{bot_id}}", handle)

    # -------------------------------------------------------------- shutdown
    async def shutdown(self, timeout: float = 15.0) -> None:
        self._stopping = True
        for bot_id in list(self._bot_tasks):
            task = self._bot_tasks.pop(bot_id)
            task.cancel()
        if self._inflight:
            done, pending = await asyncio.wait(list(self._inflight), timeout=timeout)
            for task in pending:
                task.cancel()
        for bot_id in list(self.bots):
            await self._drop(bot_id)

    async def touch(self) -> None:
        """Updates ``updated_at`` of running bots (liveness marker)."""
        async with session_scope(self.sm) as s:
            for bot_id in self.bots:
                rec = await s.get(BotRecord, bot_id)
                if rec:
                    rec.updated_at = utcnow()
