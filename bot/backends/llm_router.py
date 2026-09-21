"""In-process backend that calls llm-router's own pools."""

from __future__ import annotations

import asyncio
import time
from functools import partial
from typing import Any

from ..models import BackendResult, DispatchEnvelope
from .base import Backend, HealthResult


class LLMRouterBackend(Backend):
    """Calls ``agents.run_team`` (or a single-pool shortcut) in-process."""

    name = "llm-router"

    def __init__(self, capability: str | None = None) -> None:
        self._capability = capability
        self._registry: Any = None
        self._lock = asyncio.Lock()

    async def _ensure_registry(self) -> Any:
        if self._registry is not None:
            return self._registry
        async with self._lock:
            if self._registry is None:
                # Lazy import so the bot can start before llm-router deps
                # are fully resolved (e.g. in unit tests).
                from core.registry import PluginRegistry  # noqa: PLC0415

                reg = PluginRegistry().discover()
                pools_yaml = reg.project_root / "config" / "pools.yaml"
                if pools_yaml.exists():
                    reg.apply_pools_config(pools_yaml)
                self._registry = reg
        return self._registry

    async def health(self) -> HealthResult:
        try:
            reg = await self._ensure_registry()
            ok = len(reg) > 0
            return HealthResult(ok, f"{len(reg)} pools registered")
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, repr(exc))

    async def run(self, envelope: DispatchEnvelope) -> BackendResult:
        cap = envelope.capability or self._capability or "general"
        try:
            reg = await self._ensure_registry()
            # Pick first healthy plugin that advertises the capability.
            chosen = next(iter(reg.by_capability(cap)), None)
            if chosen is None:
                chosen = next(iter(reg), None)
            if chosen is None:
                return BackendResult(
                    backend="llm-router",
                    ok=False,
                    error="no pools available",
                )
            t0 = time.perf_counter()
            chat = await asyncio.get_running_loop().run_in_executor(
                None,
                partial(
                    chosen.chat,
                    [{"role": "user", "content": envelope.prompt}],
                ),
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
            text = ""
            if isinstance(chat, dict):
                choices = chat.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    msg = choices[0].get("message") or {}
                    text = msg.get("content") or ""
            return BackendResult(
                backend="llm-router",
                ok=bool(text),
                text=text or "(empty reply)",
                model=str(getattr(chosen, "model", "") or ""),
                latency_ms=latency_ms,
                extra={"pool": str(getattr(chosen, "name", ""))},
            )
        except Exception as exc:  # noqa: BLE001
            return BackendResult(
                backend="llm-router",
                ok=False,
                error=repr(exc),
            )
