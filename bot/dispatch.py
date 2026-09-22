"""Fan-out orchestrator: run N backends in parallel, collect results."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable

from .backends.base import Backend
from .models import BackendName, BackendResult, DispatchEnvelope, DispatchReport

DEFAULT_BACKEND_ORDER: tuple[BackendName, ...] = ("claude", "codex", "llm-router")


# Streaming callback: receives (newly_completed_result, all_results_so_far).
# The orchestrator awaits this after every backend finishes.
StreamingCallback = Callable[[BackendResult, list[BackendResult]], Awaitable[None]]


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
            return DispatchReport(envelope=envelope, results=[], consensus="")
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

    async def dispatch_streaming(
        self,
        envelope: DispatchEnvelope,
        on_complete: StreamingCallback,
    ) -> DispatchReport:
        """Like ``dispatch`` but calls ``on_complete`` after each backend finishes.

        The callback receives the *new* BackendResult plus the full results
        list so far, so callers can re-render an in-place Telegram message
        edit. Telegram rate-limits edits to ~1/sec per chat, so the
        callback should debounce when streaming to many backends.
        """
        targets = self._resolve(envelope)
        if not targets:
            return DispatchReport(envelope=envelope, results=[], consensus="")

        results: list[BackendResult] = []
        pending_tasks: dict[asyncio.Task[BackendResult], Backend] = {
            asyncio.create_task(b.run(envelope), name=b.name): b for b in targets
        }
        for fut in asyncio.as_completed(list(pending_tasks.keys())):
            try:
                result = await fut
            except Exception as exc:  # pragma: no cover - defensive
                # Should not happen since Backend.run swallows, but log defensively.
                result = BackendResult(
                    backend="unknown",
                    ok=False,
                    error=f"dispatch error: {exc!r}",
                )
            results.append(result)
            try:
                await on_complete(result, list(results))
            except Exception as exc:  # noqa: BLE001
                # Callback errors must not derail the whole dispatch.
                # The orchestrator will keep waiting for the remaining
                # backends; the next iteration's edit will catch up.
                print(f"[bot.dispatch] on_complete error: {exc!r}", flush=True)
        consensus_text, source = synthesize(results)
        return DispatchReport(
            envelope=envelope,
            results=results,
            consensus=consensus_text,
            consensus_source=source,
        )

    async def dispatch_async(
        self,
        envelope: DispatchEnvelope,
    ) -> AsyncIterator[BackendResult]:
        """Async iterator yielding each BackendResult as it finishes.

        Same as ``dispatch_streaming`` but without the callback — useful
        when the caller wants to drive the edits itself.
        """
        targets = self._resolve(envelope)
        if not targets:
            return
        pending = {asyncio.create_task(b.run(envelope), name=b.name): b for b in targets}
        for fut in asyncio.as_completed(list(pending.keys())):
            try:
                yield await fut
            except Exception as exc:  # pragma: no cover - defensive
                yield BackendResult(
                    backend="unknown",
                    ok=False,
                    error=f"dispatch error: {exc!r}",
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
    return items[0].text, items[0].backend
