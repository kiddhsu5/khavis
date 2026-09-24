"""Telegram dispatch bot backends for khavis.

Sub-modules:
- ``base``     abstract ``Backend`` protocol
- ``claude``   subprocess wrapper around ``claude -p``
- ``codex``    subprocess wrapper around ``codex exec``
- ``khavis``  in-process call to ``agents.run_team`` / ``core.registry``
"""

from __future__ import annotations

from .base import Backend, HealthResult
from .claude import ClaudeBackend
from .codex import CodexBackend
from .judge import JudgeBackend
from .khavis import KhavisBackend

__all__ = [
    "Backend",
    "HealthResult",
    "ClaudeBackend",
    "CodexBackend",
    "JudgeBackend",
    "KhavisBackend",
]
