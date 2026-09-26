# K.H.A.V.I.S.

> **Unified interface for 12 LLM providers with smart routing and zero quota interruption.**

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org)
[![Status](https://img.shields.io/badge/status-v0.1.0--alpha-orange.svg)](#roadmap)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

```
    ┌──────────────────────────────────────────────────────────────┐
    │                     K.H.A.V.I.S.                         │
    │       One API. Twelve pools. Zero quota interruption.        │
    └──────────────────────────────────────────────────────────────┘
```

### Router overhead (p95, real registry, mocked I/O)

| Path | Budget | Measured | Notes |
| --- | --- | --- | --- |
| Cold start (`discovery_ms`) | 200 ms | **0.4 ms** | importlib + class init for 12 plugins |
| YAML reload (`capability_load_ms`) | 50 ms | **9.2 ms** | hot reload goes through this path |
| Per-request routing (`selection_ms`) | 2 ms | **0.02 ms** | same order as Bifrost's published 20 μs |
| End-to-end (`chat_roundtrip_ms`) | 10 ms | **0.2 ms** | router overhead only; upstream LLM I/O dominates |

Full numbers and methodology: [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md). CI gates on the budgets above.

---


### 個人開發者 wall

In production at personal / homelab setups — not enterprise logos. PRs welcome to join.

| Who | Setup |
| --- | --- |
| [@kiddhsu5](https://github.com/kiddhsu5) | homelab · Mac + Surface + Aliyun ECS · MiniMax / GLM / MiMo / Ollama |

Live strip: [`/wall`](https://khavis.kiddhsu.taipei/wall) · operator dashboard: [`/dashboard`](https://khavis.kiddhsu.taipei/dashboard)

---

## Why K.H.A.V.I.S.?

If you have ever paid for multiple LLM subscriptions, you already know the pain:

- **You hit a quota wall mid-task.** Gemini Pro is rate-limited, GLM is down for maintenance, and the one prompt you actually need to run right now cannot complete.
- **You keep rewriting boilerplate.** Every provider ships a different SDK, a different auth scheme, a different streaming protocol, a different function-call format. Your `chat()` function is 600 lines of `if provider == ...`.
- **Your local GPU sits idle while you pay for cloud.** Ollama is right there, but switching contexts is friction.
- **You cannot benchmark fairly.** Each provider has its own temperature defaults, token counters, and pricing units. Apples-to-apples comparisons require glue code.
- **You want a fallback, not a failover.** OpenRouter gives you routing, but it does not know about *your* MiniMax-M3 keys, *your* Volcano Ark credits, or *your* local Ollama box.

**K.H.A.V.I.S. is built for people who already pay for LLMs and just want them to work together.** It treats your subscriptions, free tiers, and local models as one big, capability-tagged pool. When a request arrives, the router picks the best available model, monitors quota pressure, and silently fails over before you ever see a 429.

It is not a hosted gateway. It is not a SaaS. It is a self-hosted, pluggable Python router that runs on your laptop, your homelab, or your CI box, and respects the API keys you already own.

### The promise

> **Zero quota interruption.** When a pool saturates or returns an error, traffic is rerouted within milliseconds — without restarting, without re-authenticating, and without you touching the call site.

---

## Features

- ✓ **12 LLM pools out of the box** — MiniMax-M3, GLM-5.3, Gemini Flash/Pro, NVIDIA Cloud, ByteDance Volcano Ark (3 sub-models), OpenRouter Free, OpenAI Platform API, Anthropic Claude API, Ollama (local + surface).
- ✓ **Capability-based routing** — request a capability (`code`, `vision`, `long-context`, `cheap`, `local`) and the router picks the best fit.
- ✓ **Pluggable provider system** — drop a Python file into `providers/` and it is auto-discovered.
- ✓ **YAML-first configuration** — no UI, no database, just files you can diff in git.
- ✓ **Hot reload** — edit `capabilities.yaml`, watch the router pick it up.
- ✓ **Multi-agent orchestration** — compose multiple LLMs in a single pipeline (planner + coder + critic).
- ✓ **Three-tier memory** — working, episodic, semantic — so multi-turn agents stay coherent.
- ✓ **Audit & observability** — every call is logged with cost, latency, capability, and outcome.
- ✓ **Self-hosted, BYOK** — bring your own keys, your own machine, your own model.
- ✓ **Apache 2.0** — use it commercially, fork it, ship it.

---

## Architecture at a glance

```
                         ┌────────────────────────┐
   Your app / agent ───► │   K.H.A.V.I.S.     │
                         └──────────┬─────────────┘
                                    │
            ┌───────────────────────┼────────────────────────┐
            ▼                       ▼                        ▼
   ┌────────────────┐     ┌────────────────┐      ┌────────────────┐
   │  Capability    │     │   Provider     │      │   Memory &     │
   │   Router       │     │   Registry     │      │   Audit        │
   └────────┬───────┘     └────────┬───────┘      └────────┬───────┘
            │                      │                       │
            ▼                      ▼                       ▼
   ┌──────────────────────────────────────────────────────────────┐
   │              Provider Plugin Pool (12 providers)              │
   │  MiniMax-M3 · GLM-5.3 · Gemini Flash/Pro ·                     │
   │  NVIDIA Cloud · Volcano Ark (×3) · OpenRouter Free · Ollama   │
   │  OpenAI Platform API (BYOK) · Anthropic Claude API (BYOK)     │
   └──────────────────────────────────────────────────────────────┘
```

A request flows through six layers — plugins, registry, capability router, orchestration, memory, and audit. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the deep dive.

---

## Telegram dispatch bot (optional)

A Telegram bot lives in `bot/` that fans a single user prompt out to
Claude Code + OpenAI Codex + this 12-pool gateway in parallel and
returns a synthesized result. See [`docs/TELEGRAM_BOT.md`](docs/TELEGRAM_BOT.md)
for the full operator guide. Quick start:

```bash
pip install -e ".[bot]"
cp deploy/.env.example .env       # fill in BOT_TOKEN, ALLOWED_CHAT_IDS
python -m bot.main --mode polling # local dev (no public endpoint needed)
# OR
docker compose -f deploy/docker-compose.yml up -d   # webhook + Caddy
```

Then from Telegram: `/start`, `/help`, `/status`, `/pools`, `/run <prompt>`.
A single bot user gets zero-quota-interruption: when one backend is
rate-limited or down, the other two still answer.

---

## Quick start

Three commands and you are routing.

```bash
# 1. Install
pip install khavis

# 2. Initialize a config in the current directory
khavis init

# 3. Run the daemon (HTTP API on :8080 by default)
khavis serve
```

That's it. Edit `pools.yaml` to add your API keys, then send a request:

```bash
curl -X POST http://localhost:8080/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"capability": "code", "messages": [{"role": "user", "content": "Write a quicksort in Python."}]}'
```

The router will pick the cheapest available code-capable pool, fall back to the next if it 429s, and log the whole thing.

---

## Installation

### Option A — pip (recommended for development)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install khavis
```

Verify:

```bash
khavis --version
khavis doctor               # checks Python, network, Ollama (if local)
```

### Option B — Docker (zero-install, fully isolated)

```bash
docker run -d \
  --name khavis \
  -p 8080:8080 \
  -v $(pwd)/config:/app/config \
  ghcr.io/kiddhsu5/khavis:0.1.0
```

The image ships with all provider plugins pre-installed. Mount your `config/` directory to persist keys and routing rules.

### Option C — from source (contributors)

```bash
git clone https://github.com/kiddhsu5/khavis.git
cd khavis
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

For full step-by-step setup including Ollama, Docker, and platform-specific notes, see [`INSTALLATION.md`](INSTALLATION.md).

---

## Basic usage

### 1. Capability-based chat

```python
from khavis import Router

router = Router.from_yaml("config/capabilities.yaml")

response = router.chat(
    capability="code",
    messages=[{"role": "user", "content": "Refactor this function."}],
)
print(response.text)
print(f"Pool used: {response.pool}  Cost: ${response.cost_usd:.4f}")
```

### 2. Pinning a specific pool

```python
response = router.chat(
    pool="volcano-ark-deepseek",
    messages=[{"role": "user", "content": "Hello in Japanese."}],
)
```

### 3. Streaming

```python
for chunk in router.stream(capability="long-context", messages=messages):
    print(chunk.delta, end="", flush=True)
```

### 4. Vision

```python
response = router.chat(
    capability="vision",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "What is in this image?"},
            {"type": "image_url", "image_url": {"url": "https://..."}},
        ],
    }],
)
```

### 5. Multi-agent orchestration

```python
from khavis.agents import Pipeline

pipeline = Pipeline([
    ("planner",  {"capability": "reasoning"}),
    ("coder",    {"capability": "code"}),
    ("critic",   {"capability": "code", "temperature": 0.2}),
])

result = pipeline.run(task="Design a REST API for a todo app.")
print(result.final_answer)
```

### 6. Local-first with cloud fallback

```python
router = Router.from_yaml("config/capabilities.yaml")
# capabilities.yaml can pin "local" capability to Ollama, with
# automatic fallback to cloud pools when the box is offline.
response = router.chat(capability="local", messages=messages)
```

---

## Supported providers

| Pool ID                    | Provider                       | Capability hints                       | Notes                                |
|----------------------------|--------------------------------|----------------------------------------|--------------------------------------|
| `MiniMax-M3`               | MiniMax                        | general, code                          | High throughput, low latency         |
| `glm53`                    | Zhipu GLM-5.3                  | reasoning, code, long-context          | Strong Chinese-language support      |
| `gemini-flash`             | Google Gemini Flash            | cheap, vision, long-context            | Fastest Google tier                  |
| `gemini-pro`               | Google Gemini Pro              | reasoning, vision, long-context        | Deeper reasoning                     |
| `nvidia-cloud`             | NVIDIA Cloud (NIM)             | code, reasoning                        | GPU-accelerated inference            |
| `volcano-ark-deepseek`     | ByteDance Volcano Ark (DeepSeek)| code, reasoning                       | Sub-model                            |
| `volcano-ark-qwen`         | ByteDance Volcano Ark (Qwen)   | general, code                          | Sub-model                            |
| `volcano-ark-doubao`       | ByteDance Volcano Ark (Doubao) | general, vision                        | Sub-model                            |
| `openrouter-free`          | OpenRouter Free tier           | cheap, general                         | Aggregator fallback                  |
| `openai-api`               | OpenAI Platform API *(BYOK)*   | code, reasoning, tools                 | gpt-5 series — separate billing      |
| `claude-api`               | Anthropic Claude API *(BYOK)*  | reasoning, tools, long-context         | Sonnet 5 / Opus 4.5 / Haiku 4.5      |
| `ollama-local`             | Ollama (local)                 | local, private                         | Runs on your machine                 |

Each pool is a self-contained plugin under `providers/`. To add your own, see [`docs/PLUGIN_DEVELOPMENT.md`](docs/PLUGIN_DEVELOPMENT.md).

---

## BYOK — Bring Your Own Keys

Some plugins work out of the box with **subscriptions you already have**; others need a **separate API account** billed by usage. The list below clarifies which is which, so you know exactly what to sign up for if you want every pool.

### Works out of the box (uses your existing keys)

| Plugin              | Account you need                                  | Where to get the key                                  |
|---------------------|---------------------------------------------------|-------------------------------------------------------|
| `MiniMax-M3`        | MiniMax API key                                   | https://api.MiniMax.chat                              |
| `GLM-5.3`           | ZhipuAI / BigModel key                            | https://open.bigmodel.cn                               |
| `DeepSeek-V4-Pro`   | ByteDance Volcano Ark key                         | https://www.volcengine.com/product/ark                |
| `DeepSeek-V4.1-Flash` | (same ByteDance key)                            | (same as above)                                       |
| `GLM-5.3-Flash`     | (same ByteDance key)                              | (same as above)                                       |
| `Google-Gemini`     | Google AI Studio key                              | https://aistudio.google.com/app/apikey                |
| `OpenRouter-Free`   | OpenRouter free API key                           | https://openrouter.ai/keys                            |
| `Ollama-Mac`        | None — runs on your machine                       | n/a                                                   |
| `Ollama-Surface`    | None — runs on your LAN                           | n/a                                                   |

### Requires a separate API account (BYOK)

These plugins are **enabled in code by default** but the integration test will skip them if the corresponding env var is unset. Fill in `.env` only for the providers you actually pay for:

| Plugin              | Account you need                                  | Where to sign up                                       |
|---------------------|---------------------------------------------------|--------------------------------------------------------|
| `OpenAI-API`        | OpenAI Platform API key                           | https://platform.openai.com/api-keys                   |
| `Claude-API`        | Anthropic API key                                 | https://console.anthropic.com                          |
| `NVIDIA-Cloud`      | NVIDIA NIM API key                                | https://build.nvidia.com (paid GPU credits)            |

> **Important:** An OpenAI Platform API key is **different** from a ChatGPT Plus / ChatGPT GO subscription. The same goes for Claude API versus Claude Code or Cursor — those tools use their own billing, not the platform API. BYOK means *you* decide which bills you pay; K.H.A.V.I.S. does not add a markup.

---

## Configuration

K.H.A.V.I.S. is configured by two YAML files (and optional environment variables):

| File                              | Purpose                                              |
|-----------------------------------|------------------------------------------------------|
| `config/capabilities.yaml`        | Maps capability tags → ordered pool preferences      |
| `config/pools.yaml`               | Declares each pool, its auth, and per-pool overrides |
| `config/agents.yaml` *(optional)* | Multi-agent pipeline definitions                     |
| `.env`                            | Secrets — never commit this                          |

Example `capabilities.yaml`:

```yaml
capabilities:
  code:
    prefer: [MiniMax-M3, volcano-ark-deepseek, glm53]
    fallback: [nvidia-cloud, openrouter-free]
    max_cost_usd: 0.01

  vision:
    prefer: [gemini-pro, gemini-flash, volcano-ark-doubao]

  local:
    prefer: [ollama-local]
    fallback: [glm53]   # only if you opt in to local→cloud

routing:
  retry_on: [429, 503, timeout]
  max_retries: 3
  cooldown_seconds: 60
```

See [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) for the full reference.

---

## Plugin development

Adding a new provider is a single file. The registry auto-discovers anything that subclasses `ProviderPlugin`:

```python
# providers/my_provider.py
from khavis.plugins import ProviderPlugin, ChatResponse

class MyProvider(ProviderPlugin):
    name = "my-provider"

    def chat(self, messages, **kwargs) -> ChatResponse:
        # your logic here
        ...
```

Register it in `pools.yaml`, add capability tags, submit a PR. Full walkthrough in [`docs/PLUGIN_DEVELOPMENT.md`](docs/PLUGIN_DEVELOPMENT.md).

---

## Roadmap

- [x] **v0.1.0** — Core router, registry, 12 pools (incl. OpenAI + Claude BYOK), capability routing, audit log.
- [ ] **v0.2.0** — Token-aware cost budgeting per request and per session.
- [ ] **v0.3.0** — Built-in RAG connector (Chroma, Qdrant, pgvector).
- [ ] **v0.4.0** — OpenAI-compatible drop-in server mode (replaces `litellm` for many users).
- [ ] **v0.5.0** — First-class fine-tuned model registry with hot-swap.
- [ ] **v0.6.0** — Web UI for live pool health and quota dashboards.
- [ ] **v1.0.0** — Stable plugin API, SemVer guarantees, LTS branch.

Have an idea? Open an issue or vote on the [discussion board](https://github.com/kiddhsu5/khavis/discussions).

---

## Contributing

We welcome PRs of every size — typo fixes, new providers, routing heuristics, docs. Before you start, please read [`CONTRIBUTING.md`](CONTRIBUTING.md).

Highlights:

- PEP 8 + type hints everywhere (`mypy --strict` clean).
- New providers ship with at least one integration test.
- Update `CHANGELOG.md` under "Unreleased".
- Be kind in code review. We optimize for the next contributor.

---

## Community & support

- GitHub Issues: bug reports and feature requests
- GitHub Discussions: questions, show-and-tell, routing recipes
- Discord: *coming soon*
- Security: see [`SECURITY.md`](SECURITY.md) for responsible disclosure

---

## License

Apache License 2.0. See [`LICENSE`](LICENSE) for the full text.

```
Copyright 2026 khavis contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
```

---

## Acknowledgements

K.H.A.V.I.S. stands on the shoulders of:

- The [LiteLLM](https://github.com/BerriAI/litellm) team for normalizing provider APIs.
- The [OpenRouter](https://openrouter.ai) team for proving the routing concept.
- Every provider whose API we adapt to.
- Every contributor who files an issue, writes a plugin, or improves a doc.
