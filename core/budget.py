"""Token-aware cost budgets (v0.2.0).

Tracks per-request and per-session token / USD spend, blocks the next
call once a cap is hit, and exposes a status dict for the dashboard.

Typical use::

    from core.budget import get_guard

    guard = get_guard()
    if not guard.allow(session_id="chat-1", pool="MiMo-Code", prompt_chars=800):
        raise RuntimeError(guard.reason())
    result = plugin.chat(...)
    guard.record(session_id="chat-1", pool="MiMo-Code", usage=result.get("usage"))

Policy is YAML-first (``config/budgets.yaml``) with env overrides.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_POLICY: dict[str, Any] = {
    "max_tokens_per_request": 32_000,
    "max_tokens_per_session": 400_000,
    "max_cost_per_session_usd": 5.0,
    "window_s": 3600.0,
    "filter_router": True,
}


@dataclass
class BudgetPolicy:
    max_tokens_per_request: int = 32_000
    max_tokens_per_session: int = 400_000
    max_cost_per_session_usd: float = 5.0
    window_s: float = 3600.0
    filter_router: bool = True
    pricing_usd_per_1k: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BudgetPolicy:
        pol = dict(_DEFAULT_POLICY)
        pol.update(data.get("policy") or {})
        pricing = {str(k): float(v) for k, v in (data.get("pricing_usd_per_1k") or {}).items()}
        return cls(
            max_tokens_per_request=int(pol["max_tokens_per_request"]),
            max_tokens_per_session=int(pol["max_tokens_per_session"]),
            max_cost_per_session_usd=float(pol["max_cost_per_session_usd"]),
            window_s=float(pol["window_s"]),
            filter_router=bool(pol["filter_router"]),
            pricing_usd_per_1k=pricing,
        )


def load_policy(path: Path | str | None = None) -> BudgetPolicy:
    """Load ``config/budgets.yaml``; apply env overrides."""
    if path is None:
        path = Path(__file__).resolve().parent.parent / "config" / "budgets.yaml"
    data: dict[str, Any] = {}
    p = Path(path)
    if p.exists():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            data = {}
    policy = BudgetPolicy.from_dict(data)

    def _env_int(name: str, cur: int) -> int:
        raw = os.environ.get(name)
        return int(raw) if raw and raw.isdigit() else cur

    def _env_float(name: str, cur: float) -> float:
        raw = os.environ.get(name)
        try:
            return float(raw) if raw else cur
        except ValueError:
            return cur

    policy.max_tokens_per_request = _env_int("KHAVIS_BUDGET_MAX_TOKENS_REQUEST", policy.max_tokens_per_request)
    policy.max_tokens_per_session = _env_int("KHAVIS_BUDGET_MAX_TOKENS_SESSION", policy.max_tokens_per_session)
    policy.max_cost_per_session_usd = _env_float(
        "KHAVIS_BUDGET_MAX_COST_SESSION_USD", policy.max_cost_per_session_usd
    )
    policy.window_s = _env_float("KHAVIS_BUDGET_WINDOW_S", policy.window_s)
    return policy


def estimate_tokens(text: str | None) -> int:
    """Cheap char/4 heuristic — good enough for pre-flight caps."""
    if not text:
        return 0
    return max(1, len(text) // 4)


@dataclass
class _Event:
    ts: float
    tokens: int
    cost_usd: float
    pool: str


class BudgetGuard:
    """Sliding-window session budget + per-request cap."""

    def __init__(self, policy: BudgetPolicy | None = None) -> None:
        self.policy = policy or load_policy()
        self._lock = threading.Lock()
        self._sessions: dict[str, deque[_Event]] = {}
        self._last_reason = ""

    # ------------------------------------------------------------------
    def reason(self) -> str:
        return self._last_reason

    def _window(self, session_id: str) -> deque[_Event]:
        q = self._sessions.setdefault(session_id, deque())
        cutoff = time.time() - self.policy.window_s
        while q and q[0].ts < cutoff:
            q.popleft()
        return q

    def _session_usage_unlocked(self, session_id: str) -> dict[str, float]:
        q = self._window(session_id)
        return {
            "tokens": float(sum(e.tokens for e in q)),
            "cost_usd": round(sum(e.cost_usd for e in q), 6),
            "calls": float(len(q)),
        }

    def session_usage(self, session_id: str) -> dict[str, float]:
        with self._lock:
            return self._session_usage_unlocked(session_id)

    def pool_usage(self, session_id: str | None = None) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        with self._lock:
            for sid, q in self._sessions.items():
                if session_id and sid != session_id:
                    continue
                self._window(sid)  # prune
                for e in q:
                    row = out.setdefault(e.pool, {"tokens": 0.0, "cost_usd": 0.0, "calls": 0.0})
                    row["tokens"] += e.tokens
                    row["cost_usd"] += e.cost_usd
                    row["calls"] += 1
        return out

    def cost_of(self, pool: str, tokens: int) -> float:
        rate = self.policy.pricing_usd_per_1k.get(pool, 0.0)
        return rate * tokens / 1000.0

    # ------------------------------------------------------------------
    def allow(
        self,
        *,
        session_id: str = "default",
        pool: str = "",
        prompt_chars: int = 0,
        estimated_completion_tokens: int = 0,
    ) -> bool:
        """Pre-flight check. Sets :meth:`reason` when denying."""
        est = estimate_tokens("x" * prompt_chars) + int(estimated_completion_tokens)
        pol = self.policy
        if est > pol.max_tokens_per_request:
            self._last_reason = (
                f"request estimate {est} tokens exceeds max_tokens_per_request="
                f"{pol.max_tokens_per_request}"
            )
            return False
        with self._lock:
            usage = self._session_usage_unlocked(session_id)
        if usage["tokens"] + est > pol.max_tokens_per_session:
            self._last_reason = (
                f"session {session_id!r} at {int(usage['tokens'])} tokens; "
                f"cap max_tokens_per_session={pol.max_tokens_per_session}"
            )
            return False
        if pol.max_cost_per_session_usd > 0:
            projected = usage["cost_usd"] + self.cost_of(pool, est)
            if projected > pol.max_cost_per_session_usd:
                self._last_reason = (
                    f"session cost ${usage['cost_usd']:.4f} + est ${self.cost_of(pool, est):.4f} "
                    f"would exceed max_cost_per_session_usd={pol.max_cost_per_session_usd}"
                )
                return False
        self._last_reason = ""
        return True

    def record(
        self,
        *,
        session_id: str = "default",
        pool: str = "",
        usage: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """Record actual usage after a successful (or failed) chat()."""
        usage = usage or {}
        tokens = int(
            (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        )
        if tokens <= 0:
            tokens = int(usage.get("total_tokens") or 0)
        cost = self.cost_of(pool, tokens)
        ev = _Event(ts=time.time(), tokens=tokens, cost_usd=cost, pool=pool or "?")
        with self._lock:
            self._window(session_id).append(ev)
            # drop sessions with no recent events to bound memory
            cutoff = time.time() - self.policy.window_s
            for sid in list(self._sessions):
                q = self._sessions[sid]
                while q and q[0].ts < cutoff:
                    q.popleft()
                if not q:
                    del self._sessions[sid]
        return {"tokens": float(tokens), "cost_usd": cost}

    def status(self) -> dict[str, Any]:
        pol = self.policy
        return {
            "policy": {
                "max_tokens_per_request": pol.max_tokens_per_request,
                "max_tokens_per_session": pol.max_tokens_per_session,
                "max_cost_per_session_usd": pol.max_cost_per_session_usd,
                "window_s": pol.window_s,
                "filter_router": pol.filter_router,
            },
            "sessions": {sid: self.session_usage(sid) for sid in list(self._sessions)},
            "by_pool": self.pool_usage(),
        }


_GUARD: BudgetGuard | None = None
_GUARD_LOCK = threading.Lock()


def get_guard() -> BudgetGuard:
    """Process-wide singleton (re-read policy is explicit via reset())."""
    global _GUARD  # noqa: PLW0603
    with _GUARD_LOCK:
        if _GUARD is None:
            _GUARD = BudgetGuard()
        return _GUARD


def reset_guard(policy: BudgetPolicy | None = None) -> BudgetGuard:
    global _GUARD  # noqa: PLW0603
    with _GUARD_LOCK:
        _GUARD = BudgetGuard(policy)
        return _GUARD
