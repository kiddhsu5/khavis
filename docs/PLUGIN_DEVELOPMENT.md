# Plugin Development

Adding a new LLM provider to K.H.A.V.I.S. is intentionally a small job. A plugin is a single Python file with one class. The registry picks it up automatically; you do not touch any core code.

This guide walks you through writing one from scratch and shipping it.

## The `ProviderPlugin` interface

Every plugin subclasses `ProviderPlugin` (or duck-types it) and implements four things:

```python
from khavis.plugins import ProviderPlugin, ChatResponse, HealthStatus, QuotaStatus

class MyProvider(ProviderPlugin):
    name: str = "my-provider"             # unique, matches pools.yaml
    capabilities: set[str] = {"general"}   # tags the router can match

    def chat(self, messages, **kwargs) -> ChatResponse: ...
    def stream(self, messages, **kwargs) -> Iterator[Chunk]: ...
    def health(self) -> HealthStatus: ...
    def quota(self) -> QuotaStatus: ...
```

Only `name` is strictly required. `capabilities` should be set; the router uses it to match requests. The three callables can be implemented or inherited as no-ops, but a real plugin should implement at least `chat` and `stream`.

### Return types

```python
@dataclass
class ChatResponse:
    text: str
    pool: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    raw: Any = None                       # pass-through provider payload
    finish_reason: str = "stop"

@dataclass
class HealthStatus:
    ok: bool
    latency_ms: int | None = None
    last_error: str | None = None
    last_checked_at: float = 0.0

@dataclass
class QuotaStatus:
    used: float                           # whatever unit the provider reports
    limit: float | None
    window: str                           # "minute" | "hour" | "day" | "month"
    resets_at: float | None = None
```

---

## Hello World plugin

Let us build a minimal but real plugin — a wrapper around a hypothetical `AcmeAI` HTTP API.

### 1. Create the file

```bash
touch providers/acme.py
```

### 2. Write the plugin

```python
# providers/acme.py
"""AcmeAI provider plugin for khavis."""
from __future__ import annotations

import time
import httpx
from khavis.plugins import (
    ProviderPlugin,
    ChatResponse,
    HealthStatus,
    QuotaStatus,
)


class AcmeProvider(ProviderPlugin):
    """Talks to the AcmeAI /v1/chat/completions endpoint."""

    name = "acme"
    capabilities = {"general", "code"}

    def __init__(self, api_key: str, base_url: str = "https://api.acme.ai"):
        self._api_key = api_key
        self._base_url = base_url
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=30.0,
        )
        self._last_health: HealthStatus = HealthStatus(ok=True)

    async def chat(self, messages, **kwargs) -> ChatResponse:
        model = kwargs.get("model", "acme-1-mini")
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 1024)

        started = time.perf_counter()
        resp = await self._client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        latency_ms = int((time.perf_counter() - started) * 1000)

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return ChatResponse(
            text=choice["message"]["content"],
            pool=self.name,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            cost_usd=self._estimate_cost(usage),
            raw=data,
            finish_reason=choice.get("finish_reason", "stop"),
            latency_ms=latency_ms,
        )

    async def stream(self, messages, **kwargs): ...       # similar, SSE or chunked

    async def health(self) -> HealthStatus:
        try:
            r = await self._client.get("/v1/health")
            self._last_health = HealthStatus(
                ok=r.status_code == 200,
                last_checked_at=time.time(),
            )
        except Exception as exc:
            self._last_health = HealthStatus(
                ok=False,
                last_error=str(exc),
                last_checked_at=time.time(),
            )
        return self._last_health

    async def quota(self) -> QuotaStatus:
        # Acme exposes a /v1/usage endpoint that returns per-minute counts.
        r = await self._client.get("/v1/usage")
        r.raise_for_status()
        data = r.json()
        return QuotaStatus(
            used=data["requests_this_minute"],
            limit=data["requests_per_minute_limit"],
            window="minute",
            resets_at=data["window_resets_at"],
        )

    @staticmethod
    def _estimate_cost(usage: dict) -> float:
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        # Acme pricing: $0.10/M input, $0.30/M output.
        return (prompt * 0.10 + completion * 0.30) / 1_000_000
```

### 3. Declare the pool in `pools.yaml`

```yaml
pools:
  - name: acme
    plugin: AcmeProvider              # class name in providers/acme.py
    auth:
      api_key: ${ACME_API_KEY}         # resolved from environment / .env
    options:
      base_url: https://api.acme.ai
    tags:                              # optional extra tags beyond class capabilities
      - code
```

### 4. Tag it in `capabilities.yaml`

```yaml
capabilities:
  code:
    prefer: [MiniMax-M3, acme, volcano-ark-deepseek]
    fallback: [glm53, openrouter-free]
```

### 5. Reload and test

```bash
khavis reload
khavis chat --capability code --message "hello"
```

That is the whole loop.

---

## Capability tag conventions

