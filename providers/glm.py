"""GLM (ZhipuAI / BigModel) provider plugin.

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
    OpenAI = None  # type: ignore[assignment]


DEFAULT_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-5.3"
ENV_KEY = "ZHIPUAI_API_KEY"


class GLMPlugin(ProviderPlugin):
    """Zhipu GLM pool served through the OpenAI-compatible BigModel API."""

    provider_id = "glm"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            name="GLM-5.3",
            endpoint=endpoint or DEFAULT_ENDPOINT,
            api_key=api_key or os.getenv(ENV_KEY),
            model=model or DEFAULT_MODEL,
            capabilities=capabilities or ["中文", "英文", "推理", "工具調用", "程式碼"],
            metadata=metadata or {"region": "cn", "tier": "pro"},
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
            "remaining": None,
            "total": None,
            "tier": self.metadata.get("tier"),
            "provider": self.provider_id,
            "note": "BigModel quota endpoint requires authenticated account probe.",
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

    def _normalize(self, response: Any) -> dict[str, Any]:
        try:
            data = response.model_dump()  # type: ignore[attr-defined]
        except AttributeError:
            data = dict(response)
        if "choices" not in data:
            data["choices"] = []
        return data
