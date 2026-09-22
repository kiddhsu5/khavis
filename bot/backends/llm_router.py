"""In-process backend that runs the llm-router multi-agent team.

Drives ``agents.run_team`` (planner → coder_a / coder_b → debate →
critic → verify → learn) for a single user prompt, returning the
final synthesised answer plus attribution. The graph runs
synchronously under the hood, so we off-load it to a thread executor
to keep the FastAPI event loop free.
"""

from __future__ import annotations

import asyncio
import time
from functools import partial

from ..models import BackendResult, DispatchEnvelope
from .base import Backend, HealthResult


class LLMRouterBackend(Backend):
    """Runs ``agents.run_team`` against the llm-router pool registry."""

    name = "llm-router"

    def __init__(self, session_id: str = "bot") -> None:
        self._session_id = session_id
        self._lock = asyncio.Lock()

    async def health(self) -> HealthResult:
        # Lightweight: just confirm the registry can be built.
        try:
            from core.registry import PluginRegistry  # noqa: PLC0415

            reg = PluginRegistry().discover()
            return HealthResult(True, f"{len(reg)} pools registered")
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, repr(exc))

    async def run(self, envelope: DispatchEnvelope) -> BackendResult:
        try:
            from agents import run_team  # noqa: PLC0415 - lazy

            loop = asyncio.get_running_loop()
            t0 = time.perf_counter()
            state = await loop.run_in_executor(
                None,
                partial(
                    run_team,
                    envelope.prompt,
                    session_id=self._session_id,
                ),
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
        except Exception as exc:  # noqa: BLE001
            return BackendResult(
                backend="llm-router",
                ok=False,
                error=repr(exc),
            )

        # Extract the canonical answer from the team state. Prefer the
        # synthesised ``final``; fall back to whichever stage has output.
        if not isinstance(state, dict):
            state = {}
        try:
            final = (state.get("final") or "").strip()
            if not final:
                final = (state.get("code_a") or state.get("plan") or "").strip()
            error_msg = state.get("error") or ""
            rounds = state.get("rounds", 0)
            attribution = state.get("attribution") or {}
            records = attribution.get("records") if isinstance(attribution, dict) else []
            plan = state.get("plan")
            code_b = state.get("code_b")
            fallback_used = state.get("fallback_used", False)
        except Exception as exc:  # noqa: BLE001
            return BackendResult(
                backend="llm-router",
                ok=False,
                error=f"malformed team state: {exc!r}",
            )

        if not final:
            return BackendResult(
                backend="llm-router",
                ok=False,
                error=error_msg or "team produced no answer",
                model="run_team",
                extra={"rounds": str(rounds)},
            )

        extra = {
            "rounds": str(rounds),
            "fallback_used": str(fallback_used),
            "steps": str(len(records)),
        }
        if plan:
            extra["has_plan"] = "1"
        if code_b:
            extra["two_coders"] = "1"

        return BackendResult(
            backend="llm-router",
            ok=True,
            text=final,
            model="agents.run_team",
            latency_ms=latency_ms,
            extra=extra,
        )
