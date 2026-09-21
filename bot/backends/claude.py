"""Subprocess wrapper for ``claude -p`` (Claude Code headless)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from typing import Any

from ..models import BackendResult, DispatchEnvelope
from .base import Backend, HealthResult


class ClaudeBackend(Backend):
    name = "claude"

    def __init__(self, binary: str = "claude", timeout_s: int = 180, model: str = "") -> None:
        self._binary = binary
        self._timeout = timeout_s
        self._model = model or os.environ.get("CLAUDE_DISPATCH_MODEL", "")

    async def health(self) -> HealthResult:
        binary = shutil.which(self._binary)
        if not binary:
            return HealthResult(False, f"{self._binary} not in PATH")
        try:
            proc = await asyncio.create_subprocess_exec(
                binary,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            except TimeoutError:
                proc.kill()
                return HealthResult(False, "version check timed out")
            if proc.returncode != 0:
                return HealthResult(False, f"exit={proc.returncode}")
            version = stdout.decode(errors="replace").strip().splitlines()[-1] if stdout else "?"
            return HealthResult(True, f"claude {version}")
        except FileNotFoundError as exc:
            return HealthResult(False, str(exc))

    async def run(self, envelope: DispatchEnvelope) -> BackendResult:
        args: list[str] = [self._binary, "-p"]
        if self._model:
            args += ["--model", self._model]
        # Ask Claude Code for a single JSON object — easy to parse.
        args += ["--output-format", "json"]
        args.append(envelope.prompt)
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "CI": "1"},  # disable interactive hooks
            )
            t0 = time.perf_counter()
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout
                )
            except TimeoutError:
                proc.kill()
                return BackendResult(
                    backend="claude",
                    ok=False,
                    error=f"timeout after {self._timeout}s",
                    model=self._model,
                )
            latency_ms = int((time.perf_counter() - t0) * 1000)
        except FileNotFoundError as exc:
            return BackendResult(backend="claude", ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - last-ditch
            return BackendResult(backend="claude", ok=False, error=repr(exc))

        stdout = stdout_b.decode(errors="replace").strip()
        stderr = stderr_b.decode(errors="replace").strip()

        if proc.returncode != 0:
            return BackendResult(
                backend="claude",
                ok=False,
                error=stderr or f"exit={proc.returncode}",
                latency_ms=latency_ms,
                model=self._model,
            )

        text, model, tok_in, tok_out = _parse_claude_json(stdout, envelope.prompt)
        return BackendResult(
            backend="claude",
            ok=True,
            text=text,
            model=model or self._model,
            tokens_in=tok_in,
            tokens_out=tok_out,
            latency_ms=latency_ms,
        )


def _parse_claude_json(raw: str, prompt: str) -> tuple[str, str, int, int]:
    """Best-effort JSON extraction; falls back to the raw text."""
    raw = (raw or "").strip()
    if not raw:
        return "", "", 0, 0
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        return raw, "", 0, 0
    if isinstance(data, dict):
        text = str(data.get("text") or data.get("content") or data.get("output") or "")
        model = str(data.get("model") or "")
        usage = data.get("usage") or {}
        tok_in = int(usage.get("input_tokens") or usage.get("input") or 0)
        tok_out = int(usage.get("output_tokens") or usage.get("output") or 0)
        return text, model, tok_in, tok_out
    return raw, "", 0, 0
