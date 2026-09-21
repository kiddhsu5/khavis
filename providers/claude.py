"""Anthropic Claude API provider plugin.

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
    from anthropic import Anthropic
except Exception:  # pragma: no cover - import guard
    Anthropic = None  # type: ignore[assignment]


DEFAULT_ENDPOINT = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
ENV_KEY = "ANTHROPIC_API_KEY"


class AnthropicPlugin(ProviderPlugin):
    """Anthropic Claude API pool (Sonnet 5 / Opus 4.5 / Haiku 4.5)."""

    provider_id = "claude"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            name="Claude-API",
            endpoint=endpoint or DEFAULT_ENDPOINT,
            api_key=api_key or os.getenv(ENV_KEY),
            model=model or DEFAULT_MODEL,
            capabilities=capabilities
            or [
                "英文",
                "推理",
                "工具調用",
                "長文",
            ],
            metadata=metadata or {"region": "us", "tier": "platform"},
        )
        self._client = None

    def _get_client(self):  # type: ignore[no-untyped-def]
        if Anthropic is None:
            raise RuntimeError("anthropic package is not installed")
        if self._client is None:
            self._client = Anthropic(
                api_key=self.api_key or "MISSING_API_KEY",
                base_url=self.default_endpoint,
            )
        return self._client

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        """Send a chat completion request via the Anthropic Messages API.

        Translates the OpenAI-style ``messages`` shape (system + alternating
        user/assistant turns) into Anthropic's ``system`` + ``messages``
        fields, then normalises the response back to the canonical dict
        expected by the router (``{"choices": [...], "model": ..., "usage": ...}``).
        """
        client = self._get_client()
        model = kwargs.pop("model", self.model)

        system_text: str | None = None
        converted: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                # Anthropic takes a single system string; concatenate if multiple.
                system_text = content if system_text is None else f"{system_text}\n\n{content}"
            elif role in ("user", "assistant"):
                converted.append({"role": role, "content": content})
            else:
                # Unknown role — treat as user input to avoid dropping data.
                converted.append({"role": "user", "content": content})

        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": converted,
            "max_tokens": kwargs.pop("max_tokens", 1024),
        }
        if system_text is not None:
            create_kwargs["system"] = system_text
        create_kwargs.update(kwargs)

        response = client.messages.create(**create_kwargs)  # type: ignore[arg-type]
        return self._normalize(response)

    def check_quota(self) -> dict[str, Any]:
        return {
            "remaining": "unknown",
            "total": "unknown",
            "tier": "platform_api",
            "provider": self.provider_id,
            "model": self.model,
            "note": (
                "Anthropic API quota is visible in the Anthropic console at "
                "https://console.anthropic.com/settings/billing."
            ),
        }

    def list_models(self) -> list[str]:
        return [
            "claude-sonnet-5",
            "claude-opus-4-5",
            "claude-haiku-4-5-20251001",
        ]

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
        """Coerce an Anthropic Messages response into the OpenAI-style dict.

        Output shape::

            {
                "choices": [
                    {"message": {"content": "...", "role": "assistant"}}
                ],
                "model": "...",
                "usage": {"prompt_tokens": ..., "completion_tokens": ...},
            }
        """
        # Extract text content from the Anthropic content blocks.
        text_parts: list[str] = []
        try:
            blocks = getattr(response, "content", None) or []
        except Exception:  # pragma: no cover - defensive
            blocks = []

        for block in blocks:
            text = getattr(block, "text", None)
            if text is not None:
                text_parts.append(text)
            elif isinstance(block, dict) and "text" in block:
                text_parts.append(str(block["text"]))

        content = "".join(text_parts)
        model = getattr(response, "model", self.model)

        usage: dict[str, Any] = {}
        try:
            u = getattr(response, "usage", None)
            if u is not None:
                usage = {
                    "prompt_tokens": getattr(u, "input_tokens", None) or 0,
                    "completion_tokens": getattr(u, "output_tokens", None) or 0,
                }
        except Exception:  # pragma: no cover - defensive
            usage = {}

        return {
            "choices": [{"message": {"content": content, "role": "assistant"}}],
            "model": model,
            "usage": usage,
        }
