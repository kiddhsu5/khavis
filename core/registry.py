"""Plugin registry with auto-discovery.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import pkgutil
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from providers.base import ProviderPlugin

_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _expand_env(value: str) -> str:
    """Expand ``${VAR}`` placeholders against ``os.environ``."""

    def repl(match: re.Match[str]) -> str:
        return os.getenv(match.group(1), match.group(0))

    return _PLACEHOLDER_RE.sub(repl, value)


# Files that should never be auto-loaded as plugins.
_SKIP_FILES = {"__init__.py", "base.py"}

# Symbols we never want to treat as plugin entry points.
_SKIP_NAMES = {"ProviderPlugin", "OpenAI", "genai", "requests"}


def _project_root() -> Path:
    """Return the llm-router project root (one level above this file)."""
    return Path(__file__).resolve().parent.parent


class PluginRegistry:
    """Auto-discovers and instantiates every :class:`ProviderPlugin`."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root: Path = Path(project_root) if project_root else _project_root()
        self._plugins: dict[str, ProviderPlugin] = {}
        self._factories: list[Any] = []
        self._errors: list[str] = []

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def discover(self) -> PluginRegistry:
        """Scan the ``providers/`` directory and load every plugin module.

        Returns ``self`` so calls can be chained::

            registry = PluginRegistry().discover()
        """
        providers_dir = self.project_root / "providers"
        if not providers_dir.exists():
            self._errors.append(f"providers dir not found: {providers_dir}")
            return self

        # Ensure ``providers`` is importable as a package.
        parent = str(self.project_root)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        for module_info in pkgutil.iter_modules([str(providers_dir)]):
            name = module_info.name
            if name in _SKIP_FILES or name.startswith("_"):
                continue
            try:
                module = importlib.import_module(f"providers.{name}")
            except Exception as exc:  # pragma: no cover - defensive
                self._errors.append(f"failed to import providers.{name}: {exc!r}")
                continue
            self._harvest(module)
        return self

    def _harvest(self, module: Any) -> None:
        """Pull plugin classes and factory callables out of a module."""
        for attr_name, obj in vars(module).items():
            if attr_name in _SKIP_NAMES or attr_name.startswith("_"):
                continue
            if (
                inspect.isclass(obj)
                and issubclass(obj, ProviderPlugin)
                and obj is not ProviderPlugin
            ):
                if getattr(obj, "_skip_auto_instantiate", False):
                    # Only factories should produce this class.
                    continue
                # Multi-instance plugin: one pool per entry of _plugin_instances.
                instances_cfg = getattr(obj, "_plugin_instances", None)
                if isinstance(instances_cfg, list) and instances_cfg:
                    for kwargs in instances_cfg:
                        if not isinstance(kwargs, dict):
                            self._errors.append(
                                f"{attr_name}._plugin_instances entries must be dicts"
                            )
                            continue
                        try:
                            instance = obj(**kwargs)
                        except Exception as exc:  # pragma: no cover - defensive
                            self._errors.append(
                                f"failed to instantiate {attr_name}(**{kwargs!r}): {exc!r}"
                            )
                            continue
                        self._register(instance)
                else:
                    try:
                        instance = obj()
                    except Exception as exc:  # pragma: no cover - defensive
                        self._errors.append(f"failed to instantiate {attr_name}: {exc!r}")
                        continue
                    self._register(instance)
            elif callable(obj) and hasattr(obj, "provider_id") and not inspect.isclass(obj):
                # e.g. VolcanoPluginFactory — callable that returns list[Plugin].
                self._factories.append(obj)

        # Run any factories we discovered.
        for factory in list(self._factories):
            try:
                produced = factory()
            except Exception as exc:  # pragma: no cover - defensive
                self._errors.append(f"factory {factory!r} failed: {exc!r}")
                continue
            for instance in produced or []:
                if isinstance(instance, ProviderPlugin):
                    self._register(instance)

    def _register(self, plugin: ProviderPlugin) -> None:
        if plugin.name in self._plugins:
            # Preserve first registration but record the conflict.
            self._errors.append(f"duplicate plugin name: {plugin.name}")
            return
        self._plugins[plugin.name] = plugin

    # ------------------------------------------------------------------
    # pools.yaml overrides
    # ------------------------------------------------------------------
    def apply_pools_config(self, pools_yaml_path: Path | str) -> PluginRegistry:
        """Override plugin fields from a ``pools.yaml`` file.

        Each entry in ``pools:`` is matched against an already-discovered
        plugin by its ``name``. Fields supported:

        - ``endpoint``     → ``plugin.default_endpoint``
        - ``model``        → ``plugin.model`` (str or list; first wins)
        - ``env_key``      → ``plugin.api_key`` (taken from ``os.getenv``;
                             if the env var is missing the plugin's existing
                             api_key is left untouched)
        - ``region``/``tier``/``notes`` → ``plugin.metadata`` (merged)
        - ``models``       → if ``model`` is absent and ``models`` is a list,
                             the first element is used as ``plugin.model``

        Unknown pool names are recorded in ``self._errors`` and skipped.
        Returns ``self`` for chaining.
        """
        path = Path(pools_yaml_path)
        if not path.exists():
            self._errors.append(f"pools.yaml not found: {path}")
            return self
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except Exception as exc:  # pragma: no cover - defensive
            self._errors.append(f"failed to parse {path}: {exc!r}")
            return self

        pools = data.get("pools") or []
        for entry in pools:
            name = entry.get("name")
            if not name:
                continue
            plugin = self._plugins.get(name)
            if plugin is None:
                self._errors.append(f"pools.yaml references unknown pool: {name!r}")
                continue

            if "endpoint" in entry:
                plugin.default_endpoint = _expand_env(entry["endpoint"])

            model_value = entry.get("model")
            if model_value is None and isinstance(entry.get("models"), list) and entry["models"]:
                model_value = entry["models"][0]
            if model_value is not None:
                plugin.model = model_value

            env_key = entry.get("env_key")
            if env_key:
                api_key = os.getenv(env_key)
                if api_key:
                    plugin.api_key = api_key

            meta_overlay: dict[str, Any] = {}
            for k in ("region", "tier", "notes"):
                if k in entry:
                    meta_overlay[k] = entry[k]
            if meta_overlay:
                plugin.metadata.update(meta_overlay)

        return self

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------
    def all(self) -> list[ProviderPlugin]:
        return list(self._plugins.values())

    def names(self) -> list[str]:
        return list(self._plugins.keys())

    def get(self, name: str) -> ProviderPlugin | None:
        return self._plugins.get(name)

    def by_capability(self, capability: str) -> list[ProviderPlugin]:
        return [p for p in self._plugins.values() if p.has_capability(capability)]

    def by_provider_id(self, provider_id: str) -> list[ProviderPlugin]:
        return [p for p in self._plugins.values() if p.provider_id == provider_id]

    def __iter__(self) -> Iterator[ProviderPlugin]:
        return iter(self._plugins.values())

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._plugins

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def errors(self) -> list[str]:
        return list(self._errors)

    def summary(self) -> dict[str, Any]:
        return {
            "count": len(self._plugins),
            "names": self.names(),
            "errors": self.errors(),
        }
