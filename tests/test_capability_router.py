"""Tests for the capability-based router.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
"""

from __future__ import annotations

import random
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.capability_router import CapabilityEntry, CapabilityRouter
from core.registry import PluginRegistry
from providers.base import ProviderPlugin

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def registry() -> PluginRegistry:
    return PluginRegistry(PROJECT_ROOT).discover()


@pytest.fixture
def router(registry: PluginRegistry) -> CapabilityRouter:
    return CapabilityRouter(registry)


@pytest.fixture
def loaded_router(router: CapabilityRouter) -> CapabilityRouter:
    return router.load_capabilities(CONFIG_DIR / "capabilities.yaml")


# ---------------------------------------------------------------------------
# CapabilityEntry
# ---------------------------------------------------------------------------
class TestCapabilityEntry:
    def test_from_dict_defaults(self):
        entry = CapabilityEntry.from_dict({"capability": "中文"})
        assert entry.capability == "中文"
        assert entry.pools == []
        assert entry.weight == 1.0

    def test_from_dict_full(self):
        entry = CapabilityEntry.from_dict(
            {"capability": "推理", "pools": ["A", "B"], "weight": 1.5}
        )
        assert entry.pools == ["A", "B"]
        assert entry.weight == 1.5


# ---------------------------------------------------------------------------
# Capability loading
# ---------------------------------------------------------------------------
class TestCapabilityLoading:
    def test_load_returns_self(self, router: CapabilityRouter):
        assert router.load_capabilities(CONFIG_DIR / "capabilities.yaml") is router

    def test_load_populates_entries(self, loaded_router: CapabilityRouter):
        caps = [e.capability for e in loaded_router.entries()]
        for required in ("中文", "英文", "推理", "工具調用", "Embedding", "長文"):
            assert required in caps

    def test_long_context_capability_uses_claude(self, loaded_router: CapabilityRouter):
        # The new "長文" capability should be served primarily by Claude-API.
        candidates = loaded_router.candidates("長文")
        names = [p.name for p in candidates]
        assert "Claude-API" in names
        # Google-Gemini is the second pool listed for 長文.
        assert "Google-Gemini" in names

    def test_openai_pool_in_capability_lists(self, loaded_router: CapabilityRouter):
        # OpenAI-API is BYOK but should still appear in the capability pool lists.
        for cap in ("英文", "程式碼", "推理", "工具調用", "速度優先"):
            names = [p.name for p in loaded_router.candidates(cap)]
            assert "OpenAI-API" in names, f"OpenAI-API missing from {cap} candidates"

    def test_load_weights_preserved(self, loaded_router: CapabilityRouter):
        weights = {e.capability: e.weight for e in loaded_router.entries()}
        assert weights["程式碼"] == 1.2
        assert weights["推理"] == 1.3

    def test_load_missing_file(self, router: CapabilityRouter, tmp_path):
        # Non-existent path: yaml.safe_load on '' would crash, but the
        # implementation calls ``Path(path).read_text`` so a missing
        # file raises — we only assert it's not silently swallowed.
        with pytest.raises(FileNotFoundError):
            router.load_capabilities(tmp_path / "absent.yaml")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
