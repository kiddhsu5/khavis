"""Capability-based router.

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

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from providers.base import ProviderPlugin

from .registry import PluginRegistry


@dataclass
class CapabilityEntry:
    """One YAML entry mapping a capability tag to candidate pools + weight."""

    capability: str
    pools: List[str] = field(default_factory=list)
    weight: float = 1.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityEntry":
        return cls(
            capability=data["capability"],
            pools=list(data.get("pools", [])),
            weight=float(data.get("weight", 1.0)),
        )


class CapabilityRouter:
    """Routes requests by capability tag, not by hard-coded pool name."""

    def __init__(self, registry: PluginRegistry) -> None:
        self.registry = registry
        self._entries: List[CapabilityEntry] = []

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def load_capabilities(self, path: Path) -> "CapabilityRouter":
        """Load capability → pools mappings from a YAML file."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        entries_raw = data.get("capabilities", [])
        self._entries = [CapabilityEntry.from_dict(item) for item in entries_raw]
        return self

    def entries(self) -> List[CapabilityEntry]:
        return list(self._entries)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def candidates(self, capability: str) -> List[ProviderPlugin]:
        """Return registry plugins that advertise ``capability``."""
        # First, look for an explicit YAML entry; otherwise fall back to the
        # registry's own capability tags so the system degrades gracefully
        # when the YAML is incomplete.
        explicit = next(
            (e for e in self._entries if e.capability == capability), None
        )
        plugins: List[ProviderPlugin] = []
        if explicit and explicit.pools:
            for name in explicit.pools:
                plugin = self.registry.get(name)
                if plugin is not None:
                    plugins.append(plugin)
        if not plugins:
            plugins = self.registry.by_capability(capability)
        return plugins

    def select(
        self,
        capability: str,
        *,
        strategy: str = "weighted",
        rng: Optional[random.Random] = None,
    ) -> Optional[ProviderPlugin]:
        """Pick a single plugin for the given capability.

        ``strategy`` can be ``"weighted"`` (default), ``"round_robin"`` or
        ``"random"``.
        """
        candidates = self.candidates(capability)
        if not candidates:
            return None
        if strategy == "random":
            return (rng or random).choice(candidates)
        if strategy == "round_robin":
            # Stateless round-robin: pick based on hash(capability).
            idx = abs(hash(capability)) % len(candidates)
            return candidates[idx]
        # Default: weighted random using the YAML weight when present.
        explicit = next(
            (e for e in self._entries if e.capability == capability), None
        )
        weights: List[float] = []
        for plugin in candidates:
            if explicit:
                # YAML weight applies if the pool appears in the YAML list.
                if plugin.name in explicit.pools:
                    weights.append(explicit.weight)
                else:
                    weights.append(1.0)
            else:
                weights.append(1.0)
        return _weighted_choice(candidates, weights, rng or random)


def _weighted_choice(
    items: List[Any], weights: Iterable[float], rng: random.Random
) -> Any:
    items = list(items)
    weights = [max(0.0, float(w)) for w in weights]
    total = sum(weights)
    if total <= 0:
        return rng.choice(items)
    pick = rng.uniform(0, total)
    upto = 0.0
    for item, weight in zip(items, weights):
        upto += weight
        if pick <= upto:
            return item
    return items[-1]


__all__ = ["CapabilityEntry", "CapabilityRouter"]
