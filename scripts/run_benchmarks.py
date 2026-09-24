#!/usr/bin/env python3
"""Run khavis benchmarks and print a one-shot summary.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Run from the project root::

    python scripts/run_benchmarks.py

Exits 0 if every benchmark passes its budget; 1 otherwise.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.capability_router import CapabilityRouter  # noqa: E402
from core.registry import PluginRegistry  # noqa: E402
from providers.base import ProviderPlugin  # noqa: E402

CONFIG_DIR = PROJECT_ROOT / "config"

ITERS = 200
WARMUP = 10

BUDGETS = {
    "discovery_ms": 200.0,
    "capability_load_ms": 50.0,
    "selection_ms": 2.0,
    "chat_roundtrip_ms": 10.0,
}


def _time_n(fn, n: int) -> list[float]:
    durations: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        durations.append((time.perf_counter() - t0) * 1000.0)
    return durations


def _report(name: str, durations: list[float]) -> dict[str, float]:
    s = sorted(durations)
    summary = {
        "min_ms": min(s),
        "p50_ms": statistics.median(s),
        "p95_ms": s[int(len(s) * 0.95) - 1],
        "max_ms": max(s),
        "mean_ms": statistics.fmean(s),
    }
    print(
        f"  [{name:>28}]  n={len(s):>4}  "
        f"min={summary['min_ms']:7.3f}  "
        f"p50={summary['p50_ms']:7.3f}  "
        f"p95={summary['p95_ms']:7.3f}  "
        f"max={summary['max_ms']:7.3f}  "
        f"mean={summary['mean_ms']:7.3f} ms"
    )
    return summary


def _make_mock_plugin(name: str, capabilities: list[str]) -> MagicMock:
    mock = MagicMock(spec=ProviderPlugin)
    mock.name = name
    mock.capabilities = capabilities
    mock.health_check.return_value = True
    mock.chat.return_value = {
        "content": "OK", "model": "mock",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "raw": {},
    }
    return mock


def _synthetic_registry() -> tuple[MagicMock, dict[str, MagicMock]]:
    reg = MagicMock(spec=PluginRegistry)
    pool_specs = [
        ("MiniMax-M3", ["中文", "推理", "工具調用", "辯論"]),
        ("GLM-5.3", ["中文", "程式碼", "推理", "工具調用", "辯論", "審查", "驗證"]),
        ("Google-Gemini", ["英文", "推理", "工具調用", "辯論", "Embedding", "長文",
                           "審查", "驗證", "速度優先"]),
        ("NVIDIA-Cloud", ["英文", "程式碼", "推理", "工具調用"]),
        ("DeepSeek-V4-Pro", ["中文", "英文", "程式碼", "推理", "工具調用", "辯論",
                             "審查", "驗證"]),
        ("DeepSeek-V4.1-Flash", ["中文", "速度優先"]),
        ("GLM-5.3-Flash", ["中文", "速度優先"]),
        ("OpenRouter-Free", ["英文", "速度優先"]),
        ("OpenAI-API", ["英文", "程式碼", "推理", "工具調用", "辯論", "審查",
                        "驗證", "速度優先"]),
        ("Claude-API", ["英文", "推理", "工具調用", "辯論", "審查", "驗證", "長文"]),
        ("Ollama-Mac", ["中文", "英文", "Embedding", "速度優先"]),
        ("Ollama-Surface", ["中文", "英文", "Embedding", "速度優先"]),
    ]
    plugins = {name: _make_mock_plugin(name, caps) for name, caps in pool_specs}
    reg.by_capability.side_effect = lambda cap: [
        p for p in plugins.values() if cap in p.capabilities
    ]
    reg.get.side_effect = lambda name: plugins.get(name)
    return reg, plugins


def main() -> int:
    print(f"khavis benchmark suite \u2014 {ITERS} iterations each\n")

    print("--- cold start ---")
    PluginRegistry(PROJECT_ROOT).discover()  # warmup
    durations: list[float] = []
    for _ in range(20):
        durations.extend(_time_n(lambda: PluginRegistry(PROJECT_ROOT).discover(), 1))
    d = _report("discovery_ms", durations)
    registry = PluginRegistry(PROJECT_ROOT).discover()

    print("\n--- config load ---")
    router = CapabilityRouter(registry)
    for _ in range(WARMUP):
        router.load_capabilities(CONFIG_DIR / "capabilities.yaml")
    cap_durations = _time_n(
        lambda: router.load_capabilities(CONFIG_DIR / "capabilities.yaml"), ITERS
    )
    c = _report("capability_load_ms", cap_durations)

    # Selection on the real registry
    print("\n--- selection (per capability, real registry) ---")
    caps = ["中文", "英文", "程式碼", "推理", "工具調用", "速度優先", "Embedding", "長文"]
    sel_durations: list[float] = []
    for cap in caps:
        for _ in range(WARMUP):
            router.select(cap)
        durations = _time_n(lambda c=cap: router.select(c), ITERS)
        d_sel = _report(f"selection_ms[{cap}]", durations)
        sel_durations.append(d_sel["p95_ms"])

    # Roundtrip with synthetic registry (mocked I/O)
    print("\n--- end-to-end (mocked I/O) ---")
    reg, _ = _synthetic_registry()
    synth_router = CapabilityRouter(reg).load_capabilities(CONFIG_DIR / "capabilities.yaml")

    def _round():
        plugin = synth_router.select("推理")
        assert plugin is not None
        plugin.chat([{"role": "user", "content": "ping"}])

    for _ in range(WARMUP):
        _round()
    r = _report("chat_roundtrip_ms", _time_n(_round, ITERS))

    # Final pass/fail
    print("\n--- budgets ---")
    failed = False
    checks = [
        ("discovery_ms", d["p95_ms"], BUDGETS["discovery_ms"]),
        ("capability_load_ms", c["p95_ms"], BUDGETS["capability_load_ms"]),
        ("chat_roundtrip_ms", r["p95_ms"], BUDGETS["chat_roundtrip_ms"]),
    ]
    for name, actual, budget in checks:
        ok = actual < budget
        if not ok:
            failed = True
        flag = "OK  " if ok else "FAIL"
        print(f"  [{flag}] {name:>22}  p95={actual:7.3f} ms  budget={budget:7.1f} ms")

    sel_max = max(sel_durations) if sel_durations else 0.0
    sel_budget = BUDGETS["selection_ms"] * 3  # per-capability, allow 3x noise headroom
    ok = sel_max < sel_budget
    if not ok:
        failed = True
    flag = "OK  " if ok else "FAIL"
    print(
        f"  [{flag}] {'selection_ms[max cap]':>22}  p95={sel_max:7.3f} ms  "
        f"budget={sel_budget:7.1f} ms"
    )

    print()
    if failed:
        print("one or more benchmarks exceeded budget")
        return 1
    print("all benchmarks within budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