Tags are lowercase, hyphen-separated strings. The router matches `request.capability ⊆ pool.capabilities` (with the request's capability being a single string or a set).

### Reserved / conventional tags

| Tag             | Meaning                                               |
|-----------------|-------------------------------------------------------|
| `general`       | General-purpose chat (every plugin should declare this)|
| `code`          | Code generation, completion, refactoring              |
| `reasoning`     | Step-by-step reasoning, math, planning                |
| `vision`        | Image input                                          |
| `long-context`  | 100k+ token context window                           |
| `cheap`         | Free or near-free tier                                |
| `local`         | Runs on the host machine, no network egress           |
| `private`       | Provider has a no-log / zero-retention guarantee      |
| `streaming`     | Supports token streaming (almost all do — only set if you want to advertise) |
| `tools`         | Supports function/tool calling                        |
| `json-mode`     | Supports structured JSON output                       |

You can invent your own tags. The router matches them as opaque strings. Invent a tag like `experimental-foo` and route to it — no central registry needed.

---

## Testing your plugin

The repo ships with a pytest harness that boots an in-memory router and exercises your plugin against a mock HTTP server.

```python
# tests/providers/test_acme.py
import pytest
from providers.acme import AcmeProvider

@pytest.fixture
def mock_acme(respx_mock):
    respx_mock.post("https://api.acme.ai/v1/chat/completions").respond(
        json={
            "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
    )
    return respx_mock

async def test_chat_returns_response(mock_acme):
    plugin = AcmeProvider(api_key="test-key")
    resp = await plugin.chat([{"role": "user", "content": "ping"}])
    assert resp.text == "pong"
    assert resp.pool == "acme"
    assert resp.completion_tokens == 1
```

Run:

```bash
pytest tests/providers/test_acme.py -v
```

Conventions:

- One test file per plugin, named `test_<plugin>.py`.
- Cover at minimum: a happy-path chat, a streaming chunk, a health check, a quota check, a 4xx/5xx error.
- Use `respx` (or `pytest-httpx`) for HTTP mocking — no live network calls in tests.

---

## Reference plugins in the repo

The shipped `providers/` directory is the best place to copy-paste from. Highlights:

- `providers/openrouter.py` — minimal OpenAI-compatible plugin (≈110 lines). The cleanest template for any provider that exposes `/v1/chat/completions`.
- `providers/openai.py` — OpenAI Platform API plugin (gpt-5 series). Uses the official `openai` SDK; default model is `gpt-5-mini`.
- `providers/claude.py` — Anthropic-native example. Shows how to:
  1. Split `system` messages out of the chat history (Anthropic takes a single `system=` kwarg, not a message role).
  2. Translate Anthropic `content` blocks back to an OpenAI-style `choices[]` dict so the router and audit log stay provider-agnostic.
- `providers/volcano.py` — factory pattern: one file declares three sub-pools (DeepSeek-V4-Pro, DeepSeek-V4.1-Flash, GLM-5.3-Flash) sharing a single Volcano Ark API key.
- `providers/ollama.py` — environment-variable URL expansion (`${SURFACE_IP}`) for LAN hosts. Useful when you want to spin up one plugin class but serve multiple machines.

---

## Submitting to the registry

If your plugin is generally useful, please open a PR against the upstream `providers/` directory.

The PR template asks for:

- [ ] Plugin file under `providers/` (no subdirectory required).
- [ ] One test file under `tests/providers/`.
- [ ] Entry in `config/pools.yaml.example` (commented out by default).
- [ ] Entry in `docs/CONFIGURATION.md` provider table.
- [ ] `CHANGELOG.md` updated under "Unreleased".
- [ ] No hardcoded secrets — auth must be read from env or `pools.yaml`.
- [ ] License header matching the project (Apache 2.0).

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the full PR checklist.

---

## Advanced: overriding the registry

If you need to do something the standard interface does not support — for example, maintaining a persistent WebSocket connection, or sharing an HTTP/2 client across pools — drop your plugin under `providers/` and it will still be discovered, but you can also add a `setup()` classmethod:

```python
class MyProvider(ProviderPlugin):
    name = "my-provider"

    @classmethod
    def setup(cls, config: dict) -> "MyProvider":
        # called once at boot, with the raw pools.yaml entry
        return cls(api_key=config["auth"]["api_key"])
```

The registry will prefer `setup()` over the default `__init__(api_key=...)` if you define it.

---

## Reference: full method signatures

```python
class ProviderPlugin:
    name: str
    capabilities: set[str]

    async def chat(self, messages: list[dict], **kwargs) -> ChatResponse: ...
    def stream(self, messages: list[dict], **kwargs) -> Iterator[Chunk]: ...
    async def health(self) -> HealthStatus: ...
    async def quota(self) -> QuotaStatus: ...
    @classmethod
    def setup(cls, config: dict) -> "ProviderPlugin": ...
```

`messages` follows the OpenAI chat-completions shape (`{"role": ..., "content": ...}`). `**kwargs` carries per-request overrides (`temperature`, `max_tokens`, `model`, etc.) — your plugin decides which to honor.

Happy hacking.
