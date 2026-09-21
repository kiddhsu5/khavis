"""Parse incoming messages and route to the right handler."""
from __future__ import annotations

import shlex
from collections.abc import Callable, Coroutine, Iterable
from typing import Any

from .models import BackendName, DispatchEnvelope, IncomingMessage

HELP_TEXT = """\
*llm-router dispatch bot*

Commands:
  /start \\- welcome + allowlist check
  /help \\- this message
  /status \\- per\\-backend health snapshot
  /pools \\- list llm\\-router pools and capabilities
  /run \\<prompt\\> \\- fan\\-out to claude, codex, llm\\-router
  /run \\-\\-only claude,codex \\<prompt\\> \\- subset
  /run \\-\\-capability code \\<prompt\\> \\- hint for the gateway

Operators: webhooks register at `POST /webhook/<token>`; long\\-poll \
fallback is automatic when the public endpoint is unreachable.
"""


def is_allowed(chat_id: int, allowlist: Iterable[int]) -> bool:
    """Empty allowlist means *no one* — refuse until the operator \
explicitly opts in via env."""
    allow = list(allowlist)
    if not allow:
        return False
    return chat_id in allow


def parse_run_command(text: str) -> tuple[list[BackendName] | None, str | None, str]:
    """Parse ``/run [--only X,Y] [--capability Z] <prompt>``.

    Returns ``(only, capability, prompt)``.  ``only`` is None when no
    ``--only`` flag was passed (means "all backends").  ``capability``
    is None when not specified.  ``prompt`` is the remainder after
    stripping flags.
    """
    parts = shlex.split(text)
    if not parts or parts[0] != "/run":
        return None, None, ""
    args = parts[1:]
    only: list[BackendName] | None = None
    capability: str | None = None
    prompt_parts: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--only" and i + 1 < len(args):
            allowed: set[str] = {"claude", "codex", "llm-router"}
            only = [p for p in args[i + 1].split(",") if p in allowed]  # type: ignore[list-item]
            i += 2
            continue
        if a.startswith("--capability="):
            capability = a.split("=", 1)[1] or None
            i += 1
            continue
        if a == "--capability" and i + 1 < len(args):
            capability = args[i + 1]
            i += 2
            continue
        prompt_parts.append(a)
        i += 1
    return only, capability, " ".join(prompt_parts).strip()


# Per-message handler signature: (msg, deps) -> None
CommandHandler = Callable[[IncomingMessage, "HandlerDeps"], Coroutine[Any, Any, None]]


class HandlerDeps:
    """Bundle of services a command handler may need.

    Filled in by ``main.lifespan`` and passed to each handler invocation.
    """

    def __init__(
        self,
        telegram: object,  # TelegramAPI (avoid forward ref to dodge cycles)
        allowlist: list[int],
        backends: dict[str, object],
        pools: list[tuple[str, list[str]]] | None = None,
    ) -> None:
        self.telegram = telegram
        self.allowlist = allowlist
        self.backends = backends
        self.pools = pools or []


async def handle_start(msg: IncomingMessage, deps: HandlerDeps) -> None:
    from .telegram_api import TelegramAPI

    api: TelegramAPI = deps.telegram  # type: ignore[assignment]
    if not is_allowed(msg.chat_id, deps.allowlist):
        await api.send_message(msg.chat_id, "🚫 Not authorized.")
        return
    await api.send_message(
        msg.chat_id,
        f"👋 Welcome\\! Send /help for usage. (chat_id={msg.chat_id})",
        reply_to=msg.update_id,
    )


async def handle_help(msg: IncomingMessage, deps: HandlerDeps) -> None:
    from .telegram_api import TelegramAPI

    api: TelegramAPI = deps.telegram  # type: ignore[assignment]
    if not is_allowed(msg.chat_id, deps.allowlist):
        return
    await api.send_message(msg.chat_id, HELP_TEXT, reply_to=msg.update_id)


async def handle_status(msg: IncomingMessage, deps: HandlerDeps) -> None:
    from .telegram_api import TelegramAPI

    api: TelegramAPI = deps.telegram  # type: ignore[assignment]
    if not is_allowed(msg.chat_id, deps.allowlist):
        return
    lines = ["*backend status*"]
    for name, backend in deps.backends.items():
        # Each backend exposes ``.health() -> dict``
        try:
            h = await backend.health()  # type: ignore[attr-defined]
            ok = h.get("ok")
            detail = h.get("detail", "")
            check = "✅" if ok else "❌"
            lines.append(f"{check} `{name}` \\- {detail}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"❌ `{name}` \\- error: {exc!r}")
    await api.send_message(msg.chat_id, "\n".join(lines), reply_to=msg.update_id)


async def handle_pools(msg: IncomingMessage, deps: HandlerDeps) -> None:
    from .telegram_api import TelegramAPI

    api: TelegramAPI = deps.telegram  # type: ignore[assignment]
    if not is_allowed(msg.chat_id, deps.allowlist):
        return
    if not deps.pools:
        await api.send_message(msg.chat_id, "_(no pools registered)_")
        return
    lines = ["*llm\\-router pools*"]
    for name, caps in deps.pools:
        cap_str = TelegramAPI.escape_markdown_v2(", ".join(caps))
        lines.append(f"• `{TelegramAPI.escape_markdown_v2(name)}` — {cap_str}")
    await api.send_message(msg.chat_id, "\n".join(lines), reply_to=msg.update_id)


async def handle_run(msg: IncomingMessage, deps: HandlerDeps) -> DispatchEnvelope | None:
    from .telegram_api import TelegramAPI

    api: TelegramAPI = deps.telegram  # type: ignore[assignment]
    if not is_allowed(msg.chat_id, deps.allowlist):
        return DispatchEnvelope(chat_id=msg.chat_id, prompt="")
    only, capability, prompt = parse_run_command(msg.text or "")
    if not prompt:
        await api.send_message(
            msg.chat_id,
            "usage: /run \\<prompt\\>",
            reply_to=msg.update_id,
        )
        return None
    # The actual fan-out happens in dispatch.dispatch(); this handler
    # just parses. The wiring is in main.py.
    return DispatchEnvelope(
        chat_id=msg.chat_id,
        prompt=prompt,
        only=only,
        capability=capability,
    )


# Convenience registry used by main.py
COMMANDS: dict[str, CommandHandler] = {
    "/start": handle_start,
    "/help": handle_help,
    "/status": handle_status,
    "/pools": handle_pools,
}


def route_command(text: str) -> CommandHandler | None:
    """Return the handler for ``text``'s leading command, or None."""
    head = (text or "").strip().split(maxsplit=1)[0].lower()
    if head in COMMANDS:
        return COMMANDS[head]
    if head == "/run":
        return handle_run
    return None
