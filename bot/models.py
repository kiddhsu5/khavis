"""Pydantic models exchanged across the bot layers."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BackendName = Literal["claude", "codex", "llm-router"]


class IncomingMessage(BaseModel):
    """A chat message we just received (from webhook OR polling)."""

    update_id: int
    chat_id: int
    user_id: int | None = None
    text: str
    is_command: bool = False


class DispatchEnvelope(BaseModel):
    """A user ``/run`` invocation, after command parsing."""

    chat_id: int
    prompt: str
    only: list[BackendName] | None = None  # None = fan out to all
    capability: str | None = None  # hint for llm-router's CapabilityRouter


class BackendResult(BaseModel):
    """Per-backend completion (success or failure)."""

    backend: BackendName
    ok: bool
    text: str = ""
    error: str = ""
    latency_ms: int = 0
    model: str = ""  # reported by the backend itself
    tokens_in: int = 0
    tokens_out: int = 0
    extra: dict[str, str] = Field(default_factory=dict)


class DispatchReport(BaseModel):
    """Final answer sent back to the originating Telegram chat."""

    envelope: DispatchEnvelope
    results: list[BackendResult]
    consensus: str = ""
    consensus_source: BackendName | str = ""
