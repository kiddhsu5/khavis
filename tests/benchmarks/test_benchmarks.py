"""Hot-path benchmarks for khavis.

Each test class measures a different layer of the request lifecycle.
All measurements mock external I/O so the suite runs offline.

Run::

    pytest tests/benchmarks/ -v -s
    # or:
    python scripts/run_benchmarks.py

Why plain ``time.perf_counter`` instead of ``pytest-bbenchmark``:
the project does not depend on ``pytest-benchmark`` (see pyproject.toml
``[project.optional-dependencies.dev]``). Adding it would be welcome
but would require a dependency change. Plain timing keeps these tests
portable.

The numbers we care about:

* ``discovery_ms``        — cold-start cost of auto-loading plugins
* ``capability_load_ms``  — YAML parse + entry construction
* ``selection_ms``        — hot path; called for every request
* ``chat_roundtrip_ms``   — end-to-end with a synthetic mock registry
* ``hot_reload_apply_ms`` — YAML change → entry reload

A reasonable target is **selection_ms < 1 ms** and
**chat_roundtrip_ms < 5 ms** (mocked). If a regression pushes either
above 2x the budget, the test fails.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.capability_router import CapabilityRouter
from core.registry import PluginRegistry
from providers.base import ProviderPlugin

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

ITERS = 200
WARMUP = 10

SELECTION_BUDGET_MS = 2.0
ROUNDTRIP_BUDGET_MS = 10.0
DISCOVERY_BUDGET_MS = 200.0
RELOAD_BUDGET_MS = 50.0


def _time_n(callable_, n: int) -> list[float]:
    """Run ``callable_`` ``n`` times and return per-call durations in ms."""
    durations: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        callable_()
        durations.append((time.perf_counter() - t0) * 1000.0)
    return durations


def _report(name: str, durations: list[float]) -> dict[str, float]:
    """Print and return a summary dict."""
    durations_sorted = sorted(durations)
    p50 = statistics.median(durations_sorted)
    p95 = durations_sorted[int(len(durations_sorted) * 0.95) - 1]
    summary = {
        "min_ms": min(durations_sorted),
        "p50_ms": p50,
        "p95_ms": p95,
        "max_ms": max(durations_sorted),
        "mean_ms": statistics.fmean(durations_sorted),
    }
    print(
        f"\n  [{name}] n={len(durations)} "
        f"min={summary['min_ms']:.3f}ms "
        f"p50={summary['p50_ms']:.3f}ms "
        f"p95={summary['p95_ms']:.3f}ms "
        f"max={summary['max_ms']:.3f}ms"
    )
    return summary


def _make_mock_plugin(name: str, capabilities: list[str]) -> MagicMock:
    """Build a MagicMock that looks like a ProviderPlugin for the router."""
    mock = MagicMock(spec=ProviderPlugin)
    mock.name = name
    mock.capabilities = capabilities
    mock.health_check.return_value = True
    mock.chat.return_value = {
        "content": "OK",
        "model": "mock",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        "raw": {},
    }
    return mock


def _synthetic_registry() -> MagicMock:
    """Return a MagicMock registry with 12 mock plugins wired up."""
    reg = MagicMock(spec=PluginRegistry)
    pool_names = [
        ("MiniMax-M3", ["中文", "推理", "工具調用", "辯論"]),
        ("GLM-5.3", ["中文", "程式碼", "推理", "工具調用", "辯論", "審查", "驗證"]),
        ("Google-Gemini", ["英文", "推理", "工具調用", "辯論", "Embedding", "長文", "審查", "驗證", "速度優先"]),
        ("NVIDIA-Cloud", ["英文", "程式碼", "推理", "工具調用"]),
        ("DeepSeek-V4-Pro", ["中文", "英文", "程式碼", "推理", "工具調用", "辯論", "審查", "驗證"]),
        ("DeepSeek-V4.1-Flash", ["中文", "速度優先"]),
        ("GLM-5.3-Flash", ["中文", "速度優先"]),
        ("OpenRouter-Free", ["英文", "速度優先"]),
        ("OpenAI-API", ["英文", "程式碼", "推理", "工具調用", "辯論", "審查", "驗證", "速度優先"]),
        ("Claude-API", ["英文", "推理", "工具調用", "辯論", "審查", "驗證", "長文"]),
        ("Ollama-Mac", ["中文", "英文", "Embedding", "速度優先"]),
        ("Ollama-Surface", ["中文", "英文", "Embedding", "速度優先"]),
    ]
    plugins = {name: _make_mock_plugin(name, caps) for name, caps in pool_names}

    reg.by_capability.side_effect = lambda cap: [
        p for p in plugins.values() if cap in p.capabilities
    ]
    reg.get.side_effect = lambda name: plugins.get(name)
    reg.names.return_value = [p.name for p in plugins.values()]
    return reg, plugins


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def registry() -> PluginRegistry:
    return PluginRegistry(PROJECT_ROOT).discover()


@pytest.fixture(scope="module")
def loaded_router(registry: PluginRegistry) -> CapabilityRouter:
    return CapabilityRouter(registry).load_capabilities(CONFIG_DIR / "capabilities.yaml")


@pytest.fixture
def synthetic():
    return _synthetic_registry()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
class TestDiscoveryBenchmark:
    """Cold start: how long does it take to load all 12 plugins?

    Includes importlib, class instantiation, and YAML scan.
    """

    def test_discovery_under_budget(self):
        durations: list[float] = []
        # Warmup: skip the first call (imports, etc.)
        PluginRegistry(PROJECT_ROOT).discover()
        for _ in range(20):
            d = _time_n(lambda: PluginRegistry(PROJECT_ROOT).discover(), 1)
            durations.append(d[0])

        summary = _report("discovery_ms", durations)
        assert summary["p95_ms"] < DISCOVERY_BUDGET_MS, (
            f"discovery p95 {summary['p95_ms']:.1f}ms exceeded budget "
            f"{DISCOVERY_BUDGET_MS:.1f}ms"
        )


# ---------------------------------------------------------------------------
# Capability loading
# ---------------------------------------------------------------------------
class TestCapabilityLoadBenchmark:
    """YAML parse + entry construction (one-shot per reload)."""

    def test_capability_load_under_budget(self, registry: PluginRegistry):
        router = CapabilityRouter(registry)
        for _ in range(WARMUP):
            router.load_capabilities(CONFIG_DIR / "capabilities.yaml")
        durations = _time_n(
            lambda: router.load_capabilities(CONFIG_DIR / "capabilities.yaml"), ITERS
        )
        summary = _report("capability_load_ms", durations)
        assert summary["p95_ms"] < RELOAD_BUDGET_MS, (
            f"capability load p95 {summary['p95_ms']:.1f}ms exceeded budget "
            f"{RELOAD_BUDGET_MS:.1f}ms"
        )


# ---------------------------------------------------------------------------
# Selection (the hot path)
# ---------------------------------------------------------------------------
class TestSelectionBenchmark:
    """``CapabilityRouter.select()`` is called for every incoming request.

    Target: < 1 ms p95. This test gives us 2 ms as a generous ceiling.
    """

    @pytest.mark.parametrize(
        "capability",
        ["中文", "英文", "程式碼", "推理", "工具調用", "速度優先", "Embedding", "長文"],
    )
    def test_select_each_capability(self, loaded_router: CapabilityRouter, capability: str):
        for _ in range(WARMUP):
            loaded_router.select(capability)
        durations = _time_n(lambda: loaded_router.select(capability), ITERS)
        summary = _report(f"selection_ms[{capability}]", durations)
        assert summary["p95_ms"] < SELECTION_BUDGET_MS, (
            f"selection p95 for {capability!r} was "
            f"{summary['p95_ms']:.2f}ms (budget {SELECTION_BUDGET_MS:.2f}ms)"
        )

    def test_select_synthetic_low_overhead(self, synthetic):
        """Confirm the router is cheap even with 12 mock candidates per cap."""
        reg, _ = synthetic
        router = CapabilityRouter(reg).load_capabilities(CONFIG_DIR / "capabilities.yaml")
        for _ in range(WARMUP):
            router.select("推理")
        durations = _time_n(lambda: router.select("推理"), ITERS)
        summary = _report("selection_ms[synthetic/推理]", durations)
        assert summary["p95_ms"] < SELECTION_BUDGET_MS, (
            f"synthetic selection p95 {summary['p95_ms']:.2f}ms exceeded budget"
        )


# ---------------------------------------------------------------------------
# End-to-end roundtrip with mocked I/O
# ---------------------------------------------------------------------------
class TestChatRoundtripBenchmark:
    """End-to-end: select + invoke mocked chat() on the chosen plugin.

    Uses a synthetic mock registry so no network I/O is performed.
    Real network latency dominates on top of this; the number we care
    about is the router overhead (select + method dispatch + return).
    """

    def test_roundtrip_under_budget(self, synthetic):
        reg, plugins = synthetic
        router = CapabilityRouter(reg).load_capabilities(CONFIG_DIR / "capabilities.yaml")

        for _ in range(WARMUP):
            plugin = router.select("推理")
            assert plugin is not None
            plugin.chat([{"role": "user", "content": "ping"}])

        def _round():
            plugin = router.select("推理")
            assert plugin is not None
            plugin.chat([{"role": "user", "content": "ping"}])

        durations = _time_n(_round, ITERS)
        summary = _report("chat_roundtrip_ms", durations)
        assert summary["p95_ms"] < ROUNDTRIP_BUDGET_MS, (
            f"roundtrip p95 {summary['p95_ms']:.1f}ms exceeded budget "
            f"{ROUNDTRIP_BUDGET_MS:.1f}ms"
        )

    def test_roundtrip_failover(self, synthetic):
        """Round-robin across 3 candidate pools and call each one."""
        reg, plugins = synthetic
        router = CapabilityRouter(reg).load_capabilities(CONFIG_DIR / "capabilities.yaml")

        for _ in range(WARMUP):
            for cap in ["推理", "程式碼", "英文"]:
                plugin = router.select(cap)
                assert plugin is not None
                plugin.chat([{"role": "user", "content": "ping"}])

        def _round():
            for cap in ["推理", "程式碼", "英文"]:
                plugin = router.select(cap)
                assert plugin is not None
                plugin.chat([{"role": "user", "content": "ping"}])

        durations = _time_n(_round, ITERS)
        summary = _report("chat_roundtrip_ms[3-cap-mix]", durations)
        # 3 caps × the per-call budget.
        assert summary["p95_ms"] < ROUNDTRIP_BUDGET_MS * 3, (
            f"3-cap mix p95 {summary['p95_ms']:.1f}ms exceeded budget"
        )


# ---------------------------------------------------------------------------
# Hot reload (YAML change propagation)
# ---------------------------------------------------------------------------
class TestHotReloadBenchmark:
    """Apply a no-op capability edit and time the reload callback."""

    def test_reload_callback_under_budget(self, registry: PluginRegistry, tmp_path):
        router = CapabilityRouter(registry)
        yaml_path = tmp_path / "capabilities.yaml"
        yaml_path.write_text(
            "capabilities:\n"
            "  - capability: bench\n"
            "    pools: [MiniMax-M3]\n"
            "    weight: 1.0\n",
            encoding="utf-8",
        )

        for _ in range(WARMUP):
            router.load_capabilities(yaml_path)

        durations = _time_n(lambda: router.load_capabilities(yaml_path), ITERS)
        summary = _report("hot_reload_apply_ms", durations)
        assert summary["p95_ms"] < RELOAD_BUDGET_MS, (
            f"hot reload p95 {summary['p95_ms']:.1f}ms exceeded budget "
            f"{RELOAD_BUDGET_MS:.1f}ms"
        )
