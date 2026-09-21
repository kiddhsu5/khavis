"""Bot secrets: token + allowlist + timeouts.

Tokens are sourced from environment variables only; ``pairing_loader`` is a
separate helper that reads the *historical* pairing JSON (which holds the
allowlist of chat IDs and any cached metadata) but never holds the token
itself in source-controlled files.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field


@dataclass
class BotSecrets:
    """Runtime credentials and limits for the dispatch bot."""

    bot_token: str
    webhook_secret: str  # sent as X-Telegram-Bot-Api-Secret-Token
    allowed_chat_ids: list[int] = field(default_factory=list)
    backend_timeout_s: int = 180
    long_poll_timeout_s: int = 30

    @classmethod
    def from_env(cls) -> BotSecrets:
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "BOT_TOKEN environment variable is required. "
                "Obtain it from @BotFather and inject via .env or "
                "docker-compose, never commit it to source."
            )
        secret = os.environ.get("WEBHOOK_SECRET", token).strip()
        allowed = _parse_allowed_chat_ids(os.environ.get("ALLOWED_CHAT_IDS", ""))
        timeout = int(os.environ.get("BACKEND_TIMEOUT_S", "180"))
        poll = int(os.environ.get("LONG_POLL_TIMEOUT_S", "30"))
        return cls(
            bot_token=token,
            webhook_secret=secret,
            allowed_chat_ids=allowed,
            backend_timeout_s=timeout,
            long_poll_timeout_s=poll,
        )


def _parse_allowed_chat_ids(raw: str) -> list[int]:
    """Parse ``"123,456,789"`` into ``[123, 456, 789]``."""
    out: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        with contextlib.suppress(ValueError):
            out.append(int(chunk))
    return out
