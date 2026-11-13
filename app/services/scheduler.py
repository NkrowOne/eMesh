"""⏰ The scheduler: every ``SCHEDULER_TICK_SECONDS`` (or right after :meth:`Scheduler.wake`) it starts the due work of
every running bot as background jobs, each bot in its own tasks so a slow or flooded bot never delays the others:

* ``send`` (not while the network is paused, not for a hub main bot): the due own-schedule and one-time posts, each
  to its whole audience; every few minutes, the runs left half-done by a task that died go on (or are closed when
  too old).
* ``delete``: the auto deletions that are due (also while paused: announced deletions always happen).
* ``maint``: owner pauses that ended (also while paused), the daily summary and, every
  ``MAINTENANCE_INTERVAL_HOURS``, the refresh of every chat (title, members, rights).

Plus, once a day, the cleanup of old runs and activity. Everything is in the database, so after a restart the ticks
simply pick up what is due; a post found more than ``LATE_SKIP_MINUTES`` late is skipped, not sent late. A post is
claimed (its next time stored) right before it is sent, so a crash never sends it twice and the due posts still
waiting for their turn go out after the restart. A scheduled send that doesn't go out (found too late, or no chat can
receive it) is stored in the activity and told to the admins.

Bookkeeping in the KV table: ``maint:<bot id>`` / ``maint:cleanup`` (last run, ISO time),
``summary:<bot id>:<local date>`` (sent once) and ``missed:<post id>:<reason>`` (last alert of a missed send).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, exists, func, select, update

from app.db.base import utcnow
from app.db.models import KV, BotStatus, BotUser, Chat, ChatStatus, Delivery, DeliveryStatus, Event, EventKind, Post, \
    PostStatus, Run, RunKind, SchedMode
from app.db.models import Bot as BotRecord
from app.db.session import session_scope
from app.i18n import t
from app.services import audience, chatstate, events, freq, stats
from app.services.notify import send_dm
from app.services.publisher import LIVE_AGE, chunks
from app.services.users import admin_ids
from app.telegram.context import bot_scope, set_low_priority
from app.ui.callbacks import MenuCB
from app.ui.common import btn, kb
from app.ui.fmt import esc, num, zone

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.config import Settings
    from app.db.session import SessionMaker
    from app.services.publisher import Publisher
    from app.telegram.manager import BotManager

log = logging.getLogger(__name__)

STOP_TIMEOUT = 30.0
DELETE_CHUNK = 500
CLEANUP_EVERY = timedelta(days=1)
ORPHANS_EVERY = 300.0  # seconds between two looks for runs whose task died
MISSED_EVERY = timedelta(hours=12)  # a post missed again for the same reason isn't told more often than this

JobKey = tuple[str, int]


def _as_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _summary_text(rec: BotRecord, day_label: str, runs: int, sent: int, failed: int, skipped: int, reach: int,
                  sm: stats.Summary, lang: str) -> str:
    lines = [
        t("eng.summary.title", lang, bot=esc(rec.username or rec.name)),
        t("eng.summary.date", lang, date=day_label),
        "",
        t("eng.summary.runs", lang, n=num(runs)),
        t("eng.summary.sent", lang, n=num(sent)),
        t("eng.summary.failed", lang, n=num(failed)),
        t("eng.summary.skipped", lang, n=num(skipped)),
        t("eng.summary.reach", lang, n=num(reach)),
        "",
        t("eng.summary.chats", lang, n=num(sm.chats), members=num(sm.members)),
    ]
    for key, n in (("eng.summary.owner_paused", sm.owner_paused), ("eng.summary.admin_paused", sm.admin_paused),
                   ("eng.summary.pending", sm.pending), ("eng.summary.no_rights", sm.no_rights)):
        if n:
            lines.append(t(key, lang, n=num(n)))
    return "\n".join(lines)


class Scheduler:
    def __init__(self, manager: BotManager, sm: SessionMaker, settings: Settings, publisher: Publisher) -> None:
        self.manager = manager
        self.sm = sm
        self.settings = settings
        self.publisher = publisher
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopping = False
        self._jobs: dict[JobKey, asyncio.Task[None]] = {}
        self._swept: dict[int, float] = {}  # bot id -> when its half-done runs were last looked for

    # ------------------------------------------------------------------ loop
    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self.publisher.allow_sending()
        self._task = asyncio.create_task(self._loop(), name="scheduler")
        log.info("Scheduler started (tick %ss)", self.settings.SCHEDULER_TICK_SECONDS)

    async def stop(self) -> None:
        """Stops the loop; running runs end with the batch in flight (resumed at the next start)."""
        self._stopping = True
        self.publisher.stop_sending()
        self._wake.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        jobs = [job for job in self._jobs.values() if not job.done()]
        if jobs:
            _, pending = await asyncio.wait(jobs, timeout=STOP_TIMEOUT)
            for job in pending:
                job.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        await self.publisher.wait_idle(timeout=STOP_TIMEOUT)

    def wake(self) -> None:
        """Runs a tick as soon as possible (after a schedule changed)."""
        self._wake.set()

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.tick(wait=False)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Scheduler tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(),
                                       timeout=max(0.1, float(self.settings.SCHEDULER_TICK_SECONDS)))
            self._wake.clear()

    async def tick(self, *, wait: bool = True) -> None:
        """Starts the due work of every running bot (a bot whose job of the same kind is still running is left for a
        later tick). ``wait``: return when those jobs are done (the loop doesn't wait)."""
        running = [bot_id for bot_id in list(self.manager.bots) if self.manager.is_running(bot_id)]
        rows: list[Any] = []
        if running:
            async with session_scope(self.sm) as s:
                rows = list((await s.execute(
                    select(BotRecord.id, BotRecord.is_main, BotRecord.paused)
                    .where(BotRecord.id.in_(running), BotRecord.status == BotStatus.ACTIVE)
                    .order_by(BotRecord.id))).all())
        started: list[asyncio.Task[None] | None] = []
        for bot_id, is_main, paused in rows:
            started.append(self._start(("delete", bot_id), partial(self.publisher.delete_due, bot_id)))
            if self._hub(is_main):
                continue  # a hub main bot runs no network
            started.append(self._start(("maint", bot_id), partial(self._maintenance, bot_id)))
            if not paused:
                started.append(self._start(("send", bot_id), partial(self._sends, bot_id)))
        started.append(self._start(("cleanup", 0), self._cleanup))
        tasks = [task for task in started if task is not None]
        if wait and tasks:
            await asyncio.wait(tasks)

    def _hub(self, is_main: bool) -> bool:
        return bool(is_main) and self.settings.MAIN_BOT_MODE == "hub"

    def _start(self, key: JobKey, fn: Callable[[], Awaitable[Any]]) -> asyncio.Task[None] | None:
        job = self._jobs.get(key)
        if job is not None and not job.done():
            return job
        if self._stopping:
            return None
        job = asyncio.create_task(self._run_job(key, fn), name=f"scheduler-{key[0]}-{key[1]}")
        self._jobs[key] = job
        job.add_done_callback(lambda done, k=key: self._jobs.pop(k, None) if self._jobs.get(k) is done else None)
        return job

    @staticmethod
    async def _run_job(key: JobKey, fn: Callable[[], Awaitable[Any]]) -> None:
        set_low_priority()
        try:
            with bot_scope(key[1]) if key[1] else contextlib.nullcontext():
                await fn()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Scheduler job %s failed", key)

    @staticmethod
    async def _guard(job: Awaitable[Any], what: str) -> None:
        """One step of a job: its failure is logged and the next steps still run."""
        try:
            await job
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Scheduler step failed: %s", what)

    @property
    def _late(self) -> timedelta:
        return timedelta(minutes=max(0, self.settings.LATE_SKIP_MINUTES))

    def _tz(self, rec: BotRecord) -> str:
        return rec.timezone or self.settings.DEFAULT_TIMEZONE

    # ----------------------------------------------------------------- sends
    async def _sends(self, bot_id: int) -> None:
        last = self._swept.get(bot_id)
        if last is None or time.monotonic() - last >= ORPHANS_EVERY:
            # Runs left "sending" with no task behind them (it died): they go on, or are closed when too old.
            self._swept[bot_id] = time.monotonic()
            await self._guard(self.publisher.resume_bot(bot_id), f"half-done runs of bot {bot_id}")
        # The half-done runs may take minutes: the clock is read again (a stale "now" would compute next times already
        # past and send the same post twice).
        await self._guard(self._posts(bot_id, utcnow()), f"scheduled posts of bot {bot_id}")

    async def _posts(self, bot_id: int, now: datetime) -> None:
        """Campaigns that are over become done; due own-frequency and one-time posts go to their whole audience, one
        after another. A post found too late is skipped (and told to the admins)."""
        todo: list[int] = []
        missed: list[tuple[int, str, datetime]] = []
        async with session_scope(self.sm) as s:
            ws = await s.get(BotRecord, bot_id)
            if ws is None or ws.paused or not self.manager.is_running(bot_id):
                return
            tz = self._tz(ws)
            for post in (await s.execute(select(Post).where(
                    Post.bot_id == bot_id, Post.status == PostStatus.ACTIVE, Post.ends_on.is_not(None)))).scalars():
                if freq.ended(post, tz, now):
                    post.status = PostStatus.DONE
                    post.next_send_at = None
            scheduled = (Post.bot_id == bot_id, Post.status == PostStatus.ACTIVE,
                         Post.mode.in_([SchedMode.OWN, SchedMode.ONCE]))
            for post in (await s.execute(select(Post).where(*scheduled, Post.next_send_at.is_(None)))).scalars():
                freq.refresh_post(post, tz, now)
            due = (await s.execute(select(Post).where(*scheduled, Post.next_send_at.is_not(None),
                                                      Post.next_send_at <= now)
                                   .order_by(Post.next_send_at, Post.id))).scalars().all()
            for post in due:
                assert post.next_send_at is not None
                if now - post.next_send_at > self._late:
                    log.warning("Post %s was due at %s (%s late, downtime?): skipped", post.id,
                                post.next_send_at.isoformat(), now - post.next_send_at)
                    missed.append((post.id, post.name, post.next_send_at))
                    if post.mode == SchedMode.ONCE:
                        post.status = PostStatus.DONE
                    freq.refresh_post(post, tz, now)
                elif not self.publisher.is_busy(post.id):  # (being sent right now: next tick)
                    todo.append(post.id)
        for post_id, name, due_at in missed:
            await self._guard(self._missed(bot_id, post_id, name, "late", due_at), f"missed post {post_id}")
        for post_id in todo:
            if self._stopping or not self.manager.is_running(bot_id):
                return  # the ones left are still due: they go out at the next start
            # One after another: their audiences overlap, and the anti-spam sees each run before the next.
            await self._guard(self._send_due(bot_id, post_id), f"run of post {post_id}")

    async def _send_due(self, bot_id: int, post_id: int) -> None:
        """Claims a due post (its next time is stored, a one-time post is done) and sends it to its audience."""
        now = utcnow()
        async with session_scope(self.sm) as s:
            post = await s.get(Post, post_id)
            ws = await s.get(BotRecord, bot_id)
            if (post is None or ws is None or ws.paused or post.status != PostStatus.ACTIVE
                    or post.mode not in (SchedMode.OWN, SchedMode.ONCE) or post.next_send_at is None
                    or post.next_send_at > now or self.publisher.is_busy(post_id)):
                return  # changed, paused or sent by hand while the posts before it went out
            due_at, once, name = post.next_send_at, post.mode == SchedMode.ONCE, post.name
            chats = [c.id for c in await audience.audience(s, post, now=now)]
            if once:
                post.status = PostStatus.DONE
            freq.refresh_post(post, self._tz(ws), now)
        if not chats:
            log.info("Post %s is due but no chat can receive it now", post_id)
            await self._missed(bot_id, post_id, name, "no_chats", due_at)
            return
        run_id = await self.publisher.run(post_id, chats, kind=RunKind.ONCE if once else RunKind.SCHEDULE, wait=True)
        if run_id is None and self._stopping:
            # Stopped between the claim and the run: the post is due again, for the next start.
            async with session_scope(self.sm) as s:
                post = await s.get(Post, post_id)
                if post is not None and post.status == (PostStatus.DONE if once else PostStatus.ACTIVE):
                    post.status = PostStatus.ACTIVE
                    post.next_send_at = due_at

    async def _missed(self, bot_id: int, post_id: int, name: str, reason: str, due_at: datetime) -> None:
        """A scheduled send that didn't go out: stored in the activity and told to the admins. Once per post and
        reason every ``MISSED_EVERY`` (an hourly post whose chats are all paused doesn't alert every hour)."""
        if not await self._claim_interval(f"missed:{post_id}:{reason}", utcnow(), MISSED_EVERY):
            return
        async with session_scope(self.sm) as s:
            ws = await s.get(BotRecord, bot_id)
            if ws is None:
                return
            await events.emit(self.manager.get(bot_id), s, ws, EventKind.POST_MISSED, notify=True,
                              data={"reason": reason, "post": name, "post_id": post_id, "due": due_at.isoformat()})

    # ----------------------------------------------------------- maintenance
    async def _maintenance(self, bot_id: int) -> None:
        now = utcnow()
        await self._guard(self._pauses_over(bot_id, now), f"owner pauses of bot {bot_id}")
        async with session_scope(self.sm) as s:
            rec = await s.get(BotRecord, bot_id)
            paused = rec is None or rec.paused
        if paused:
            return
        await self._guard(self._summary(bot_id, now), f"daily summary of bot {bot_id}")
        await self._guard(self._refresh_chats(bot_id, now), f"chat refresh of bot {bot_id}")

    async def _pauses_over(self, bot_id: int, now: datetime) -> None:
        """Owner pauses whose end passed: cleared, logged (the admins are alerted) and the partner is told."""
        expired = (Chat.bot_id == bot_id, Chat.owner_paused.is_(True), Chat.owner_paused_until.is_not(None),
                   Chat.owner_paused_until <= now)
        async with session_scope(self.sm) as s:
            ids = list((await s.execute(select(Chat.id).where(*expired).order_by(Chat.id))).scalars())
        bot = self.manager.get(bot_id)
        for chat_pk in ids:
            async with session_scope(self.sm) as s:
                res = await s.execute(update(Chat).where(Chat.id == chat_pk, *expired)
                                      .values(owner_paused=False, owner_paused_until=None)
                                      .execution_options(synchronize_session=False))
                if not res.rowcount:
                    continue  # resumed by its owner meanwhile
                chat = await s.get(Chat, chat_pk)
                ws = await s.get(BotRecord, bot_id)
                if chat is None or ws is None:
                    continue
                if not chat.admin_paused:
                    chat.paused_at = None
                log.info("Chat %s: the pause of its owner is over", chat.chat_id)
                if chat.status != ChatStatus.APPROVED:
                    continue
                await events.emit(bot, s, ws, EventKind.CHAT_RESUMED, chat=chat, data={"by": "auto"})
                await self._tell_pause_over(bot, s, ws, chat)

    @staticmethod
    async def _tell_pause_over(bot: Bot | None, s: AsyncSession, ws: BotRecord, chat: Chat) -> None:
        uid = chat.owner_user_id
        if bot is None or not uid or uid in await admin_ids(s, ws):
            return  # the admins get the event alert instead
        bu = await s.get(BotUser, (ws.id, uid))
        if bu is None or bu.is_blocked:
            return
        text = t("eng.pause_over", bu.lang, kind=chatstate.kind_word(chat, bu.lang), chat=esc(chat.display_title))
        await send_dm(bot, s, uid, text, kb([btn(t("eng.btn.my_chats", bu.lang), MenuCB(screen="my_chats"))]))

    async def _summary(self, bot_id: int, now: datetime) -> None:
        """Once a day after SUMMARY_HOUR (bot timezone): yesterday's numbers to the admins with the summary on."""
        async with session_scope(self.sm) as s:
            rec = await s.get(BotRecord, bot_id)
        bot = self.manager.get(bot_id)
        if rec is None or bot is None:
            return
        tz = self._tz(rec)
        local = now.astimezone(zone(tz))
        if local.hour < self.settings.SUMMARY_HOUR:
            return
        if not await self._claim_once(f"summary:{bot_id}:{local.date().isoformat()}", now):
            return
        day = local.date() - timedelta(days=1)
        start, end = freq.day_start(day, tz), freq.day_start(local.date(), tz)
        async with session_scope(self.sm) as s:
            runs, sent, failed, skipped, reach = (int(x or 0) for x in (await s.execute(
                select(func.count(Run.id), func.coalesce(func.sum(Run.sent), 0), func.coalesce(func.sum(Run.failed), 0),
                       func.coalesce(func.sum(Run.skipped), 0), func.coalesce(func.sum(Run.reach), 0))
                .where(Run.bot_id == bot_id, Run.started_at >= start, Run.started_at < end))).one())
            numbers = await stats.summary(s, bot_id, now=now)
        if not runs and not numbers.chats and not numbers.pending:
            return  # an empty network: nothing to tell
        async with session_scope(self.sm) as s:
            rec = await s.get(BotRecord, bot_id)
            if rec is None:
                return
            for uid in await admin_ids(s, rec):
                bu = await s.get(BotUser, (bot_id, uid))
                if bu is None or not bu.summary or bu.is_blocked:
                    continue
                text = _summary_text(rec, day.strftime("%d/%m/%Y"), runs, sent, failed, skipped, reach, numbers,
                                     bu.lang)
                await send_dm(bot, s, uid, text, kb([btn(t("eng.btn.stats", bu.lang), MenuCB(screen="stats"))]))
        log.info("Bot %s: daily summary of %s sent", bot_id, day.isoformat())

    async def _refresh_chats(self, bot_id: int, now: datetime) -> None:
        """Every MAINTENANCE_INTERVAL_HOURS: title, members and rights of every approved and pending chat (a pending
        chat that got its rights is approved by the chats module, not here)."""
        every = timedelta(hours=max(1, self.settings.MAINTENANCE_INTERVAL_HOURS))
        if not await self._claim_interval(f"maint:{bot_id}", now, every):
            return
        bot = self.manager.get(bot_id)
        if bot is None:
            return
        async with session_scope(self.sm) as s:
            ids = list((await s.execute(
                select(Chat.id).where(Chat.bot_id == bot_id,
                                      Chat.status.in_([ChatStatus.APPROVED, ChatStatus.PENDING]))
                .order_by(Chat.id))).scalars())
        log.info("Bot %s: refreshing %d chats", bot_id, len(ids))
        for chat_pk in ids:
            if self._stopping or self.manager.get(bot_id) is not bot:
                log.info("Bot %s stopped: chat refresh interrupted", bot_id)
                return
            try:
                async with session_scope(self.sm) as s:
                    chat = await s.get(Chat, chat_pk)
                    ws = await s.get(BotRecord, bot_id)
                    if chat is None or ws is None or chat.status not in (ChatStatus.APPROVED, ChatStatus.PENDING):
                        continue
                    await chatstate.refresh(bot, s, ws, chat)
            except Exception:  # noqa: BLE001 - one chat never stops the others
                log.exception("Refreshing chat %s failed", chat_pk)

    # --------------------------------------------------------------- cleanup
    async def _cleanup(self) -> None:
        """Once a day: runs (with their deliveries) and activity older than RETENTION_DAYS. A run with deliveries
        still waiting for their auto delete is kept."""
        now = utcnow()
        if not await self._claim_interval("maint:cleanup", now, CLEANUP_EVERY):
            return
        cutoff = now - timedelta(days=max(1, self.settings.RETENTION_DAYS))
        waiting = exists().where(Delivery.run_id == Run.id, Delivery.status == DeliveryStatus.SENT,
                                 Delivery.delete_at.is_not(None), Delivery.sent_at > now - LIVE_AGE)
        async with session_scope(self.sm) as s:
            ids = list((await s.execute(select(Run.id).where(Run.started_at < cutoff, ~waiting))).scalars())
        for batch in chunks(ids, DELETE_CHUNK):
            async with session_scope(self.sm) as s:
                await s.execute(delete(Delivery).where(Delivery.run_id.in_(list(batch)))
                                .execution_options(synchronize_session=False))
                await s.execute(delete(Run).where(Run.id.in_(list(batch)))
                                .execution_options(synchronize_session=False))
        async with session_scope(self.sm) as s:
            gone = await s.execute(delete(Event).where(Event.created_at < cutoff)
                                   .execution_options(synchronize_session=False))
            await s.execute(delete(KV).where(KV.key.like("summary:%") | KV.key.like("missed:%"), KV.updated_at < cutoff)
                            .execution_options(synchronize_session=False))
        log.info("Cleanup: %d old runs and %d old events deleted", len(ids), gone.rowcount or 0)

    # ----------------------------------------------------------- bookkeeping
    async def _claim_interval(self, key: str, now: datetime, every: timedelta) -> bool:
        """True (and ``now`` is stored) when the job ``key`` didn't run in the last ``every``."""
        async with session_scope(self.sm) as s:
            rec = await s.get(KV, key)
            last = _as_datetime(rec.value) if rec is not None else None
            if last is not None and now - last < every:
                return False
            if rec is None:
                s.add(KV(key=key, value=now.isoformat(), updated_at=now))
            else:
                rec.value = now.isoformat()
                rec.updated_at = now
        return True

    async def _claim_once(self, key: str, now: datetime) -> bool:
        """True the first time ``key`` is claimed."""
        async with session_scope(self.sm) as s:
            if await s.get(KV, key) is not None:
                return False
            s.add(KV(key=key, value=now.isoformat(), updated_at=now))
        return True
