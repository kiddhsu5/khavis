"""Ollama local provider plugin (parameterised for Mac / Surface hosts).

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
from typing import Any, Dict, List, Optional

import requests

from .base import ProviderPlugin


DEFAULT_MODEL = "gemma4:e2b"
SURFACE_IP_ENV = "SURFACE_IP"
_OPENAI_COMPAT_PREFIX = "ollama/"


def _normalize_model(model: Optional[str]) -> Optional[str]:
    """Strip the OpenAI-compat ``ollama/`` prefix used on ``/v1/chat/completions``.

    The native ``/api/chat`` endpoint expects a bare model tag like
    ``gemma4:e2b`` and rejects the ``ollama/`` prefix with HTTP 404.
    Older llm-router configs and the default below historically shipped
    with the prefix; we tolerate it on the way in so users upgrading
    do not need to edit their pools.yaml.
    """
    if not model:
        return model
    if model.startswith(_OPENAI_COMPAT_PREFIX):
        return model[len(_OPENAI_COMPAT_PREFIX):]
    return model


class OllamaPlugin(ProviderPlugin):
    """Ollama HTTP pool.

    A single class is used for both the Mac (``localhost:11434``) and the
    Surface (``$SURFACE_IP:11434``) hosts. The pool name and base URL are
    configurable so the registry can instantiate multiple pools from one
    plugin class.
    """

    provider_id = "ollama"

    # The registry iterates this list and instantiates one pool per entry.
    # Each dict is passed as kwargs to ``OllamaPlugin.__init__``.
    _plugin_instances = [
        {
            "name": "Ollama-Mac",
            "base_url": "http://localhost:11434",
        },
        {
            "name": "Ollama-Surface",
            "base_url": "http://${SURFACE_IP}:11434",
            "metadata": {"region": "remote", "tier": "self-hosted"},
        },
    ]

    def __init__(
        self,
        name: str = "Ollama-Mac",
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if base_url is None:
            if name.lower().startswith("ollama-surface"):
                surface_ip = os.getenv(SURFACE_IP_ENV)
                base_url = (
                    f"http://{surface_ip}:11434"
                    if surface_ip
                    else "http://surface.local:11434"
                )
            else:
                base_url = "http://localhost:11434"
        # Expand ${SURFACE_IP} placeholders sourced from pools.yaml.
        if "${SURFACE_IP}" in base_url:
            surface_ip = os.getenv(SURFACE_IP_ENV, "surface.local")
            base_url = base_url.replace("${SURFACE_IP}", surface_ip)
        super().__init__(
            name=name,
            endpoint=base_url,
            api_key=None,  # Ollama is local; no key required.
            model=model or DEFAULT_MODEL,
            capabilities=capabilities or ["英文", "中文", "Embedding", "速度優先"],
            metadata=metadata or {"region": "local", "tier": "self-hosted"},
        )

    # ------------------------------------------------------------------
    # ProviderPlugin interface
    # ------------------------------------------------------------------
    def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> Dict[str, Any]:
        url = f"{self.default_endpoint.rstrip('/')}/api/chat"
        payload: Dict[str, Any] = {
            "model": _normalize_model(self.model),
            "messages": messages,
            "stream": False,
        }
        payload.update(kwargs)
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data: Dict[str, Any] = resp.json()
        # Normalise to OpenAI-style response.
        content = ""
        if isinstance(data, dict):
            message = data.get("message") or {}
            content = message.get("content", "") if isinstance(message, dict) else ""
        return {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "model": data.get("model", self.model) if isinstance(data, dict) else self.model,
            "usage": {},
        }

    def check_quota(self) -> Dict[str, Any]:
        # Ollama is local, so quota is effectively unbounded.
        return {
            "remaining": None,
            "total": None,
            "tier": "local",
            "provider": self.provider_id,
            "note": "Local Ollama has no external quota.",
        }

    def list_models(self) -> List[str]:
        url = f"{self.default_endpoint.rstrip('/')}/api/tags"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []

    def health_check(self) -> Dict[str, Any]:
        try:
            resp = requests.get(self.default_endpoint, timeout=5)
            ok = resp.status_code < 500
            detail = f"endpoint={self.default_endpoint} status={resp.status_code}"
        except Exception as exc:  # pragma: no cover - network failure
            ok = False
            detail = f"endpoint={self.default_endpoint} error={exc!r}"
        return {"ok": ok, "detail": detail}
