"""Database models. All tables are prefixed with ``em_`` so they never collide with other schemas.

Vocabulary (code -> UI):
* ``Bot``        the main bot or a clone ("bot").
* ``Chat``       a channel or group of a bot ("📣 Canal" / "👥 Grupo"); own or external (a partner's).
* ``ChatGroup``  a custom set of chats with an optional own frequency ("🗂 Grupo de canales").
* ``Post``       content the network distributes, with its buttons, targets and schedule ("📝 Mensaje").
* ``Run``        one distribution of a post to a set of chats ("envío").
* ``Delivery``   the post inside one chat (the Telegram message there).
* ``Event``      activity log line ("📜 Actividad"): joins, pauses, removals...
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import false as sa_false
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow


# ---------------------------------------------------------------------------
# Enumerations (stored as plain strings)
# ---------------------------------------------------------------------------
class BotStatus:
    ACTIVE = "active"
    DISABLED = "disabled"  # stopped by its owner or a super admin (status_reason says who)
    INVALID = "invalid"  # token revoked / unauthorized
    PENDING = "pending"  # a clone waiting for a super admin's approval (clone policy "approval")


class Role:
    SUPER = "superadmin"  # platform owner (SUPER_ADMIN_IDS)
    OWNER = "owner"  # owner of a bot (bots.owner_id)
    ADMIN = "admin"  # promoted with /admin
    USER = "user"  # everyone else (e.g. partners: owners of external chats)


class ChatType:
    CHANNEL = "channel"
    GROUP = "group"


class ChatOrigin:
    OWN = "own"  # added by the bot's owner or one of its admins
    EXTERNAL = "ext"  # added by someone else while the bot accepts external chats (a "partner")


class ChatStatus:
    PENDING = "pending"  # external chat waiting for approval, or any chat without the required rights yet
    APPROVED = "approved"
    REJECTED = "rejected"  # the bot left; it can be added again
    BANNED = "banned"  # never accepted again (the bot leaves when re-added)
    LEFT = "left"  # the bot is not in the chat any more (removed, chat deleted)


class PostStatus:
    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"  # a one-time post already sent, or a campaign past its end date


class SchedMode:
    """When a post is sent."""

    ROTATION = "rotation"  # 🔁 takes turns with the other rotation posts of each chat, at the chat's frequency
    OWN = "own"  # ⏰ its own frequency (Post.freq), to its whole audience
    ONCE = "once"  # 📆 one date and time (Post.send_at)
    MANUAL = "manual"  # ✋ only with "🚀 Enviar ahora"


class RotationOrder:
    """``Bot.rotation``: how the 🔁 rotation posts take turns, or no rotation at all."""

    SEQUENTIAL = "seq"  # each chat gets the posts in order (oldest first), then starts again
    RANDOM = "random"  # a random post each time (never the same twice in a row when there are more)
    # No rotation: the global and groups' frequencies send nothing; each post goes out on its own schedule (⏰ own,
    # 📢 once, ✋ manual). Rotation posts stay as they are, unsent, until it is on again or their mode changes.
    OFF = "off"


def rotation_on(order: str | None) -> bool:
    """``Bot.rotation`` turns the rotation on (in order or at random)."""
    return order != RotationOrder.OFF


class RunKind:
    ROTATION = "rotation"
    SCHEDULE = "schedule"  # a post with its own frequency
    ONCE = "once"
    MANUAL = "manual"  # 🚀 Enviar ahora


class RunStatus:
    SENDING = "sending"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


class DeliveryStatus:
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"  # left out by the anti-spam limits of the bot
    DELETED = "deleted"  # deleted by the bot (auto delete, "delete previous", withdraw)
    MISSING = "missing"  # already gone when the bot tried to delete it
    UNKNOWN = "unknown"  # maybe sent: no answer from Telegram, or the process stopped while sending
    EXPIRED = "expired"  # older than 48 h: Telegram doesn't let bots delete it any more


class EventKind:
    CHAT_ADDED = "chat_added"  # own chat added by an admin
    CHAT_REQUEST = "chat_request"  # external chat waiting for approval
    CHAT_JOINED = "chat_joined"  # external chat accepted (automatically or by an admin)
    CHAT_REJECTED = "chat_rejected"
    CHAT_BANNED = "chat_banned"
    CHAT_PAUSED = "chat_paused"  # data: {"by": "owner"|"admin", "until": iso|None}
    CHAT_RESUMED = "chat_resumed"  # data: {"by": "owner"|"admin"|"auto"}
    CHAT_LEFT = "chat_left"  # the bot was removed from the chat or the chat is gone
    CHAT_REMOVED = "chat_removed"  # taken out of the network (data: {"by": "owner"|"admin"})
    CHAT_RIGHTS = "chat_rights"  # the bot lost required rights (data: {"missing": "a,b"})
    CHAT_RIGHTS_OK = "chat_rights_ok"  # the rights are back
    BOT_PAUSED = "bot_paused"  # ⏸ the whole distribution
    BOT_RESUMED = "bot_resumed"


# A new post stays in the chats until it is deleted (the wizard asks how long; 0 = never deleted).
DEFAULT_DELETE_AFTER = 0
# Partners may pause the distribution in their chats until they resume it (0 = no limit), unless the admins limit it.
DEFAULT_PAUSE_MAX_HOURS = 0

# Global frequency of a new bot: once a day, at 12:00 (a post can also be a one-off broadcast: SchedMode.ONCE).
DEFAULT_FREQ: dict[str, Any] = {"mode": "times", "times": "12:00", "days": "0123456"}


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
class Bot(Base):
    """A Telegram bot run by the platform: the main bot (or a copy of it) or a clone."""

    __tablename__ = "em_bots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(128), default="")
    token_enc: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    managed: Mapped[bool] = mapped_column(Boolean, default=False)  # created with Telegram Managed Bots
    status: Mapped[str] = mapped_column(String(16), default=BotStatus.ACTIVE)
    status_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Madrid")
    # The owner chose the timezone (asked on the first /start of a new clone: Telegram doesn't tell it).
    timezone_set: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    # 🧭 The owner went through the setup wizard of a new bot (bots that existed before it: done).
    setup_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_true())

    # --- distribution ---
    paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())  # ⏸ everything
    freq: Mapped[dict[str, Any]] = mapped_column(JSON, default=lambda: dict(DEFAULT_FREQ))  # 🌐 global frequency
    rot_next_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # next global slot
    rotation: Mapped[str] = mapped_column(String(8), default=RotationOrder.SEQUENTIAL, server_default="seq")
    # 🛡 Anti-spam, per chat: at most N posts a day (bot timezone; 0 = no limit), at least N minutes between two
    # posts (0 = no minimum), and only one post of the network at a time (the previous one is deleted first).
    max_per_day: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    min_gap: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    one_at_a_time: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    # Options of new posts: {"pin", "silent", "protect", "link_preview", "delete_after", "delete_previous"}.
    post_defaults: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # --- external chats (partners) ---
    join_open: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    # ⏸ The admins rule over the partners' pauses: whether partners may pause their chats and for how long at most
    # (hours; 0 = until they resume it). Admins can always resume a partner's pause.
    partners_can_pause: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())
    pause_max_hours: Mapped[int] = mapped_column(Integer, default=DEFAULT_PAUSE_MAX_HOURS,
                                                 server_default=str(DEFAULT_PAUSE_MAX_HOURS))
    join_approval: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())
    min_members: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    join_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # custom text of the join screen (HTML)
    support_username: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 🛟 contact (None = owner)

    # --- limits set by a super admin (None = platform default, 0 = unlimited) ---
    limit_chats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    limit_posts: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class User(Base):
    """A Telegram user (global, shared by all bots)."""

    __tablename__ = "em_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p) or str(self.id)


class BotUser(Base):
    """Per bot state of a user that started that bot."""

    __tablename__ = "em_bot_users"

    bot_id: Mapped[int] = mapped_column(ForeignKey("em_bots.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("em_users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), default=Role.USER)
    lang: Mapped[str] = mapped_column(String(8), default="es")
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)  # 🔔 alerts: chats paused, joined, removed...
    summary: Mapped[bool] = mapped_column(Boolean, default=True)  # 📋 daily summary (admins)
    run_reports: Mapped[bool] = mapped_column(Boolean, default=False)  # 📨 a report after every send (admins)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    # Super admins in a main bot: the clone they manage from there (🛠 Gestionar), None = this bot.
    ws_bot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_em_bot_users_bot_role", "bot_id", "role"),
        Index("ix_em_bot_users_user", "user_id"),  # a person's rows in every bot (the timezone they already chose)
    )


class Chat(Base):
    """A channel or group registered in one bot."""

    __tablename__ = "em_chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("em_bots.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String(16), default=ChatType.CHANNEL)
    title: Mapped[str] = mapped_column(String(256), default="")
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    members: Mapped[int] = mapped_column(Integer, default=0)
    members_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    origin: Mapped[str] = mapped_column(String(8), default=ChatOrigin.OWN)
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)  # who added the bot

    status: Mapped[str] = mapped_column(String(16), default=ChatStatus.PENDING)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    rights_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    missing_rights: Mapped[str] = mapped_column(String(256), default="")

    # ⏸ Pauses: by an admin of the bot (only an admin resumes it) and by the chat's owner (partners, within the
    # bot's rules: Bot.partners_can_pause / pause_max_hours; they resume it, and an admin can resume it too: the
    # admins rule). owner_paused_until None = until resumed; a past date = already over (the scheduler clears it and
    # tells the admins).
    admin_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    owner_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    owner_paused_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # 🗄 Canal almacén (an own channel): it keeps the premium copies of the posts that the other channels receive as
    # forwards (Telegram doesn't let bots send custom emoji to channels); it receives nothing from the network.
    vault: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    rot_last_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # rotation: last post received
    posts_total: Mapped[int] = mapped_column(Integer, default=0)  # posts delivered in this chat
    last_post_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("bot_id", "chat_id", name="uq_em_chats_bot_chat"),
        Index("ix_em_chats_bot_status", "bot_id", "status"),
    )

    @property
    def display_title(self) -> str:
        return (self.title or str(self.chat_id)).strip()

    @property
    def is_channel(self) -> bool:
        return self.type == ChatType.CHANNEL

    @property
    def is_external(self) -> bool:
        return self.origin == ChatOrigin.EXTERNAL

    @property
    def public_link(self) -> str | None:
        return f"https://t.me/{self.username}" if self.username else None

    def owner_pause_active(self, now: datetime | None = None) -> bool:
        """Paused by its owner right now (a pause whose end already passed doesn't count)."""
        if not self.owner_paused:
            return False
        return self.owner_paused_until is None or self.owner_paused_until > (now or utcnow())

    def is_paused(self, now: datetime | None = None) -> bool:
        return self.admin_paused or self.owner_pause_active(now)


class ChatGroup(Base):
    """🗂 A custom group of chats: a target for posts and, optionally, its own frequency."""

    __tablename__ = "em_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("em_bots.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    # None = the chats of the group follow the global frequency; a dict = its own frequency (see services/freq.py).
    freq: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    rot_next_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # next slot (own freq only)
    # 🤝 Partners can join or leave it from their panel, and new external chats join it automatically.
    open: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class GroupChat(Base):
    """Membership of a chat in a 🗂 group."""

    __tablename__ = "em_group_chats"

    group_id: Mapped[int] = mapped_column(ForeignKey("em_groups.id", ondelete="CASCADE"), primary_key=True)
    chat_pk: Mapped[int] = mapped_column(ForeignKey("em_chats.id", ondelete="CASCADE"), primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Post(Base):
    """📝 Content distributed by the network: text or media, buttons, targets, schedule and options."""

    __tablename__ = "em_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("em_bots.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="")  # internal label (defaults to the first words)

    # --- content (see services/content.py) ---
    kind: Mapped[str] = mapped_column(String(16), default="text")  # text|photo|video|animation|document|audio|voice
    text: Mapped[str | None] = mapped_column(Text, nullable=True)  # HTML: the text, or the caption of the media
    # Telegram file ids are per bot: {"<bot id>": "<file id>"} for every bot that has sent the media.
    media: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    media_name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # file name (documents, audio)
    # Rows of buttons: [[{"text": ..., "url": ...} | {"text": ..., "copy": ...}, + optional "style"]].
    buttons: Mapped[list[list[dict[str, str]]]] = mapped_column(JSON, default=list)
    # 💎 Premium copy in the canal almacén (forwarded to channels, which refuse custom emoji sent by bots) and the
    # content signature it was made from (``content.signature``): a different one means it is out of date.
    vault_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vault_msg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vault_sig: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- audience: "all", "own", "ext" and "g<group id>" (see services/audience.py) ---
    targets: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["all"])

    # --- schedule ---
    mode: Mapped[str] = mapped_column(String(16), default=SchedMode.ROTATION)
    freq: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # mode "own"
    send_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # mode "once"
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # 📆 campaign dates (bot timezone)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    # --- options ---
    pin: Mapped[bool] = mapped_column(Boolean, default=False)
    silent: Mapped[bool] = mapped_column(Boolean, default=False)  # disable_notification
    protect: Mapped[bool] = mapped_column(Boolean, default=False)  # protect_content: no forwarding nor saving
    link_preview: Mapped[bool] = mapped_column(Boolean, default=False)
    caption_above: Mapped[bool] = mapped_column(Boolean, default=False)  # show_caption_above_media
    spoiler: Mapped[bool] = mapped_column(Boolean, default=False)  # has_spoiler (photo, video, GIF)
    delete_after: Mapped[int] = mapped_column(Integer, default=DEFAULT_DELETE_AFTER)  # minutes; 0 = never deleted
    delete_previous: Mapped[bool] = mapped_column(Boolean, default=True)  # delete its previous copy in the chat

    status: Mapped[str] = mapped_column(String(16), default=PostStatus.ACTIVE)
    next_send_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)  # own / once
    last_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    runs_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)  # deliveries sent, all runs
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Run(Base):
    """One distribution of a post to a set of chats."""

    __tablename__ = "em_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("em_bots.id", ondelete="CASCADE"), index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("em_posts.id", ondelete="SET NULL"), nullable=True,
                                                index=True)
    post_name: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(16), default=RunKind.MANUAL)
    source: Mapped[str] = mapped_column(String(16), default="")  # rotation: "global" or "g<group id>"
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.SENDING)
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    reach: Mapped[int] = mapped_column(Integer, default=0)  # members of the chats it was sent to
    triggered_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Delivery(Base):
    """A post inside one chat (the Telegram message there)."""

    __tablename__ = "em_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("em_runs.id", ondelete="CASCADE"), index=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("em_posts.id", ondelete="SET NULL"), nullable=True,
                                                index=True)
    chat_pk: Mapped[int | None] = mapped_column(ForeignKey("em_chats.id", ondelete="SET NULL"), nullable=True,
                                                index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=DeliveryStatus.QUEUED)
    error: Mapped[str | None] = mapped_column(String(256), nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    forwarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())  # from the almacén
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    delete_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (
        Index("ix_em_deliveries_status_delete", "status", "delete_at"),
        Index("ix_em_deliveries_chat_sent", "chat_pk", "sent_at"),
    )


class RequestNotice(Base):
    """Admin notices of a pending external chat (edited when someone decides)."""

    __tablename__ = "em_request_notices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_pk: Mapped[int] = mapped_column(ForeignKey("em_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Event(Base):
    """📜 Activity of a bot's network (shown in its panel, sent as alerts to the admins)."""

    __tablename__ = "em_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("em_bots.id", ondelete="CASCADE"))
    chat_pk: Mapped[int | None] = mapped_column(ForeignKey("em_chats.id", ondelete="SET NULL"), nullable=True,
                                                index=True)
    chat_title: Mapped[str] = mapped_column(String(256), default="")  # kept when the chat row is gone
    kind: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_em_events_bot_created", "bot_id", "created_at"),)


class FSMRecord(Base):
    """Persistent aiogram FSM state."""

    __tablename__ = "em_fsm"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class KV(Base):
    """Small key/value store: job bookkeeping and platform settings."""

    __tablename__ = "em_kv"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
