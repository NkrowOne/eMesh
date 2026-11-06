from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings

log = logging.getLogger(__name__)


class TokenCipher:
    """Encrypts bot tokens at rest."""

    def __init__(self, settings: Settings) -> None:
        key = settings.ENCRYPTION_KEY
        if not key:
            log.warning("ENCRYPTION_KEY is not set: deriving it from BOT_TOKEN. Set ENCRYPTION_KEY in production.")
            key = base64.urlsafe_b64encode(hashlib.sha256(("emesh:" + settings.BOT_TOKEN).encode()).digest()).decode()
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt(self, token_enc: str) -> str | None:
        try:
            return self._fernet.decrypt(token_enc.encode()).decode()
        except (InvalidToken, ValueError):
            log.error("Cannot decrypt a stored bot token (ENCRYPTION_KEY changed?)")
            return None
