"""Google Gemini provider plugin.

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
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None  # type: ignore[assignment,misc]


DEFAULT_MODELS: list[str] = ["gemini-2.5-flash", "gemini-2.5-pro"]
ENV_KEY = "GOOGLE_API_KEY"


class GeminiPlugin(ProviderPlugin):
    """Google Gemini pool.

    Supports multiple model variants (``gemini-2.5-flash``,
    ``gemini-2.5-pro``). The first entry of ``models`` is treated as the
    default unless overridden at construction time.
    """

    provider_id = "gemini"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        models: list[str] | None = None,
    ) -> None:
        self._models: list[str] = list(models) if models else list(DEFAULT_MODELS)
        super().__init__(
            name="Google-Gemini",
            endpoint=endpoint or "https://generativelanguage.googleapis.com",
            api_key=api_key or os.getenv(ENV_KEY),
            model=model or self._models[0],
            capabilities=capabilities
            or [
                "英文",
                "推理",
                "工具調用",
                "速度優先",
                "Embedding",
            ],
            metadata=metadata or {"region": "global", "tier": "pro"},
        )

    # ------------------------------------------------------------------
    # ProviderPlugin interface
    # ------------------------------------------------------------------
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        if genai is None:
            raise RuntimeError("google-generativeai package is not installed")
        if not self.api_key:
            raise RuntimeError("GOOGLE_API_KEY not configured")

        genai.configure(api_key=self.api_key)
        target_model = kwargs.pop("model", self.model)
        gen_model = genai.GenerativeModel(target_model)

        # Convert OpenAI-style messages to Gemini's contents format.
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        history = [
            {"role": m["role"], "parts": [m["content"]]}
            for m in messages
            if m.get("role") in ("user", "model")
        ]
        prompt = history.pop()["parts"][0] if history else ""
        full_prompt = ("\n\n".join(system_parts) + "\n\n" + prompt) if system_parts else prompt

        response = gen_model.generate_content(full_prompt, **kwargs)
        text = getattr(response, "text", "") or ""

        return {
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "model": target_model,
            "usage": {},
        }

    def check_quota(self) -> dict[str, Any]:
        return {
            "remaining": None,
            "total": None,
            "tier": self.metadata.get("tier"),
            "provider": self.provider_id,
            "note": "Gemini quota is visible via the Google AI Studio console.",
        }

    def list_models(self) -> list[str]:
        return list(self._models)

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": bool(self.api_key),
            "detail": (
                f"endpoint={self.default_endpoint} "
                f"models={self._models} key_present={bool(self.api_key)}"
            ),
        }
