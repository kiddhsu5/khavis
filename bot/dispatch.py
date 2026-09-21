"""Fan-out orchestrator: run N backends in parallel, collect results."""
from __future__ import annotations

import asyncio
from collections.abc import Iterable

from .backends.base import Backend
from .models import BackendName, BackendResult, DispatchEnvelope, DispatchReport

DEFAULT_BACKEND_ORDER: tuple[BackendName, ...] = ("claude", "codex", "llm-router")


class DispatchRouter:
    """Owns the set of available backends; resolves ``envelope.only``."""

    def __init__(self, backends: dict[BackendName, Backend]) -> None:
        self._backends = backends

    @property
    def names(self) -> list[BackendName]:
        return list(self._backends.keys())  # type: ignore[return-value]

    def _resolve(self, envelope: DispatchEnvelope) -> list[Backend]:
        wanted = envelope.only
        if wanted is None:
            wanted = list(DEFAULT_BACKEND_ORDER)
        return [self._backends[name] for name in wanted if name in self._backends]

    async def dispatch(self, envelope: DispatchEnvelope) -> DispatchReport:
        """Run the resolved backends in parallel; never raise."""
        targets = self._resolve(envelope)
        if not targets:
            return DispatchReport(envelope=envelope, results=[], consensus="(no backends)")
        results = await asyncio.gather(
            *(b.run(envelope) for b in targets),
            return_exceptions=False,
        )
        consensus_text, source = synthesize(results)
        return DispatchReport(
            envelope=envelope,
            results=list(results),
            consensus=consensus_text,
            consensus_source=source,
        )

    async def health_all(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for name, backend in self._backends.items():
            try:
                h = await backend.health()
                out[name] = {"ok": "yes" if h.ok else "no", "detail": h.detail}
            except Exception as exc:  # noqa: BLE001
                out[name] = {"ok": "no", "detail": repr(exc)}
        return out


def synthesize(
    results: Iterable[BackendResult],
) -> tuple[str, str]:
    """Pick the best non-empty backend answer.

    Heuristic: longest answer (in characters) above 20 chars wins.
    If none clear the threshold, return whatever's first.
    """
    items = [r for r in results if r.ok and r.text.strip()]
    if not items:
        return "", ""
    items.sort(key=lambda r: len(r.text), reverse=True)
    top = items[0]
    if len(top.text) >= 20:
        return top.text, top.backend
    # Fall back to the first available, even if short.
    return items[0].text, items[0].backend
