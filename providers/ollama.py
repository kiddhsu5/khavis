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
import re
from typing import Any

import requests

from .base import ProviderPlugin

DEFAULT_MODEL = "gemma4:e2b"
SURFACE_IP_ENV = "SURFACE_IP"
MAC_IP_ENV = "MAC_IP"
_OPENAI_COMPAT_PREFIX = "ollama/"
_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _normalize_model(model: str | None) -> str | None:
    """Strip the OpenAI-compat ``ollama/`` prefix used on ``/v1/chat/completions``.

    The native ``/api/chat`` endpoint expects a bare model tag like
    ``gemma4:e2b`` and rejects the ``ollama/`` prefix with HTTP 404.
    Older K.H.A.V.I.S. configs and the default below historically shipped
    with the prefix; we tolerate it on the way in so users upgrading
    do not need to edit their pools.yaml.
    """
    if not model:
        return model
    if model.startswith(_OPENAI_COMPAT_PREFIX):
        return model[len(_OPENAI_COMPAT_PREFIX) :]
    return model


def _expand_env(text: str) -> str:
    """Resolve ``${VAR}`` placeholders from the environment.

    An unresolved placeholder becomes ``<var>.local`` rather than being
    left in place: a URL still containing ``${...}`` is not a resolvable
    endpoint and would only fail later with a confusing DNS error. The
    ``.local`` name makes the misconfiguration obvious in health output.

    Both ``${MAC_IP}`` and ``${SURFACE_IP}`` go through here — the pools
    live on a Tailscale network whose addresses vary per deployment, so
    they belong in ``.env``, not in the tracked ``pools.yaml``.
    """

    def _sub(match: re.Match[str]) -> str:
        var = match.group(1)
        return os.getenv(var) or f"{var.lower()}.local"

    return _PLACEHOLDER_RE.sub(_sub, text)


def _model_available(available: set[str], want: str) -> bool:
    """Is ``want`` in Ollama's tag list?

    An untagged request (``gemma4``) matches any tag of that name; a
    tagged one (``gemma4:e2b``) must match exactly, because Ollama treats
    those as distinct models and will 404 on a mismatch.
    """
    want = _normalize_model(want) or ""
    if not want:
        return True
    if want in available:
        return True
    if ":" not in want:
        return any(a.split(":", 1)[0] == want for a in available)
    return False


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
    # The ``model`` field mirrors ``config/pools.yaml`` — keep both in sync.
    _plugin_instances = [
        {
            "name": "Ollama-Mac",
            # Tailscale address of the Mac, not localhost: the router is
            # frequently deployed on a cloud VM whose own Ollama is a
            # different box with different models.
            "base_url": "http://${MAC_IP}:11434",
            "model": "gemma4:e2b",
        },
        {
            "name": "Ollama-Surface",
            "base_url": "http://${SURFACE_IP}:11434",
            "model": "qwen2.5:1.5b",
            "metadata": {"region": "remote", "tier": "self-hosted"},
        },
    ]

    def __init__(
        self,
        name: str = "Ollama-Mac",
        base_url: str | None = None,
        model: str | None = None,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if base_url is None:
            if name.lower().startswith("ollama-surface"):
                base_url = f"http://${{{SURFACE_IP_ENV}}}:11434"
            else:
                base_url = f"http://${{{MAC_IP_ENV}}}:11434"
        # Expand ${VAR} placeholders sourced from pools.yaml.
        base_url = _expand_env(base_url)
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
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        url = f"{self.default_endpoint.rstrip('/')}/api/chat"
        payload: dict[str, Any] = {
            "model": _normalize_model(self.model),
            "messages": messages,
            "stream": False,
        }
        payload.update(kwargs)
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
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

    def check_quota(self) -> dict[str, Any]:
        # Ollama is local, so quota is effectively unbounded.
        return {
            "remaining": None,
            "total": None,
            "tier": "local",
            "provider": self.provider_id,
            "note": "Local Ollama has no external quota.",
        }

    def list_models(self) -> list[str]:
        url = f"{self.default_endpoint.rstrip('/')}/api/tags"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []

    def health_check(self) -> dict[str, Any]:
        """Reachability *and* that the configured model is actually pulled.

        Checking only that the endpoint answers is not enough. A pool whose
        model is missing reports healthy (``/`` returns 200) and then 404s
        on ``/api/chat`` — which is exactly what hid behind Ollama-Mac when
        it pointed at a box without ``gemma4:e2b``.
        """
        tags_url = f"{self.default_endpoint.rstrip('/')}/api/tags"
        try:
            resp = requests.get(tags_url, timeout=5)
        except Exception as exc:  # pragma: no cover - network failure
            return {"ok": False, "detail": f"endpoint={self.default_endpoint} error={exc!r}"}

        if resp.status_code >= 500:
            return {
                "ok": False,
                "detail": f"endpoint={self.default_endpoint} status={resp.status_code}",
            }

        try:
            payload: Any = resp.json()
        except ValueError:
            payload = {}
        models = payload.get("models") if isinstance(payload, dict) else None
        available = {
            str(m.get("name") or m.get("model") or "")
            for m in (models or [])
            if isinstance(m, dict)
        }

        want = _normalize_model(self.model) or ""
        if want and not _model_available(available, want):
            have = ", ".join(sorted(a for a in available if a)[:6]) or "none"
            return {
                "ok": False,
                "detail": (
                    f"endpoint={self.default_endpoint} reachable but model "
                    f"{want!r} not pulled (have: {have})"
                ),
            }
        return {
            "ok": True,
            "detail": f"endpoint={self.default_endpoint} model={want or '-'} available",
        }
