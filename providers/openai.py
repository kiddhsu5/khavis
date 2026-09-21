"""OpenAI Platform API provider plugin.

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
except Exception:  # pragma: no cover - import guard
    OpenAI = None  # type: ignore[assignment]


DEFAULT_ENDPOINT = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-5-mini"
ENV_KEY = "OPENAI_API_KEY"


class OpenAIPlugin(ProviderPlugin):
    """OpenAI Platform API pool (gpt-5 series)."""

    provider_id = "openai"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            name="OpenAI-API",
            endpoint=endpoint or DEFAULT_ENDPOINT,
            api_key=api_key or os.getenv(ENV_KEY),
            model=model or DEFAULT_MODEL,
            capabilities=capabilities
            or [
                "英文",
                "程式碼",
                "推理",
                "工具調用",
                "速度優先",
            ],
            metadata=metadata or {"region": "us", "tier": "platform"},
        )
        self._client = None

    def _get_client(self):  # type: ignore[no-untyped-def]
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
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
        return self._normalize(response)

    def check_quota(self) -> dict[str, Any]:
        return {
            "remaining": "unknown",
            "total": "unknown",
            "tier": "platform_api",
            "provider": self.provider_id,
            "model": self.model,
            "note": (
                "OpenAI Platform API quota is visible in the OpenAI dashboard "
                "at https://platform.openai.com/usage."
            ),
        }

    def list_models(self) -> list[str]:
        return [
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-codex",
            "gpt-5-nano",
        ]

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
            data = response.model_dump()  # type: ignore[attr-defined]
        except AttributeError:
            data = dict(response)
        if "choices" not in data:
            data["choices"] = []
        return data
