"""Long-polling loop — fallback when webhook is unreachable.

Same message-routing path as the webhook route; the only difference is
the source. Both call ``handle_update()`` (in ``main.py``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import httpx

from .models import IncomingMessage

if TYPE_CHECKING:
    from .secrets import BotSecrets

API_BASE = "https://api.telegram.org/bot{token}/getUpdates"


def _make_get_updates_url(token: str) -> str:
    return API_BASE.format(token=token)


async def long_poll_loop(
    secrets: BotSecrets,
    handler: Callable[[IncomingMessage], Awaitable[None]],
    *,
    stop: asyncio.Event,
    timeout_s: int = 30,
    poll_timeout_s: int = 30,
) -> None:
    """Run forever, calling ``handler`` for each new update.

    Robust to transient network failures (exponential back-off up to
    30 s). Stops cleanly when ``stop`` is set.
    """
    url = _make_get_updates_url(secrets.bot_token)
    offset: int | None = None
    backoff = 1.0
    async with httpx.AsyncClient(timeout=poll_timeout_s + 5) as client:
        while not stop.is_set():
            params: dict[str, int | str] = {
                "timeout": poll_timeout_s,
                "allowed_updates": '["message"]',
            }
            if offset is not None:
                params["offset"] = offset
            try:
                r = await client.get(url, params=params)
            except (TimeoutError, httpx.HTTPError) as exc:
                # Network glitch — back off and retry.
                wait = min(backoff, 30)
                await _sleep_or_stop(stop, wait)
                backoff = min(backoff * 2, 30)
                _log(f"getUpdates error: {exc!r}; sleeping {wait}s")
                continue
            if r.status_code != 200:
                wait = min(backoff, 30)
                await _sleep_or_stop(stop, wait)
                backoff = min(backoff * 2, 30)
                _log(f"getUpdates HTTP {r.status_code}; sleeping {wait}s")
                continue
            backoff = 1.0  # reset on success
            try:
                data = r.json()
            except ValueError:
                continue
            if not data.get("ok"):
                _log(f"getUpdates payload error: {data}")
                continue
            for upd in data.get("result") or []:
                offset = max(offset or 0, int(upd.get("update_id", 0)) + 1)
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = msg.get("text") or ""
                chat = msg.get("chat") or {}
                if not chat or not text:
                    continue
                incoming = IncomingMessage(
                    update_id=int(upd.get("update_id", 0)),
                    message_id=msg.get("message_id"),
                    chat_id=int(chat.get("id", 0)),
                    user_id=(msg.get("from") or {}).get("id"),
                    text=text,
                    is_command=text.startswith("/"),
                )
                try:
                    await handler(incoming)
                except Exception as exc:  # noqa: BLE001
                    _log(f"handler error: {exc!r}")


def _log(msg: str) -> None:
    """Best-effort logger (stdout). Tests replace via monkeypatch."""
    print(f"[bot.polling] {msg}", flush=True)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        return