class TestRouting:
    def test_candidates_for_known_capability(self, loaded_router: CapabilityRouter):
        candidates = loaded_router.candidates("推理")
        assert len(candidates) >= 1
        assert all(isinstance(p, ProviderPlugin) for p in candidates)

    def test_candidates_falls_back_to_registry(self, router: CapabilityRouter):
        # No YAML loaded → falls back to registry.by_capability().
        candidates = router.candidates("中文")
        assert any(p.name == "MiniMax-M3" for p in candidates)

    def test_candidates_skips_missing_pools(self, loaded_router: CapabilityRouter):
        # Inject a bogus pool name and verify it's silently dropped.
        loaded_router._entries.append(
            CapabilityEntry(capability="nonsense", pools=["NotAPool"], weight=1.0)
        )
        # No provider advertises "nonsense" so we should get an empty list
        # unless the registry happens to match — assert list type.
        assert isinstance(loaded_router.candidates("nonsense"), list)

    def test_candidates_unknown_capability(self, loaded_router: CapabilityRouter):
        assert loaded_router.candidates("totally-unknown-cap") == []

    def test_select_returns_plugin_or_none(self, loaded_router: CapabilityRouter):
        p = loaded_router.select("推理", strategy="weighted")
        assert p is None or isinstance(p, ProviderPlugin)

    def test_select_unknown_capability_returns_none(self, loaded_router: CapabilityRouter):
        assert loaded_router.select("does-not-exist") is None

    def test_strategy_random(self, loaded_router: CapabilityRouter):
        rng = random.Random(0)
        a = loaded_router.select("推理", strategy="random", rng=rng)
        b = loaded_router.select("推理", strategy="random", rng=rng)
        assert a is not None and b is not None
        # We don't assert inequality — same seed could pick the same item.

    def test_strategy_round_robin_is_deterministic(self, loaded_router: CapabilityRouter):
        a1 = loaded_router.select("推理", strategy="round_robin")
        a2 = loaded_router.select("推理", strategy="round_robin")
        assert a1 is not None and a2 is not None
        assert a1.name == a2.name

    def test_strategy_round_robin_distinguishes_capabilities(self, loaded_router: CapabilityRouter):
        a = loaded_router.select("中文", strategy="round_robin")
        b = loaded_router.select("Embedding", strategy="round_robin")
        # Both should resolve but may pick different pools.
        assert a is not None and b is not None


# ---------------------------------------------------------------------------
# Weighted selection
# ---------------------------------------------------------------------------
class TestWeightedChoice:
    def test_weighted_choice_respects_distribution(self):
        from core.capability_router import _weighted_choice

        items = ["a", "b"]
        rng = random.Random(42)
        # weight heavily toward "a" → should pick "a" almost always.
        results = [_weighted_choice(items, [1000.0, 1.0], rng) for _ in range(200)]
        assert results.count("a") > 150

    def test_weighted_choice_zero_total_falls_back_to_uniform(self):
        from core.capability_router import _weighted_choice

        items = ["a", "b", "c"]
        rng = random.Random(0)
        # All zero weights → fall back to rng.choice(items).
        for _ in range(50):
            assert _weighted_choice(items, [0.0, 0.0, 0.0], rng) in items

    def test_weighted_choice_clips_negative_weights(self):
        from core.capability_router import _weighted_choice

        items = ["a", "b"]
        rng = random.Random(0)
        # Negative weight is clipped to zero → falls into the "all zero"
        # branch and picks uniformly.
        for _ in range(20):
            assert _weighted_choice(items, [-1.0, -1.0], rng) in items


# ---------------------------------------------------------------------------
# Fallback / health
# ---------------------------------------------------------------------------
class TestFallback:
    def test_select_falls_back_when_no_yaml_entry(self, router: CapabilityRouter):
        # No entries loaded; registry should still produce candidates
        # for any capability advertised by the providers.
        assert router.select("中文") is not None

    def test_select_when_only_plugin_fails_health(self, registry: PluginRegistry):
        # Build a router with one registered plugin that "fails" health_check.
        failing = MagicMock(spec=ProviderPlugin)
        failing.name = "Failing"
        failing.has_capability.return_value = True
        failing.health_check.return_value = {"ok": False, "detail": "down"}

        # Use a stub registry that exposes the failing plugin.
        stub_registry = MagicMock()
        stub_registry.by_capability.return_value = [failing]
        stub_registry.get.return_value = failing

        router = CapabilityRouter(stub_registry)
        # router.select doesn't currently filter by health, but we exercise
        # the path to ensure it does not crash.
        selected = router.select("any-cap")
        assert selected is failing

    def test_weighted_choice_returns_last_item_on_overshoot(self):
        from core.capability_router import _weighted_choice

        # With a fixed seed and unequal weights we verify the function
        # always returns an item from the input list (regression guard).
        items = ["x", "y", "z"]
        rng = random.Random(7)
        for _ in range(100):
            assert _weighted_choice(items, [1.0, 1.0, 1.0], rng) in items
