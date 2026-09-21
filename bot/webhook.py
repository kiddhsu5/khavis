"""Webhook route — single FastAPI route + secret-token validation."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from .models import IncomingMessage

if TYPE_CHECKING:
    from .secrets import BotSecrets


async def webhook_route(
    request: Request,
    secrets: BotSecrets,
    handler: Callable[[IncomingMessage], Awaitable[None]],
) -> dict[str, bool]:
    """Validate ``X-Telegram-Bot-Api-Secret-Token`` and dispatch."""
    expected = secrets.webhook_secret.encode()
    provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "").encode()
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=403, detail="bad secret token")
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid json: {exc!s}") from exc
    msg = payload.get("message") or payload.get("edited_message") or {}
    chat = msg.get("chat") or {}
    text = msg.get("text") or ""
    if not chat or not text:
        # Telegram sends non-text updates too — we just drop them.
        return {"ok": True}
    incoming = IncomingMessage(
        update_id=int(payload.get("update_id", 0)),
        chat_id=int(chat.get("id", 0)),
        user_id=(msg.get("from") or {}).get("id"),
        text=text,
        is_command=text.startswith("/"),
    )
    await handler(incoming)
    return {"ok": True}
