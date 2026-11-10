"""📤 Publishing engine: a *run* sends one post to a set of chats; in each chat it leaves a *delivery* (the message
there), deleted later by the auto delete, "delete previous", "one at a time", 🔚 Retirar or when the chat leaves.

Everything is in the database, so a restart never loses track of what went out: a run stores its deliveries
(``queued``) before sending, marks each batch ``sending`` right before the API calls and stores the results batch by
batch. After a restart :meth:`Publisher.resume` goes on with the queued deliveries; one left ``sending`` becomes
``unknown`` (it may be out) and is never sent again.

Concurrency: one run per post at a time (``is_busy``), ``SEND_CONCURRENCY`` chats at a time inside a run, and the
deliveries of a chat are handled by one batch at a time (a lock per chat), so "one at a time" and "delete previous"
never race with another run or a deletion.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any, TypeVar

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramMigrateToChat, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InputFile
from sqlalchemy import case, delete, func, select, update

from app.db.base import utcnow
from app.db.models import Bot as BotRecord
from app.db.models import (
    BotUser,
    Chat,
    ChatType,
    Delivery,
    DeliveryStatus,
    Post,
    PostStatus,
    Run,
    RunKind,
    RunStatus,
)
from app.db.session import session_scope
from app.i18n import t
from app.services import audience, chatstate, content
from app.services import freq as freq_svc
from app.services.chatinfo import missing_rights
from app.services.notify import send_dm
from app.services.users import admin_ids
from app.telegram.context import Priority, bot_scope, request_priority
from app.telegram.errors import (
    is_button_error,
    is_cant_delete,
    is_chat_gone,
    is_message_gone,
    is_not_modified,
    is_outcome_unknown,
    is_rights_error,
    is_topic_error,
    is_unauthorized,
    short,
)
from app.ui.callbacks import MenuCB
from app.ui.common import btn, kb
from app.ui.fmt import esc, num, zone

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.config import Settings
    from app.db.session import SessionMaker
    from app.telegram.manager import BotManager

log = logging.getLogger(__name__)

T = TypeVar("T")

BATCH_SIZE = 25  # deliveries per DB transaction
LIVE_AGE = timedelta(hours=48)  # Telegram doesn't let bots delete older messages: they are no longer "live"
MAX_DELETE_AGE = timedelta(hours=47, minutes=55)  # an auto delete of 48 h is done a little before the limit
DELETE_RETRY = timedelta(minutes=5)  # a deletion Telegram didn't answer is tried again this much later
MEDIA_ALERT_EVERY = 24 * 3600.0  # seconds between two alerts to every admin about the same broken media
NO_BUTTONS = "no buttons: "  # Delivery.error of a message sent without its buttons (Telegram refused one)
DELIVERED = (DeliveryStatus.SENT, DeliveryStatus.DELETED, DeliveryStatus.MISSING, DeliveryStatus.EXPIRED)
PENDING = (DeliveryStatus.QUEUED, DeliveryStatus.SENDING)
GONE = "gone"
RIGHTS = "rights"
RETRY = "retry"  # deletion outcome: try again later (the delivery stays live)


def chunks(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


@contextmanager
def low_priority() -> Iterator[None]:
    """Background priority for the current task, restored afterwards (safe to use inline)."""
    token = request_priority.set(Priority.LOW)
    try:
        yield
    finally:
        request_priority.reset(token)


def delete_time(sent_at: datetime, minutes: int | None) -> datetime | None:
    """When a delivery is auto deleted (None: never), at most 48 h after it was sent."""
    if not minutes or minutes <= 0:
        return None
    return sent_at + min(timedelta(minutes=minutes), MAX_DELETE_AGE)


async def live_count(session: AsyncSession, post_id: int) -> int:
    """Deliveries of the post still up in the chats (sent, not deleted, younger than 48 h)."""
    q = select(func.count()).select_from(Delivery).where(
        Delivery.post_id == post_id, Delivery.status == DeliveryStatus.SENT, Delivery.message_id.is_not(None),
        Delivery.sent_at > utcnow() - LIVE_AGE)
    return int(await session.scalar(q) or 0)


class _ChatLocks:
    """One lock per chat (by pk): the batches that touch the deliveries of a chat (a send with its "delete previous",
    an auto delete, a retire...) go one at a time. Several are always taken in the same order: no deadlock."""

    def __init__(self) -> None:
        self._locks: dict[int, list[Any]] = {}  # chat pk -> [lock, holders and waiters]

    @asynccontextmanager
    async def hold(self, keys: Iterable[int | None]) -> AsyncIterator[None]:
        entries: list[tuple[int, list[Any]]] = []
        for key in sorted({k for k in keys if k is not None}):
            entry = self._locks.setdefault(key, [asyncio.Lock(), 0])
            entry[1] += 1
            entries.append((key, entry))
        taken: list[asyncio.Lock] = []
        try:
            for _, entry in entries:
                await entry[0].acquire()
                taken.append(entry[0])
            yield
        finally:
            for lock in reversed(taken):
                lock.release()
            for key, entry in entries:
                entry[1] -= 1
                if entry[1] <= 0 and self._locks.get(key) is entry:
                    del self._locks[key]


@dataclass
class _Live:
    """A delivery that is up in its chat (detached snapshot)."""

    id: int
    chat_pk: int | None
    chat_id: int
    message_id: int | None
    sent_at: datetime | None
    pinned: bool
    post_id: int | None

    @classmethod
    def of(cls, d: Delivery) -> _Live:
        return cls(d.id, d.chat_pk, d.chat_id, d.message_id, d.sent_at, bool(d.pinned), d.post_id)


@dataclass
class _Gone:
    """What happened when the bot tried to delete a delivery."""

    live: _Live
    status: str  # deleted / missing / expired, or RETRY
    error: str | None = None
    problem: str | None = None  # GONE / RIGHTS: the chat can't receive posts
    missing: list[str] = field(default_factory=list)
    unpinned: bool = False


@dataclass
class _Target:
    delivery_id: int
    chat_pk: int
    chat_id: int
    chat_type: str
    previous: list[_Live] = field(default_factory=list)  # deleted right before sending (one at a time / previous)
    unpin: list[_Live] = field(default_factory=list)  # older pinned copies of the post that stay in the chat


@dataclass
class _Result:
    target: _Target
    status: str = DeliveryStatus.FAILED
    message_id: int | None = None
    sent_at: datetime | None = None
    error: str | None = None
    chat_id: int | None = None  # final chat id (it changes when a group became a supergroup)
    migrated: bool = False
    problem: str | None = None
    missing: list[str] = field(default_factory=list)
    file_id: str | None = None  # the file id an upload got (media taken from another bot)
    previous: list[_Gone] = field(default_factory=list)
    pinned: bool = False


@dataclass
class _Job:
    """What a run needs while it sends (detached snapshots)."""

    run_id: int
    bot: Bot
    bot_id: int
    post: Post
    kind: str
    one_at_a_time: bool
    markup: InlineKeyboardMarkup | None
    no_buttons: bool = False  # Telegram refused a button: the rest goes without buttons
    media: str | InputFile | None = None

    @property
    def post_id(self) -> int:
        return self.post.id


@dataclass
class _Outcome:
    """A finished run, for its report."""

    bot_id: int
    post_id: int | None
    name: str
    total: int
    sent: int
    failed: int
    skipped: int
    unknown: int
    cancelled: bool = False
    media_error: str | None = None
    no_buttons: str | None = None


class _Stopped(Exception):
    """Shutdown, or the bot stopped, between two batches: the run stays ``sending`` and is resumed later."""


class _Cancelled(Exception):
    """The post is being retired or was deleted: the rest of the run is not sent."""


def _report_text(o: _Outcome, lang: str) -> str:
    post = esc(o.name or "—")
    if o.media_error:
        reason = t(f"eng.media.{'too_big' if o.media_error == 'too_big' else 'unavailable'}", lang)
        return t("eng.report.media", lang, post=post, reason=reason)
    if o.cancelled:
        return t("eng.report.cancelled", lang, post=post, sent=num(o.sent), total=num(o.total))
    parts = []
    if o.failed:
        parts.append(t("eng.report.failed_one" if o.failed == 1 else "eng.report.failed", lang, n=num(o.failed)))
    if o.skipped:
        parts.append(t("eng.report.skipped_one" if o.skipped == 1 else "eng.report.skipped", lang,
                       n=num(o.skipped)))
    if o.unknown:
        parts.append(t("eng.report.unknown", lang, n=num(o.unknown)))
    details = f" ({' · '.join(parts)})" if parts else ""
    text = t("eng.report", lang, post=post, sent=num(o.sent), total=num(o.total), details=details)
    if o.no_buttons:
        text += "\n" + t("eng.report.no_buttons", lang, error=esc(o.no_buttons.removeprefix(NO_BUTTONS)))
    return text


class Publisher:
    def __init__(self, manager: BotManager, sm: SessionMaker, settings: Settings) -> None:
        self.manager = manager
        self.sm = sm
        self.settings = settings
        self._claims: dict[int, int] = {}  # post id (or -run id) -> runs/retires running or waiting
        self._locks: dict[int, asyncio.Lock] = {}
        self._chats = _ChatLocks()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._cancel: set[int] = set()  # runs of a post being retired: they stop at their next batch
        self._withdrawing: set[int] = set()  # bots whose live deliveries are being withdrawn
        self._in_flight: dict[int, int] = {}  # bot id -> run batches being sent
        self._media_alerts: dict[tuple[int, str], float] = {}
        self._stopping = False

    # ------------------------------------------------------------------ state
    def stop_sending(self) -> None:
        """Shutdown: running runs stop after the batch in flight (all stored) and none starts; resume() goes on
        with them after the restart."""
        self._stopping = True

    def allow_sending(self) -> None:
        self._stopping = False

    def is_busy(self, post_id: int) -> bool:
        """A run (or a retire / update of the published copies) of this post is running or waiting."""
        return self._claims.get(post_id, 0) > 0

    def _claim(self, key: int) -> None:
        self._claims[key] = self._claims.get(key, 0) + 1

    def _release(self, key: int) -> None:
        left = self._claims.get(key, 1) - 1
        if left > 0:
            self._claims[key] = left
        else:
            self._claims.pop(key, None)
            self._locks.pop(key, None)

    async def _exclusive(self, key: int, fn: Callable[[], Awaitable[T]]) -> T:
        """Runs ``fn`` holding the lock of ``key`` (already claimed by the caller), at low priority."""
        try:
            async with self._locks.setdefault(key, asyncio.Lock()):
                with low_priority():
                    return await fn()
        finally:
            self._release(key)

    def _spawn(self, coro: Awaitable[Any], name: str) -> None:
        task = asyncio.create_task(self._background(coro, name), name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _background(coro: Awaitable[Any], name: str) -> None:
        try:
            with low_priority():
                await coro
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a background job must never die silently
            log.exception("Background job %s failed", name)

    async def wait_idle(self, timeout: float | None = None) -> None:
        """Waits for the runs started in the background; cancels the ones still running after ``timeout``."""
        while True:
            tasks = [task for task in self._tasks if not task.done()]
            if not tasks:
                return
            _, pending = await asyncio.wait(tasks, timeout=timeout)
            if pending:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                return

    def _halted(self, bot_id: int) -> bool:
        return self._stopping or bot_id in self._withdrawing or not self.manager.is_running(bot_id)

    async def _network_paused(self, bot_id: int) -> bool:
        async with self.sm() as s:
            return bool((await s.execute(select(BotRecord.paused).where(BotRecord.id == bot_id))).scalar())

    def _tz(self, rec: BotRecord | None) -> str:
        return (rec.timezone if rec is not None else None) or self.settings.DEFAULT_TIMEZONE

    @property
    def _concurrency(self) -> int:
        return max(1, int(self.settings.SEND_CONCURRENCY))

    # ------------------------------------------------------------- public API
    async def send_now(self, post_id: int, *, user_id: int | None = None) -> int | None:
        """🚀 Enviar ahora: a manual run to the post's audience, in the background. None when the post is busy or
        nobody can receive it."""
        if self.is_busy(post_id):
            return None
        async with session_scope(self.sm) as s:
            post = await s.get(Post, post_id)
            chats = await audience.audience(s, post) if post is not None else []
        if not chats:
            return None
        return await self.run(post_id, [c.id for c in chats], kind=RunKind.MANUAL, triggered_by=user_id)

    async def run(self, post_id: int, chat_pks: list[int], *, kind: str, source: str = "",
                  triggered_by: int | None = None, wait: bool = False) -> int | None:
        """Sends the post to these chats (only the sendable ones of its bot). Returns the run id, or None when the
        post is busy, its bot isn't running or no chat can receive it. ``wait``: send before returning."""
        if self._stopping or self.is_busy(post_id):
            log.info("Post %s is busy (or shutting down): run not started", post_id)
            return None
        self._claim(post_id)  # synchronously: is_busy() is right before the run is even stored
        try:
            run_id = await self._create_run(post_id, chat_pks, kind=kind, source=source, triggered_by=triggered_by)
        except BaseException:
            self._release(post_id)
            raise
        if run_id is None:
            self._release(post_id)
            return None
        job = self._exclusive(post_id, partial(self._send_run, run_id))
        if wait:
            await job
        else:
            self._spawn(job, name=f"run-{run_id}")
        return run_id

    async def retire(self, post_id: int) -> int:
        """🔚 Retirar: deletes every live delivery of the post now (a run of it in progress stops first). Returns how
        many were deleted."""
        self._claim(post_id)  # first: no new run of the post starts from now on
        try:
            async with session_scope(self.sm) as s:
                self._cancel.update((await s.execute(select(Run.id).where(
                    Run.post_id == post_id, Run.status == RunStatus.SENDING))).scalars())
        except BaseException:
            self._release(post_id)
            raise
        return await self._exclusive(post_id, partial(self._retire, post_id))

    async def update_live(self, post_id: int) -> tuple[int, int]:
        """🔄 Actualizar publicados: the live deliveries (< 48 h) get the current text and buttons of the post (not the
        media). Returns (edited, failed); "not modified" counts as edited."""
        self._claim(post_id)
        return await self._exclusive(post_id, partial(self._update_live, post_id))

    async def drop_chat(self, chat_pk: int) -> int:
        """The bot is about to leave the chat: its live deliveries there (any post) are deleted now, as it can't once
        it is out. Returns how many were deleted."""
        async with session_scope(self.sm) as s:
            chat = await s.get(Chat, chat_pk)
            bot_id = chat.bot_id if chat is not None else None
        if bot_id is None:
            return 0
        with bot_scope(bot_id):
            deleted = await self._delete_live(bot_id, Delivery.chat_pk == chat_pk)
        log.info("Chat %s: %d deliveries deleted before leaving it", chat_pk, deleted)
        return deleted

    async def delete_due(self, bot_id: int | None = None) -> int:
        """Auto delete: the live deliveries whose ``delete_at`` passed (of one bot, or of every running bot)."""
        bots = [bot_id] if bot_id is not None else [b for b in list(self.manager.bots) if self.manager.is_running(b)]
        now = utcnow()
        deleted = 0
        for b in bots:
            with low_priority(), bot_scope(b):
                deleted += await self._delete_live(b, Delivery.delete_at.is_not(None), Delivery.delete_at <= now)
        return deleted

    async def withdraw_bot(self, bot_id: int, *, timeout: float | None = None) -> int:
        """The bot stops for good while its token works: its live deliveries with an auto delete are deleted now, as
        nothing deletes them while it isn't running. Its runs stop after their current batch (they are resumed when
        it starts again). Gives up after ``timeout`` seconds. Returns how many were deleted."""
        self._withdrawing.add(bot_id)
        deleted: list[int] = [0]
        try:
            async with asyncio.timeout(timeout):
                # The batches in flight end first (what they send is withdrawn too), but never for the whole timeout.
                wait_until = asyncio.get_running_loop().time() + (timeout / 2 if timeout else 30.0)
                while self._in_flight.get(bot_id) and asyncio.get_running_loop().time() < wait_until:
                    await asyncio.sleep(0.05)
                with low_priority(), bot_scope(bot_id):
                    await self._delete_live(bot_id, Delivery.delete_at.is_not(None), counter=deleted)
        except TimeoutError:
            log.warning("Bot %s: its pending auto deletes could not all be done within %ss", bot_id, timeout)
        finally:
            self._withdrawing.discard(bot_id)
        log.info("Bot %s withdrawn: %d deliveries deleted", bot_id, deleted[0])
        return deleted[0]

    async def resume(self) -> None:
        """At startup: the runs a restart left half-done go on with their queued deliveries (those left ``sending``
        may be out: they become ``unknown`` and are never sent again)."""
        async with session_scope(self.sm) as s:
            lost = await s.execute(
                update(Delivery).where(Delivery.status == DeliveryStatus.SENDING)
                .values(status=DeliveryStatus.UNKNOWN, error="interrupted")
                .execution_options(synchronize_session=False))
            runs = (await s.execute(
                select(Run.id, Run.post_id, Run.bot_id).where(Run.status == RunStatus.SENDING).order_by(Run.id)
            )).all()
        if lost.rowcount:
            log.warning("%d deliveries were being sent when the process stopped: marked unknown", lost.rowcount)
        for run_id, post_id, bot_id in runs:
            self._resume_run(run_id, post_id, bot_id)

    async def resume_bot(self, bot_id: int) -> None:
        """Like :meth:`resume` for one bot started later (activated again): the runs it left half-done go on."""
        async with session_scope(self.sm) as s:
            runs = [r for r in (await s.execute(
                select(Run.id, Run.post_id, Run.bot_id).where(Run.bot_id == bot_id, Run.status == RunStatus.SENDING)
                .order_by(Run.id)
            )).all() if not self.is_busy(self._key(r.post_id, r.id))]
            if runs:
                await s.execute(
                    update(Delivery).where(Delivery.run_id.in_([r.id for r in runs]),
                                           Delivery.status == DeliveryStatus.SENDING)
                    .values(status=DeliveryStatus.UNKNOWN, error="interrupted")
                    .execution_options(synchronize_session=False))
        for run_id, post_id, b in runs:
            self._resume_run(run_id, post_id, b)

    # ------------------------------------------------------------------- runs
    @staticmethod
    def _key(post_id: int | None, run_id: int) -> int:
        # A run whose post was deleted gets its own (negative) lock key.
        return post_id if post_id is not None else -run_id

    def _resume_run(self, run_id: int, post_id: int | None, bot_id: int) -> None:
        if self.manager.get(bot_id) is None:
            return  # resume_bot() goes on with it when the bot starts
        key = self._key(post_id, run_id)
        if self.is_busy(key):
            return
        self._claim(key)
        log.info("Resuming run %s of bot %s", run_id, bot_id)
        self._spawn(self._exclusive(key, partial(self._continue_run, run_id)), name=f"resume-run-{run_id}")

    async def _continue_run(self, run_id: int) -> None:
        async with session_scope(self.sm) as s:
            run = await s.get(Run, run_id)
            if run is None or run.status != RunStatus.SENDING:
                return
            last = await s.scalar(select(func.max(Delivery.sent_at)).where(Delivery.run_id == run_id))
            bot_id = run.bot_id
            active = max(run.started_at, last) if last is not None else run.started_at
        if utcnow() - active > timedelta(minutes=self.settings.LATE_SKIP_MINUTES):
            # A long downtime: like a late slot, the rest isn't sent late.
            log.warning("Run %s was interrupted too long ago: the rest is not sent", run_id)
            await self._fail_queued(run_id, "interrupted")
            await self._finish(self.manager.get(bot_id), run_id, report=False)
            return
        await self._send_run(run_id)

    async def _create_run(self, post_id: int, chat_pks: Iterable[int], *, kind: str, source: str,
                          triggered_by: int | None) -> int | None:
        wanted = list(dict.fromkeys(int(pk) for pk in chat_pks))
        if not wanted:
            return None
        now = utcnow()
        async with session_scope(self.sm) as s:
            post = await s.get(Post, post_id)
            if post is None:
                return None
            if not self.manager.is_running(post.bot_id):
                log.info("Bot %s is not running: post %s not sent", post.bot_id, post_id)
                return None
            ws = await s.get(BotRecord, post.bot_id)
            if ws is None:
                return None
            if ws.paused:  # ⏸ Pausar todo: nothing is sent until the network is resumed
                log.info("The network of bot %s is paused: post %s not sent", post.bot_id, post_id)
                return None
            found: list[Chat] = []
            for part in chunks(wanted, 500):
                found += (await s.execute(
                    select(Chat).where(Chat.id.in_(list(part)), Chat.bot_id == post.bot_id))).scalars().all()
            chats = sorted((c for c in found if audience.is_sendable(c, now)), key=lambda c: c.id)
            if not chats:
                return None
            skips = await self._antispam(s, ws, chats, now)
            run = Run(bot_id=post.bot_id, post_id=post.id, post_name=(post.name or "")[:64], kind=kind,
                      source=(source or "")[:16], status=RunStatus.SENDING, total=len(chats),
                      triggered_by=triggered_by, started_at=now)
            s.add(run)
            await s.flush()
            s.add_all([
                Delivery(run_id=run.id, bot_id=post.bot_id, post_id=post.id, chat_pk=c.id, chat_id=c.chat_id,
                         status=DeliveryStatus.SKIPPED if c.id in skips else DeliveryStatus.QUEUED,
                         error=skips.get(c.id))
                for c in chats
            ])
            run_id = run.id
        log.info("Run %s: post %s (%s, %s) to %d chats, %d left out by the anti-spam", run_id, post_id, kind,
                 source or "-", len(chats), len(skips))
        return run_id

    async def _antispam(self, s: AsyncSession, ws: BotRecord, chats: list[Chat], now: datetime) -> dict[int, str]:
        """``{chat pk: reason}`` of the chats the bot's anti-spam leaves out: ``max_per_day`` posts today (bot
        timezone) or the last one less than ``min_gap`` minutes ago. A send of another run still queued there counts
        as a post right now."""
        if ws.max_per_day <= 0 and ws.min_gap <= 0:
            return {}
        tz = self._tz(ws)
        today = freq_svc.day_start(now.astimezone(zone(tz)).date(), tz)
        gap = timedelta(minutes=max(0, ws.min_gap))
        rows = await s.execute(
            select(Delivery.chat_pk, func.sum(case((Delivery.sent_at >= today, 1), else_=0)),
                   func.max(Delivery.sent_at))
            .where(Delivery.bot_id == ws.id, Delivery.chat_pk.is_not(None), Delivery.sent_at >= min(today, now - gap),
                   Delivery.status.in_([*DELIVERED, DeliveryStatus.UNKNOWN]))
            .group_by(Delivery.chat_pk))
        seen = {pk: (int(n or 0), last) for pk, n, last in rows}
        pending = set((await s.execute(
            select(Delivery.chat_pk).join(Run, Run.id == Delivery.run_id)
            .where(Delivery.bot_id == ws.id, Delivery.status.in_(PENDING), Run.status == RunStatus.SENDING,
                   Run.started_at >= now - timedelta(hours=1))
            .distinct())).scalars())
        out: dict[int, str] = {}
        for chat in chats:
            n, last = seen.get(chat.id, (0, None))
            if chat.id in pending:
                n, last = n + 1, now
            if ws.max_per_day > 0 and n >= ws.max_per_day:
                out[chat.id] = "max_per_day"
            elif ws.min_gap > 0 and last is not None and now - last < gap:
                out[chat.id] = "min_gap"
        return out

    async def _send_run(self, run_id: int) -> None:
        """Sends the queued deliveries of a run, then closes it (counters, report)."""
        async with session_scope(self.sm) as s:
            run = await s.get(Run, run_id)
            if run is None or run.status != RunStatus.SENDING:
                return
            post = await s.get(Post, run.post_id) if run.post_id is not None else None
            ws = await s.get(BotRecord, run.bot_id)
            queued = list((await s.execute(
                select(Delivery.id).where(Delivery.run_id == run_id, Delivery.status == DeliveryStatus.QUEUED)
                .order_by(Delivery.id))).scalars())
            no_buttons = await s.scalar(select(Delivery.id).where(
                Delivery.run_id == run_id, Delivery.error.like(NO_BUTTONS + "%")).limit(1)) is not None
            bot_id, kind = run.bot_id, run.kind
        bot = self.manager.get(bot_id)
        if bot is None:
            log.info("Bot %s is not running: run %s goes on when it starts", bot_id, run_id)
            return
        with bot_scope(bot_id):
            if post is None or ws is None:
                await self._cancel_queued(run_id)
                await self._finish(bot, run_id, cancelled=True)
                return
            job = _Job(run_id=run_id, bot=bot, bot_id=bot_id, post=post, kind=kind,
                       one_at_a_time=bool(ws.one_at_a_time), markup=content.build_markup(post.buttons),
                       no_buttons=no_buttons)
            if queued:
                try:
                    job.media = await content.media_for(bot, post, self.manager)
                except content.MediaError as exc:
                    log.warning("Run %s: the media of post %s can't be used by bot %s (%s)", run_id, post.id,
                                bot_id, exc)
                    await self._fail_queued(run_id, f"media: {exc}")
                    await self._finish(bot, run_id, media_error=str(exc))
                    return
                try:
                    await self._send_queued(job, queued)
                except _Stopped:
                    log.info("Run %s stopped after its current batch: it goes on later", run_id)
                    return
                except _Cancelled:
                    log.info("Run %s cancelled (post %s retired or deleted, or the network paused)", run_id, post.id)
                    await self._cancel_queued(run_id)
                    await self._finish(bot, run_id, cancelled=True)
                    return
            await self._finish(bot, run_id)

    async def _send_queued(self, job: _Job, ids: list[int]) -> None:
        pending = list(ids)
        while pending:
            if job.run_id in self._cancel:
                raise _Cancelled
            if self._halted(job.bot_id):
                raise _Stopped
            if await self._network_paused(job.bot_id):  # ⏸ Pausar todo stops a run in progress too
                raise _Cancelled
            # A file taken from another bot is uploaded once: one chat at a time until Telegram gives its file id.
            size = 1 if isinstance(job.media, InputFile) else BATCH_SIZE
            batch, pending = pending[:size], pending[size:]
            await self._send_batch(job, batch)

    async def _send_batch(self, job: _Job, ids: Sequence[int]) -> None:
        results: list[_Result] = []
        self._in_flight[job.bot_id] = self._in_flight.get(job.bot_id, 0) + 1
        try:
            async with session_scope(self.sm) as s:
                pks = list((await s.execute(select(Delivery.chat_pk).where(Delivery.id.in_(list(ids))))).scalars())
            async with self._chats.hold(pks):
                targets = await self._prepare(job, ids)
                if not targets:
                    return
                sem = asyncio.Semaphore(self._concurrency)
                results = list(await asyncio.gather(*(self._deliver(job, sem, tg) for tg in targets)))
                await self._store(job, results)
                if job.post.pin:
                    await self._pin(job, results)
                problems = [(r.target.chat_pk, r.problem, r.missing) for r in results if r.problem]
                problems += [(g.live.chat_pk, g.problem, g.missing) for r in results for g in r.previous if g.problem]
                await self._apply_problems(job.bot, job.bot_id, problems)
        finally:
            left = self._in_flight.get(job.bot_id, 1) - 1
            if left > 0:
                self._in_flight[job.bot_id] = left
            else:
                self._in_flight.pop(job.bot_id, None)
        if isinstance(job.media, InputFile):
            file_id = next((r.file_id for r in results if r.file_id), None)
            if file_id:
                await content.remember_media(self.sm, job.post_id, job.bot_id, file_id,
                                             source=content.media_source(job.media))
                job.media = file_id

    async def _prepare(self, job: _Job, ids: Sequence[int]) -> list[_Target]:
        """Under the locks of the chats: the deliveries still queued whose chat can still receive posts are marked
        ``sending`` (a chat that can't any more, paused or gone meanwhile, is taken out of the run), with the live
        deliveries to delete first ("one at a time" / "delete previous") and the older pinned copies to unpin."""
        now = utcnow()
        async with session_scope(self.sm) as s:
            if await s.get(Post, job.post_id) is None:
                raise _Cancelled
            rows = (await s.execute(select(Delivery).where(
                Delivery.id.in_(list(ids)), Delivery.status == DeliveryStatus.QUEUED).order_by(Delivery.id))).scalars().all()
            pks = {d.chat_pk for d in rows if d.chat_pk is not None}
            chats = {c.id: c for c in (await s.execute(select(Chat).where(Chat.id.in_(pks)))).scalars()} if pks else {}
            targets: list[_Target] = []
            dropped = 0
            for d in rows:
                chat = chats.get(d.chat_pk) if d.chat_pk is not None else None
                if chat is None or chat.bot_id != job.bot_id or not audience.is_sendable(chat, now):
                    await s.delete(d)
                    dropped += 1
                    continue
                d.status = DeliveryStatus.SENDING
                d.chat_id = chat.chat_id
                targets.append(_Target(d.id, chat.id, chat.chat_id, chat.type))
            if dropped:
                await s.execute(update(Run).where(Run.id == job.run_id).values(total=Run.total - dropped)
                                .execution_options(synchronize_session=False))
                log.info("Run %s: %d chat(s) can't receive posts any more, left out", job.run_id, dropped)
            if targets and (job.one_at_a_time or job.post.delete_previous or job.post.pin):
                by_pk = {tg.chat_pk: tg for tg in targets}
                q = select(Delivery).where(Delivery.chat_pk.in_(list(by_pk)), Delivery.status == DeliveryStatus.SENT,
                                           Delivery.message_id.is_not(None))
                if not job.one_at_a_time:
                    q = q.where(Delivery.post_id == job.post_id)
                for prev in (await s.execute(q.order_by(Delivery.id))).scalars():
                    tg = by_pk[prev.chat_pk]
                    if job.one_at_a_time or job.post.delete_previous:
                        tg.previous.append(_Live.of(prev))
                    elif prev.pinned and job.post.pin:
                        tg.unpin.append(_Live.of(prev))
        return targets

    async def _deliver(self, job: _Job, sem: asyncio.Semaphore, tg: _Target) -> _Result:
        async with sem:
            res = _Result(tg, chat_id=tg.chat_id)
            for live in tg.previous:
                res.previous.append(await self._delete_message(job.bot, live, tg.chat_type))
            chat_id = tg.chat_id
            button_error: str | None = None
            while True:
                markup = None if job.no_buttons else job.markup
                try:
                    msg = await content.deliver(job.bot, chat_id, job.post, media=job.media, reply_markup=markup)
                except TelegramMigrateToChat as exc:
                    if res.migrated:
                        res.error = short(exc)
                        return res
                    chat_id = res.chat_id = exc.migrate_to_chat_id
                    res.migrated = True
                    continue
                except TelegramAPIError as exc:
                    if is_outcome_unknown(exc):
                        # No answer: the message may be out, so it is never sent again.
                        res.status, res.error, res.sent_at = DeliveryStatus.UNKNOWN, short(exc), utcnow()
                        return res
                    if is_button_error(exc) and markup is not None:
                        job.no_buttons = True
                        button_error = short(exc)
                        log.warning("Run %s: Telegram refused a button (%s); sent without buttons", job.run_id,
                                    button_error)
                        continue
                    res.error = short(exc)
                    res.problem, res.missing = await self._diagnose(job.bot, chat_id, tg.chat_type, exc)
                    log.info("Delivery %s to %s failed: %s", tg.delivery_id, chat_id, res.error)
                    return res
                except content.MediaError as exc:
                    res.error = f"media: {exc}"
                    return res
                except Exception as exc:  # noqa: BLE001 - e.g. an answer that can't be read: it may be out
                    log.exception("Delivery %s to %s: unexpected error", tg.delivery_id, chat_id)
                    res.status, res.error, res.sent_at = DeliveryStatus.UNKNOWN, short(exc), utcnow()
                    return res
                res.status, res.message_id, res.sent_at = DeliveryStatus.SENT, msg.message_id, utcnow()
                if button_error:
                    res.error = NO_BUTTONS + button_error
                if isinstance(job.media, InputFile):
                    res.file_id = content.file_id_of(msg, job.post.kind)
                return res

    @staticmethod
    async def _diagnose(bot: Bot, chat_id: int, chat_type: str, exc: TelegramAPIError) -> tuple[str | None, list[str]]:
        """Why Telegram refused: the bot is out of the chat (GONE), lacks rights (RIGHTS, with the missing ones) or
        neither (the message or a hiccup: a temporary failure that never expels a chat). A 403 is final; any other
        refusal about the chat is confirmed by asking for the bot's membership."""
        if is_topic_error(exc):
            return RIGHTS, ["can_manage_topics"]
        rights = is_rights_error(exc)
        message = str(getattr(exc, "message", exc)).lower()
        if isinstance(exc, TelegramForbiddenError) and not (
                rights and "not a member" not in message and "kicked" not in message):
            return GONE, []  # a 403 is final (unless it only says the bot may not write there: probed below)
        if not rights and not is_chat_gone(exc):
            return None, []
        try:
            member = await bot.get_chat_member(chat_id, bot.id)
        except TelegramAPIError as probe:
            if is_chat_gone(probe):
                return GONE, []
            return (RIGHTS, ["admin"]) if rights else (None, [])
        except Exception:  # noqa: BLE001 - unknown: never expel a chat on it
            log.warning("Can't read the membership of bot %s in %s", bot.id, chat_id, exc_info=True)
            return (RIGHTS, ["admin"]) if rights else (None, [])
        if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
            return GONE, []
        missing = missing_rights(member, chat_type)
        return (RIGHTS, missing) if missing else (None, [])

    async def _store(self, job: _Job, results: Sequence[_Result]) -> None:
        now = utcnow()
        async with session_scope(self.sm) as s:
            rows = {d.id: d for d in (await s.execute(select(Delivery).where(
                Delivery.id.in_([r.target.delivery_id for r in results])))).scalars()}
            for r in results:
                await self._store_gone(s, r.previous, now)
                d = rows.get(r.target.delivery_id)
                if d is None:
                    continue
                d.status, d.error, d.message_id, d.sent_at = r.status, r.error, r.message_id, r.sent_at
                if r.chat_id is not None:
                    d.chat_id = r.chat_id
                if r.migrated and r.chat_id is not None:
                    await self._migrate(s, r.target.chat_pk, r.chat_id)
                if r.status == DeliveryStatus.SENT and r.sent_at is not None:
                    d.delete_at = delete_time(r.sent_at, job.post.delete_after)
                    await s.execute(update(Chat).where(Chat.id == r.target.chat_pk)
                                    .values(posts_total=Chat.posts_total + 1, last_post_at=r.sent_at)
                                    .execution_options(synchronize_session=False))

    async def _pin(self, job: _Job, results: Sequence[_Result]) -> None:
        """Pins the new messages silently (after they are stored: the "pinned" service message may arrive at once)
        and unpins the older copies of the post that stay in those chats."""
        sent = [r for r in results if r.status == DeliveryStatus.SENT and r.message_id]
        if not sent:
            return
        sem = asyncio.Semaphore(self._concurrency)
        unpinned: list[int] = []

        async def pin(r: _Result) -> None:
            async with sem:
                try:
                    await job.bot.pin_chat_message(r.chat_id, r.message_id, disable_notification=True)
                    r.pinned = True
                except Exception as exc:  # noqa: BLE001 - the message is out: never lose that
                    log.info("Delivery %s can't be pinned: %s", r.target.delivery_id, short(exc))
                    return
                for old in r.target.unpin:
                    if await self._unpin(job.bot, old):
                        unpinned.append(old.id)

        await asyncio.gather(*(pin(r) for r in sent))
        pinned = [r.target.delivery_id for r in sent if r.pinned]
        async with session_scope(self.sm) as s:
            if pinned:
                await s.execute(update(Delivery).where(Delivery.id.in_(pinned)).values(pinned=True)
                                .execution_options(synchronize_session=False))
            if unpinned:
                await s.execute(update(Delivery).where(Delivery.id.in_(unpinned)).values(pinned=False)
                                .execution_options(synchronize_session=False))

    async def _apply_problems(self, bot: Bot, bot_id: int, problems: Sequence[tuple[int | None, str | None,
                                                                                     list[str]]]) -> None:
        """The chats that can't receive posts: gone -> left, rights -> missing rights (events, alerts, partner DM),
        each in its own short transaction."""
        done: set[int] = set()
        for chat_pk, problem, missing in problems:
            if chat_pk is None or chat_pk in done or problem is None:
                continue
            done.add(chat_pk)
            try:
                async with session_scope(self.sm) as s:
                    chat = await s.get(Chat, chat_pk)
                    ws = await s.get(BotRecord, bot_id)
                    if chat is None or ws is None:
                        continue
                    if problem == GONE:
                        await chatstate.mark_left(bot, s, ws, chat)
                    else:
                        await chatstate.mark_rights(bot, s, ws, chat, list(missing) or ["admin"])
            except Exception:  # noqa: BLE001 - the deliveries are stored; the next refresh sees the chat again
                log.exception("Chat %s: its problem (%s) could not be stored", chat_pk, problem)

    @staticmethod
    async def _migrate(s: AsyncSession, chat_pk: int, new_chat_id: int) -> None:
        chat = await s.get(Chat, chat_pk)
        if chat is None or chat.chat_id == new_chat_id:
            return
        taken = await s.scalar(select(Chat.id).where(Chat.bot_id == chat.bot_id, Chat.chat_id == new_chat_id))
        if taken is not None:
            log.warning("Chat %s became the supergroup %s, which is already registered", chat.chat_id, new_chat_id)
            return
        log.info("Chat %s became the supergroup %s", chat.chat_id, new_chat_id)
        chat.chat_id = new_chat_id
        chat.type = ChatType.GROUP

    async def _fail_queued(self, run_id: int, error: str) -> None:
        async with session_scope(self.sm) as s:
            await s.execute(update(Delivery).where(Delivery.run_id == run_id, Delivery.status == DeliveryStatus.QUEUED)
                            .values(status=DeliveryStatus.FAILED, error=error[:256])
                            .execution_options(synchronize_session=False))

    async def _cancel_queued(self, run_id: int) -> None:
        async with session_scope(self.sm) as s:
            await s.execute(delete(Delivery).where(Delivery.run_id == run_id,
                                                   Delivery.status == DeliveryStatus.QUEUED)
                            .execution_options(synchronize_session=False))

    async def _finish(self, bot: Bot | None, run_id: int, *, media_error: str | None = None,
                      cancelled: bool = False, report: bool = True) -> None:
        """Closes a run: its counters, the post's counters (a one-time post is done) and the report."""
        self._cancel.discard(run_id)
        now = utcnow()
        async with session_scope(self.sm) as s:
            run = await s.get(Run, run_id)
            if run is None or run.status != RunStatus.SENDING:
                return
            counts = {st: int(n) for st, n in (await s.execute(
                select(Delivery.status, func.count()).where(Delivery.run_id == run_id).group_by(Delivery.status)))}
            sent = sum(counts.get(st, 0) for st in DELIVERED)
            failed = counts.get(DeliveryStatus.FAILED, 0)
            run.sent, run.failed, run.skipped = sent, failed, counts.get(DeliveryStatus.SKIPPED, 0)
            run.reach = int(await s.scalar(
                select(func.coalesce(func.sum(Chat.members), 0)).select_from(Delivery)
                .join(Chat, Chat.id == Delivery.chat_pk)
                .where(Delivery.run_id == run_id, Delivery.status.in_(DELIVERED))) or 0)
            run.finished_at = now
            if cancelled:
                run.status = RunStatus.CANCELLED
            elif media_error or (sent == 0 and failed > 0):
                run.status = RunStatus.FAILED
            else:
                run.status = RunStatus.DONE
            post = await s.get(Post, run.post_id) if run.post_id is not None else None
            if post is not None:
                values: dict[str, Any] = {"runs_count": Post.runs_count + 1, "sent_count": Post.sent_count + sent}
                if sent:
                    values["last_sent_at"] = run.started_at
                if run.kind == RunKind.ONCE and post.status == PostStatus.ACTIVE:
                    values.update(status=PostStatus.DONE, next_send_at=None)
                await s.execute(update(Post).where(Post.id == post.id).values(**values)
                                .execution_options(synchronize_session=False))
            note = await s.scalar(select(Delivery.error).where(
                Delivery.run_id == run_id, Delivery.error.like(NO_BUTTONS + "%")).limit(1))
            outcome = _Outcome(bot_id=run.bot_id, post_id=run.post_id, name=run.post_name, total=run.total,
                               sent=sent, failed=failed, skipped=run.skipped,
                               unknown=counts.get(DeliveryStatus.UNKNOWN, 0), cancelled=cancelled,
                               media_error=media_error, no_buttons=note)
            status = run.status
        log.info("Run %s %s: %d/%d sent, %d failed, %d skipped, %d unknown", run_id, status, outcome.sent,
                 outcome.total, outcome.failed, outcome.skipped, outcome.unknown)
        if report and bot is not None:
            await self._report(bot, outcome)

    async def _report(self, bot: Bot, o: _Outcome) -> None:
        """«📤 Promo Cine enviado a 23/25 chats…» to the admins with run reports on. A media that can't be used is
        also told to every admin with alerts on (once a day per post)."""
        alert_all = False
        if o.media_error:
            key = (o.post_id or 0, o.media_error)
            last = self._media_alerts.get(key)
            if last is None or time.monotonic() - last >= MEDIA_ALERT_EVERY:
                self._media_alerts[key] = time.monotonic()
                alert_all = True
        async with session_scope(self.sm) as s:
            ws = await s.get(BotRecord, o.bot_id)
            if ws is None:
                return
            for uid in await admin_ids(s, ws):
                bu = await s.get(BotUser, (ws.id, uid))
                if bu is None or bu.is_blocked or not (bu.run_reports or (alert_all and bu.notify)):
                    continue
                markup = kb([btn(t("eng.btn.post", bu.lang), MenuCB(screen="post", arg=o.post_id))]) \
                    if o.post_id else None
                await send_dm(bot, s, uid, _report_text(o, bu.lang), markup)

    # -------------------------------------------------------------- deletions
    async def _retire(self, post_id: int) -> int:
        async with session_scope(self.sm) as s:
            bots = list((await s.execute(select(Delivery.bot_id).where(
                Delivery.post_id == post_id, Delivery.status == DeliveryStatus.SENT).distinct())).scalars())
        deleted = 0
        for bot_id in bots:
            with bot_scope(bot_id):
                deleted += await self._delete_live(bot_id, Delivery.post_id == post_id)
        log.info("Post %s retired: %d deliveries deleted", post_id, deleted)
        return deleted

    async def _delete_live(self, bot_id: int, *conds: Any, counter: list[int] | None = None) -> int:
        """Deletes the live deliveries of a bot that match ``conds``, in batches under the locks of their chats.
        Returns how many were deleted (``counter[0]`` follows it while it runs)."""
        bot = self.manager.get(bot_id)
        if bot is None:
            return 0
        async with session_scope(self.sm) as s:
            rows = (await s.execute(
                select(Delivery.id, Delivery.chat_pk)
                .where(Delivery.bot_id == bot_id, Delivery.status == DeliveryStatus.SENT, *conds)
                .order_by(Delivery.chat_pk, Delivery.id))).all()
        deleted = 0
        sem = asyncio.Semaphore(self._concurrency)

        async def one(live: _Live, chat_type: str) -> _Gone:
            async with sem:
                return await self._delete_message(bot, live, chat_type)

        for batch in chunks(rows, BATCH_SIZE):
            if self._stopping:
                break  # shutdown: the rest is done after the restart (stored batches never leave a gap)
            async with self._chats.hold(pk for _, pk in batch):
                async with session_scope(self.sm) as s:
                    lives = [(_Live.of(d), chat_type or ChatType.CHANNEL) for d, chat_type in (await s.execute(
                        select(Delivery, Chat.type).outerjoin(Chat, Chat.id == Delivery.chat_pk)
                        .where(Delivery.id.in_([i for i, _ in batch]), Delivery.status == DeliveryStatus.SENT, *conds)
                    )).all()]
                if not lives:
                    continue
                outcomes = await asyncio.gather(*(one(live, chat_type) for live, chat_type in lives))
                async with session_scope(self.sm) as s:
                    n = await self._store_gone(s, outcomes, utcnow())
                deleted += n
                if counter is not None:
                    counter[0] += n
                await self._apply_problems(bot, bot_id, [(o.live.chat_pk, o.problem, o.missing)
                                                         for o in outcomes if o.problem])
        return deleted

    async def _delete_message(self, bot: Bot, live: _Live, chat_type: str = ChatType.CHANNEL) -> _Gone:
        if live.message_id is None:
            return _Gone(live, DeliveryStatus.MISSING, "no message id")
        # Telegram's limit is 48 h (auto deletes are scheduled a little before it, at MAX_DELETE_AGE, and run a few
        # seconds after that): only past the real limit is it too late to try.
        if live.sent_at is not None and utcnow() - live.sent_at >= LIVE_AGE:
            return _Gone(live, DeliveryStatus.EXPIRED, unpinned=await self._unpin(bot, live))
        try:
            await bot.delete_message(live.chat_id, live.message_id)
        except TelegramAPIError as exc:
            if is_message_gone(exc):
                return _Gone(live, DeliveryStatus.MISSING)
            if is_cant_delete(exc):
                return _Gone(live, DeliveryStatus.EXPIRED, short(exc), unpinned=await self._unpin(bot, live))
            if is_outcome_unknown(exc) or isinstance(exc, TelegramRetryAfter) or is_unauthorized(exc):
                return _Gone(live, RETRY, short(exc))
            problem, missing = await self._diagnose(bot, live.chat_id, chat_type, exc)
            if problem == GONE:
                return _Gone(live, DeliveryStatus.MISSING, short(exc), problem=GONE)
            if problem is None and is_chat_gone(exc):
                return _Gone(live, RETRY, short(exc))  # "chat not found" not confirmed: try again later
            # It can't be deleted (e.g. the bot lost its rights): it stays in the chat, at least not pinned.
            log.info("Delivery %s in %s can't be deleted: %s", live.id, live.chat_id, short(exc))
            return _Gone(live, DeliveryStatus.EXPIRED, short(exc), problem=problem, missing=missing,
                         unpinned=await self._unpin(bot, live))
        except Exception as exc:  # noqa: BLE001 - e.g. an answer that can't be read: try again later
            log.warning("Delivery %s in %s: unexpected error while deleting it", live.id, live.chat_id, exc_info=True)
            return _Gone(live, RETRY, short(exc))
        return _Gone(live, DeliveryStatus.DELETED)

    @staticmethod
    async def _unpin(bot: Bot, live: _Live) -> bool:
        if not (live.pinned and live.message_id):
            return False
        try:
            await bot.unpin_chat_message(live.chat_id, message_id=live.message_id)
        except Exception as exc:  # noqa: BLE001 - best effort
            log.info("Delivery %s in %s can't be unpinned: %s", live.id, live.chat_id, short(exc))
            return False
        return True

    @staticmethod
    async def _store_gone(s: AsyncSession, outcomes: Sequence[_Gone], now: datetime) -> int:
        """Stores deletion outcomes (only on deliveries still live). Returns how many were deleted."""
        deleted = 0
        for o in outcomes:
            q = update(Delivery).where(Delivery.id == o.live.id, Delivery.status == DeliveryStatus.SENT)
            if o.status == RETRY:
                values: dict[str, Any] = {"delete_at": now + DELETE_RETRY, "error": o.error}
            else:
                values = {"status": o.status, "deleted_at": now, "error": o.error}
                if o.status != DeliveryStatus.EXPIRED or o.unpinned:
                    values["pinned"] = False
            res = await s.execute(q.values(**values).execution_options(synchronize_session=False))
            if o.status == DeliveryStatus.DELETED and res.rowcount:
                deleted += 1
        return deleted

    # ---------------------------------------------------------------- editing
    async def _update_live(self, post_id: int) -> tuple[int, int]:
        async with session_scope(self.sm) as s:
            post = await s.get(Post, post_id)
            if post is None:
                return 0, 0
            rows = (await s.execute(
                select(Delivery.id, Delivery.chat_pk)
                .where(Delivery.post_id == post_id, Delivery.status == DeliveryStatus.SENT,
                       Delivery.message_id.is_not(None), Delivery.sent_at > utcnow() - LIVE_AGE)
                .order_by(Delivery.chat_pk, Delivery.id))).all()
        bot = self.manager.get(post.bot_id)
        if bot is None or not rows:
            return 0, 0
        sem = asyncio.Semaphore(self._concurrency)
        edited = failed = 0

        async def edit(live: _Live) -> str:
            """``ok``, ``gone`` (the message isn't there any more) or ``failed``."""
            async with sem:
                try:
                    await content.edit_delivery(bot, live.chat_id, live.message_id, post)  # type: ignore[arg-type]
                except TelegramAPIError as exc:
                    if is_not_modified(exc):
                        return "ok"
                    log.info("Delivery %s in %s not updated: %s", live.id, live.chat_id, short(exc))
                    return "gone" if is_message_gone(exc) else "failed"
                except Exception:  # noqa: BLE001
                    log.warning("Delivery %s in %s: unexpected error while updating it", live.id, live.chat_id,
                                exc_info=True)
                    return "failed"
                return "ok"

        with bot_scope(post.bot_id):
            for batch in chunks(rows, BATCH_SIZE):
                async with self._chats.hold(pk for _, pk in batch):
                    async with session_scope(self.sm) as s:
                        lives = [_Live.of(d) for d in (await s.execute(select(Delivery).where(
                            Delivery.id.in_([i for i, _ in batch]), Delivery.status == DeliveryStatus.SENT))).scalars()]
                    results = await asyncio.gather(*(edit(live) for live in lives))
                    gone = [live.id for live, res in zip(lives, results) if res == "gone"]
                    if gone:
                        async with session_scope(self.sm) as s:
                            await s.execute(update(Delivery).where(Delivery.id.in_(gone),
                                                                   Delivery.status == DeliveryStatus.SENT)
                                            .values(status=DeliveryStatus.MISSING, deleted_at=utcnow(), pinned=False)
                                            .execution_options(synchronize_session=False))
                    edited += sum(1 for res in results if res == "ok")
                    failed += sum(1 for res in results if res != "ok")
        log.info("Post %s: %d live deliveries updated, %d failed", post_id, edited, failed)
        return edited, failed
