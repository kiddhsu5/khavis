"""ProviderPlugin abstract base class for the llm-router plugin system.

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

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ProviderPlugin(ABC):
    """Abstract base class that every LLM provider plugin must implement.

    Plugins are auto-discovered from the ``providers/`` directory by
    :class:`core.registry.PluginRegistry`. Each plugin exposes a pool of
    one or more underlying models and provides uniform ``chat``,
    ``check_quota`` and ``health_check`` entry points so the rest of the
    router can stay provider-agnostic.
    """

    #: Human-readable plugin / pool name (e.g. ``"MiniMax-M3"``).
    name: str = "base"

    #: Short string identifier used for routing keys (e.g. ``"MiniMax"``).
    provider_id: str = "base"

    #: Default API endpoint. Plugins may override, but registry can also
    #: supply a custom one via configuration.
    default_endpoint: str = ""

    #: Capability tags advertised by this pool. See ``config/capabilities.yaml``.
    capabilities: List[str] = []

    #: Optional free-form metadata (tier, region, owner, ...).
    metadata: Dict[str, Any] = {}

    def __init__(
        self,
        name: Optional[str] = None,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if name is not None:
            self.name = name
        if endpoint is not None:
            self.default_endpoint = endpoint
        if capabilities is not None:
            self.capabilities = list(capabilities)
        if metadata is not None:
            self.metadata = dict(metadata)
        self.api_key: Optional[str] = api_key
        self.model: Optional[str] = model

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------
    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Send a chat completion request.

        Implementations MUST return a dict shaped like::

            {
                "choices": [
                    {"message": {"content": "...", "role": "assistant"}}
                ],
                "model": "...",
                "usage": {...},
            }
        """

    @abstractmethod
    def check_quota(self) -> Dict[str, Any]:
        """Return remaining/total/tier quota information.

        Implementations return at minimum::

            {"remaining": int|None, "total": int|None, "tier": str|None}

        Use ``None`` for values that are not exposed by the upstream API.
        """

    @abstractmethod
    def list_models(self) -> List[str]:
        """List model identifiers available through this provider."""

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Return a health snapshot ``{"ok": bool, "detail": str}``."""

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    def describes(self) -> Dict[str, Any]:
        """Return a serialisable description of this plugin."""
        return {
            "name": self.name,
            "provider_id": self.provider_id,
            "endpoint": self.default_endpoint,
            "capabilities": list(self.capabilities),
            "metadata": dict(self.metadata),
            "model": self.model,
        }

    def has_capability(self, tag: str) -> bool:
        """Return ``True`` if this plugin advertises ``tag``."""
        return tag in self.capabilities

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{type(self).__name__} name={self.name!r} model={self.model!r}>"
