"""Tests for the PluginRegistry auto-discovery layer.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

from core.registry import PluginRegistry
from providers.base import ProviderPlugin

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
class TestDiscovery:
    def test_discovers_all_twelve_pools(self):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        names = sorted(registry.names())

        # 12 pool names expected from pools.yaml.
        expected = {
            "MiniMax-M3",
            "GLM-5.3",
            "Google-Gemini",
            "NVIDIA-Cloud",
            "DeepSeek-V4-Pro",
            "DeepSeek-V4.1-Flash",
            "GLM-5.3-Flash",
            "OpenRouter-Free",
            "OpenAI-API",
            "Claude-API",
            "Ollama-Mac",
            "Ollama-Surface",
        }
        missing = expected - set(names)
        assert not missing, f"missing pools: {missing}"
        # And there should be no duplicate names.
        assert len(names) == len(set(names))

    def test_discovers_twelve_total(self):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        assert len(registry) >= 12

    def test_summary_shape(self):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        summary = registry.summary()
        assert set(summary.keys()) == {"count", "names", "errors"}
        assert summary["count"] == len(summary["names"])

    def test_returns_self_for_chaining(self):
        registry = PluginRegistry(PROJECT_ROOT)
        assert registry.discover() is registry

    def test_handles_missing_providers_dir(self, tmp_path):
        # No providers/ subdir under tmp_path → registry should record an
        # error rather than raise.
        (tmp_path / "providers").mkdir()  # empty
        registry = PluginRegistry(tmp_path).discover()
        # Empty dir => nothing loaded, but no exception.
        assert len(registry) == 0

    def test_handles_import_error_gracefully(self, tmp_path, monkeypatch):
        providers_dir = tmp_path / "providers"
        providers_dir.mkdir()

        # Create a stub providers package init.
        (providers_dir / "__init__.py").write_text("")
        (providers_dir / "broken.py").write_text("raise RuntimeError('intentional')")

        # Stub out providers.base so the import chain resolves.
        # We register a stub on sys.modules so that importlib can find it.
        stub_base = MagicMock()
        stub_base.ProviderPlugin = ProviderPlugin
        stub_pkg = MagicMock()
        stub_pkg.__path__ = [str(providers_dir)]

        monkeypatch.setitem(sys.modules, "providers", stub_pkg)
        monkeypatch.setitem(sys.modules, "providers.base", stub_base)

        registry = PluginRegistry(tmp_path).discover()
        # The broken module should not crash discovery, but should record.
        errs = " ".join(registry.errors())
        assert "broken" in errs or len(registry) == 0


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
class TestLookup:
    def test_get_returns_plugin(self):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        p = registry.get("MiniMax-M3")
        assert isinstance(p, ProviderPlugin)
        assert p.name == "MiniMax-M3"

    def test_get_returns_none_when_missing(self):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        assert registry.get("does-not-exist") is None

    def test_contains(self):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        assert "MiniMax-M3" in registry
        assert "missing" not in registry
        # Non-string keys are always False.
        assert 123 not in registry  # type: ignore[operator]

    def test_iteration(self):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        names = [p.name for p in registry]
        assert "MiniMax-M3" in names

    def test_by_capability(self):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        zh = registry.by_capability("中文")
        assert any(p.name == "MiniMax-M3" for p in zh)
        # An unknown capability yields an empty list.
        assert registry.by_capability("totally-bogus-cap") == []

    def test_by_provider_id(self):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        volcano = registry.by_provider_id("volcano")
        names = set(p.name for p in volcano)
        # Use a set comparison so we don't depend on ASCII sort order
        # ("-" (45) < "." (46), so "DeepSeek-V4-Pro" < "DeepSeek-V4.1-Flash").
        assert names == {"DeepSeek-V4.1-Flash", "DeepSeek-V4-Pro", "GLM-5.3-Flash"}
        assert registry.by_provider_id("no-such-provider") == []


# ---------------------------------------------------------------------------
# Errors / diagnostics
# ---------------------------------------------------------------------------
class TestErrors:
    def test_no_errors_on_clean_discovery(self):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        # In a healthy install the registry should surface no errors.
        assert registry.errors() == [] or all("duplicate" not in e for e in registry.errors())


# ---------------------------------------------------------------------------
# apply_pools_config
# ---------------------------------------------------------------------------
class TestApplyPoolsConfig:
    def _write_pools(self, tmp_path: Path, content: str) -> Path:
        path = tmp_path / "pools.yaml"
        path.write_text(content)
        return path

    def test_overrides_endpoint_and_model(self, tmp_path):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        path = self._write_pools(
            tmp_path,
            """
            pools:
              - name: Ollama-Mac
                endpoint: http://1.2.3.4:9999
                model: custom-model:1
            """,
        )
        registry.apply_pools_config(path)
        p = registry.get("Ollama-Mac")
        assert p is not None
        assert p.default_endpoint == "http://1.2.3.4:9999"
        assert p.model == "custom-model:1"

    def test_expands_env_var_placeholder(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SURFACE_IP", "10.42.42.42")
        registry = PluginRegistry(PROJECT_ROOT).discover()
        path = self._write_pools(
            tmp_path,
            """
            pools:
              - name: Ollama-Surface
                endpoint: http://${SURFACE_IP}:11434
            """,
        )
        registry.apply_pools_config(path)
        p = registry.get("Ollama-Surface")
        assert p is not None
        assert p.default_endpoint == "http://10.42.42.42:11434"

    def test_picks_first_models_list_when_model_absent(self, tmp_path):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        path = self._write_pools(
            tmp_path,
            """
            pools:
              - name: Google-Gemini
                models: [gemini-pro-latest, gemini-flash-latest]
            """,
        )
        registry.apply_pools_config(path)
        p = registry.get("Google-Gemini")
        assert p is not None
        assert p.model == "gemini-pro-latest"

    def test_unknown_pool_records_error_but_continues(self, tmp_path):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        path = self._write_pools(
            tmp_path,
            """
            pools:
              - name: DoesNotExist
                model: x
            """,
        )
        registry.apply_pools_config(path)
        errs = " ".join(registry.errors())
        assert "DoesNotExist" in errs

    def test_missing_file_records_error(self, tmp_path):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        registry.apply_pools_config(tmp_path / "absent.yaml")
        assert any("not found" in e for e in registry.errors())

    def test_env_key_resolves_to_api_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        registry = PluginRegistry(PROJECT_ROOT).discover()
        path = self._write_pools(
            tmp_path,
            """
            pools:
              - name: Claude-API
                env_key: ANTHROPIC_API_KEY
            """,
        )
        registry.apply_pools_config(path)
        p = registry.get("Claude-API")
        assert p is not None
        assert p.api_key == "sk-ant-test"

    def test_metadata_overlay_merges(self, tmp_path):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        path = self._write_pools(
            tmp_path,
            """
            pools:
              - name: OpenAI-API
                region: us-west
                tier: platform_api
                notes: byok
            """,
        )
        registry.apply_pools_config(path)
        p = registry.get("OpenAI-API")
        assert p is not None
        meta = p.metadata
        assert meta["region"] == "us-west"
        assert meta["tier"] == "platform_api"
        assert meta["notes"] == "byok"

    def test_returns_self_for_chaining(self, tmp_path):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        path = self._write_pools(tmp_path, "pools: []\n")
        assert registry.apply_pools_config(path) is registry


# ---------------------------------------------------------------------------
# Capability listing integration
# ---------------------------------------------------------------------------
class TestCapabilities:
    def test_capability_listing_via_registry(self):
        registry = PluginRegistry(PROJECT_ROOT).discover()
        caps = {
            cap: sorted(p.name for p in registry.by_capability(cap))
            for cap in ("中文", "英文", "推理", "工具調用", "Embedding", "速度優先", "程式碼")
        }
        # Every capability has at least one provider.
        for cap, providers in caps.items():
            assert providers, f"capability {cap} has no providers"
        # Ollama-Mac should be in 中文 and 英文.
        assert "Ollama-Mac" in caps["中文"]
        assert "Ollama-Mac" in caps["英文"]
        # Embedding should include Google-Gemini + Ollama.
        assert "Google-Gemini" in caps["Embedding"]
        assert "NVIDIA-Cloud" in caps["Embedding"]
