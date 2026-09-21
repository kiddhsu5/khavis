"""Volcano Ark (ByteDance) provider plugin.

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

import os
from typing import Any

from .base import ProviderPlugin

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment,misc]


DEFAULT_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3"
ENV_KEY = "BYTEDANCE_API_KEY"


# Each Volcano sub-pool is a fully-fledged ProviderPlugin instance.
# The factory below generates them dynamically so that the registry
# only needs to import :class:`VolcanoPluginFactory`.
SUB_POOLS: dict[str, dict[str, Any]] = {
    "DeepSeek-V4-Pro": {
        "model": "deepseek-v4-pro",
        "capabilities": ["中文", "英文", "推理", "程式碼", "工具調用"],
        "metadata": {"tier": "pro", "family": "deepseek"},
    },
    "DeepSeek-V4.1-Flash": {
        "model": "deepseek-v4.1-flash",
        "capabilities": ["中文", "英文", "速度優先", "推理"],
        "metadata": {"tier": "flash", "family": "deepseek"},
    },
    "GLM-5.3-Flash": {
        "model": "glm-5.3-flash",
        "capabilities": ["中文", "英文", "速度優先"],
        "metadata": {"tier": "flash", "family": "glm"},
    },
}


class VolcanoSubPool(ProviderPlugin):
    """A single Volcano sub-pool bound to a specific model identifier.

    The ``_skip_auto_instantiate`` flag tells ``PluginRegistry`` not to
    call ``VolcanoSubPool()`` with no arguments — instances are produced
    by :class:`VolcanoPluginFactory` instead.
    """

    provider_id = "volcano"
    _skip_auto_instantiate: bool = True

    def __init__(
        self,
        pool_name: str,
        model: str,
        capabilities: list[str],
        metadata: dict[str, Any] | None = None,
        endpoint: str | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            name=pool_name,
            endpoint=endpoint or DEFAULT_ENDPOINT,
            api_key=api_key or os.getenv(ENV_KEY),
            model=model,
            capabilities=capabilities,
            metadata=metadata or {"tier": "standard"},
        )
        self._client = None

    def _get_client(self):
        if OpenAI is None:
            raise RuntimeError("openai package is not installed")
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key or "MISSING_API_KEY",
                base_url=self.default_endpoint,
            )
        return self._client

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        client = self._get_client()
        model = kwargs.pop("model", self.model)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs,
        )
        return self._normalize(response)

    def check_quota(self) -> dict[str, Any]:
        return {
            "remaining": None,
            "total": None,
            "tier": self.metadata.get("tier"),
            "provider": self.provider_id,
            "model": self.model,
            "note": "Volcano Ark quota is visible in the ByteDance console.",
        }

    def list_models(self) -> list[str]:
        return [self.model or ""]

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": bool(self.api_key) and bool(self.default_endpoint),
            "detail": (
                f"endpoint={self.default_endpoint} "
                f"model={self.model} key_present={bool(self.api_key)}"
            ),
        }

    def _normalize(self, response: Any) -> dict[str, Any]:
        try:
            data = response.model_dump()
        except AttributeError:
            data = dict(response)
        if "choices" not in data:
            data["choices"] = []
        return data


class VolcanoPluginFactory:
    """Factory producing one :class:`VolcanoSubPool` per entry of :data:`SUB_POOLS`.

    The registry treats this class like a plugin; calling ``factory()``
    yields the list of sub-pool instances that should be registered.
    """

    name = "volcano"
    provider_id = "volcano"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key

    def __call__(self) -> list[VolcanoSubPool]:
        pools: list[VolcanoSubPool] = []
        for pool_name, cfg in SUB_POOLS.items():
            pools.append(
                VolcanoSubPool(
                    pool_name=pool_name,
                    model=cfg["model"],
                    capabilities=cfg["capabilities"],
                    metadata=cfg.get("metadata", {}),
                    endpoint=self.endpoint,
                    api_key=self.api_key,
                )
            )
        return pools

    # ------------------------------------------------------------------
    # Aggregate helpers — useful for status pages.
    # ------------------------------------------------------------------
    def list_sub_pools(self) -> list[dict[str, Any]]:
        return [
            {"name": name, **{k: v for k, v in cfg.items() if k != "capabilities"}}
            for name, cfg in SUB_POOLS.items()
        ]


__all__ = ["VolcanoSubPool", "VolcanoPluginFactory", "VolcanoFactory", "SUB_POOLS"]


# Module-level factory instance the plugin registry can discover and call.
# ``VolcanoFactory()`` returns the list of three sub-pool plugins.
VolcanoFactory = VolcanoPluginFactory()
