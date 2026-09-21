"""Telegram dispatch bot backends for llm-router.

Sub-modules:
- ``base``     abstract ``Backend`` protocol
- ``claude``   subprocess wrapper around ``claude -p``
- ``codex``    subprocess wrapper around ``codex exec``
- ``llm_router``  in-process call to ``agents.run_team`` / ``core.registry``
"""
from __future__ import annotations

from .base import Backend, HealthResult
from .claude import ClaudeBackend
from .codex import CodexBackend
from .llm_router import LLMRouterBackend

__all__ = [
    "Backend",
    "HealthResult",
    "ClaudeBackend",
    "CodexBackend",
    "LLMRouterBackend",
]
