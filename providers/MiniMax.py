"""MiniMax-M3 provider plugin.

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

try:  # openai is optional until chat() is actually called
    from openai import OpenAI
except Exception:  # pragma: no cover - import guard
    OpenAI = None  # type: ignore[assignment]


DEFAULT_ENDPOINT = "https://api.MiniMax.chat/v1"
DEFAULT_MODEL = "MiniMax-M3"
ENV_KEY = "MiniMax_API_KEY"


class MiniMaxPlugin(ProviderPlugin):
    """MiniMax-M3 pool served through an OpenAI-compatible HTTP API."""

    provider_id = "MiniMax"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            name="MiniMax-M3",
            endpoint=endpoint or DEFAULT_ENDPOINT,
            api_key=api_key or os.getenv(ENV_KEY),
            model=model or DEFAULT_MODEL,
            capabilities=capabilities or ["中文", "英文", "推理", "工具調用"],
            metadata=metadata or {"region": "global", "tier": "standard"},
        )
        self._client = None

    # ------------------------------------------------------------------
    # Client lazy loader
    # ------------------------------------------------------------------
    def _get_client(self):  # type: ignore[no-untyped-def]
        if OpenAI is None:
            raise RuntimeError("openai package is not installed")
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key or "MISSING_API_KEY",
                base_url=self.default_endpoint,
            )
        return self._client

    # ------------------------------------------------------------------
    # ProviderPlugin interface
    # ------------------------------------------------------------------
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        client = self._get_client()
        model = kwargs.pop("model", self.model)
        response = client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
        return self._normalize(response)

    def check_quota(self) -> dict[str, Any]:
        return {
            "remaining": None,
            "total": None,
            "tier": self.metadata.get("tier"),
            "provider": self.provider_id,
            "note": "Quota endpoint not exposed by MiniMax public API.",
        }

    def list_models(self) -> list[str]:
        return [self.model or DEFAULT_MODEL]

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": bool(self.api_key) and bool(self.default_endpoint),
            "detail": (
                f"endpoint={self.default_endpoint} "
                f"model={self.model} key_present={bool(self.api_key)}"
            ),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _normalize(self, response: Any) -> dict[str, Any]:
        """Coerce an OpenAI SDK response object into a plain dict."""
        try:
            data = response.model_dump()  # type: ignore[attr-defined]
        except AttributeError:
            # Older SDK or stub.
            data = dict(response)
        # Ensure canonical shape even if upstream returns oddly.
        if "choices" not in data:
            data["choices"] = []
        return data
