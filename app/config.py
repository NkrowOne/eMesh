from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_ignore_empty: hosting panels often keep variables with an empty value; they mean "use the default".
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                      env_ignore_empty=True)

    # --- Telegram ---
    BOT_TOKEN: str = Field(..., description="Token of the main bot (from @BotFather)")
    # Other bots that work exactly like the main bot (same mode, panel, clone creation), e.g. other usernames.
    EXTRA_MAIN_TOKENS: str = Field("", description="Comma separated tokens of copies of the main bot")
    SUPER_ADMIN_IDS: str = Field("", description="Comma separated Telegram user ids with full platform control")
    TELEGRAM_API_BASE: str | None = Field(None, description="Custom Bot API server base URL (tests / local API)")

    # --- Runtime mode ---
    MODE: Literal["polling", "webhook"] = "polling"
    # full: the main bot distributes posts like any clone (plus the 👑 panel and clone creation);
    # hub: the main bot only explains the service, creates clones and hosts the 👑 panel.
    MAIN_BOT_MODE: Literal["full", "hub"] = "full"
    WEBHOOK_BASE_URL: str | None = None
    WEBHOOK_PATH_PREFIX: str = "/tg"
    WEBHOOK_SECRET: str | None = None
    PORT: int = 8080
    HOST: str = "0.0.0.0"

    # --- Storage ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./emesh.db"
    # eButtons' database, to reuse the timezone people already chose there. Empty: eMesh's own database (both
    # projects prefix their tables, em_ / eb_, so they can share one).
    EBUTTONS_DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    RUN_MIGRATIONS: bool = True
    ENCRYPTION_KEY: str | None = Field(None, description="Fernet key used to encrypt clone bot tokens")

    # --- Defaults ---
    DEFAULT_LANG: str = "es"
    DEFAULT_TIMEZONE: str = "Europe/Madrid"
    LOG_LEVEL: str = "INFO"

    # --- Rate limits (per bot token) ---
    RL_GLOBAL_PER_SEC: float = 27.0
    RL_BULK_PER_SEC: float = 20.0
    RL_PRIVATE_PER_SEC: float = 1.0
    RL_PRIVATE_BURST: int = 3
    RL_GROUP_PER_MIN: int = 19
    RL_MAX_RETRIES: int = 6
    RL_NETWORK_RETRIES: int = 2

    # --- Engine ---
    SCHEDULER_TICK_SECONDS: int = 10
    # A slot or a scheduled post found more than this late (the bot was down) is skipped, not sent late.
    LATE_SKIP_MINUTES: int = 30
    SEND_CONCURRENCY: int = 8  # chats a run sends to at the same time (the rate limiter still applies)
    MAINTENANCE_INTERVAL_HOURS: int = 6  # members, title and rights of every chat are refreshed this often
    SUMMARY_HOUR: int = 9  # 📋 daily summary to the admins, bot timezone
    RETENTION_DAYS: int = 30  # runs, deliveries and activity older than this are deleted

    # --- Clones (defaults; the super admins change them in 👑 Panel › ⚙️ Plataforma) ---
    CLONE_POLICY: Literal["open", "approval", "closed"] = "open"
    MAX_CLONES_PER_USER: int = 3
    DEFAULT_LIMIT_CHATS: int = 0  # chats per clone, 0 = unlimited
    DEFAULT_LIMIT_POSTS: int = 0  # posts per clone, 0 = unlimited

    UPDATE_CONCURRENCY_PER_BOT: int = 16
    THROTTLE_LIMIT: int = 30  # max updates per user per THROTTLE_WINDOW seconds
    THROTTLE_WINDOW: float = 10.0

    @field_validator("DATABASE_URL", "EBUTTONS_DATABASE_URL")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    @property
    def main_bot_id(self) -> int:
        """Id of the main bot (the first part of its token)."""
        head = self.BOT_TOKEN.split(":", 1)[0]
        return int(head) if head.isdigit() else 0

    @property
    def main_copy_tokens(self) -> list[str]:
        tokens = [t.strip() for t in self.EXTRA_MAIN_TOKENS.replace(";", ",").split(",")]
        return [t for t in dict.fromkeys(tokens) if t and t != self.BOT_TOKEN]

    @property
    def super_admin_ids(self) -> set[int]:
        out: set[int] = set()
        for part in self.SUPER_ADMIN_IDS.replace(";", ",").split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                out.add(int(part))
        return out

    @property
    def primary_super_admin(self) -> int | None:
        for part in self.SUPER_ADMIN_IDS.replace(";", ",").split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                return int(part)
        return None

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
