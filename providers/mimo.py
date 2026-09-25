"""MiMo Code provider plugin (Xiaomi MiMo token plan, Anthropic-compatible).

The MiMo token plan exposes the Anthropic Messages API at
``https://token-plan-cn.xiaomimimo.com/anthropic`` and authenticates with
a bearer token (the same one Claude Code uses via ``ANTHROPIC_AUTH_TOKEN``).
There is no OpenAI-compatible surface, so this plugin speaks Messages
directly over ``requests`` — no extra SDK dependency.

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

import requests

from .base import ProviderPlugin

DEFAULT_ENDPOINT = "https://token-plan-cn.xiaomimimo.com/anthropic"
DEFAULT_MODEL = "mimo-v2.6-pro"
ENV_KEY = "MIMO_AUTH_TOKEN"
ANTHROPIC_VERSION = "2023-06-01"


class MimoCodePlugin(ProviderPlugin):
    """MiMo Code pool served through the Anthropic Messages API."""

    provider_id = "mimo"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        token = api_key or os.getenv(ENV_KEY) or os.getenv("ANTHROPIC_AUTH_TOKEN")
        super().__init__(
            name="MiMo-Code",
            endpoint=endpoint or DEFAULT_ENDPOINT,
            api_key=token,
            model=model or DEFAULT_MODEL,
            capabilities=capabilities
            or [
                "中文",
                "英文",
                "程式碼",
                "推理",
                "工具調用",
                "長文",
            ],
            metadata=metadata or {"region": "cn", "tier": "token_plan"},
        )

    # ------------------------------------------------------------------
    # ProviderPlugin interface
    # ------------------------------------------------------------------
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("MiMo-Code: missing MIMO_AUTH_TOKEN")
        model = kwargs.pop("model", self.model)
        system_text: str | None = None
        converted: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                system_text = content if system_text is None else f"{system_text}\n\n{content}"
            elif role in ("user", "assistant"):
                converted.append({"role": role, "content": content})
            else:
                converted.append({"role": "user", "content": content})

        payload: dict[str, Any] = {
            "model": model,
            "messages": converted,
            "max_tokens": kwargs.pop("max_tokens", 1024),
        }
        if system_text is not None:
            payload["system"] = system_text
        payload.update({k: v for k, v in kwargs.items() if k != "temperature"})

        resp = requests.post(
            f"{self.default_endpoint.rstrip('/')}/v1/messages",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "anthropic-version": ANTHROPIC_VERSION,
                "Content-Type": "application/json",
            },
            timeout=kwargs.pop("timeout", 120),
        )
        resp.raise_for_status()
        return self._normalize(resp.json())

    def check_quota(self) -> dict[str, Any]:
        return {
            "remaining": "unknown",
            "total": "unknown",
            "tier": self.metadata.get("tier"),
            "provider": self.provider_id,
            "model": self.model,
            "note": "MiMo token plan quota is visible in the token-plan console.",
        }

    def list_models(self) -> list[str]:
        return [self.model or DEFAULT_MODEL, "mimo-v2.6-pro"]

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
    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """Coerce an Anthropic Messages response into the OpenAI-style dict.

        MiMo returns ``thinking`` content blocks alongside ``text`` ones;
        only ``text`` is surfaced as the assistant message.
        """
        text_parts: list[str] = []
        for block in data.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text" and "text" in block:
                text_parts.append(str(block["text"]))
            elif getattr(block, "text", None) is not None:
                text_parts.append(str(block.text))

        usage_raw = data.get("usage") or {}
        return {
            "choices": [{"message": {"content": "".join(text_parts), "role": "assistant"}}],
            "model": data.get("model", self.model),
            "usage": {
                "prompt_tokens": usage_raw.get("input_tokens", 0),
                "completion_tokens": usage_raw.get("output_tokens", 0),
            },
        }
