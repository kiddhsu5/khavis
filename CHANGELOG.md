# Changelog

All notable changes to llm-router are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `OpenAI-API` plugin — OpenAI Platform API integration (gpt-5 series). Requires `OPENAI_API_KEY` from https://platform.openai.com. Independent of ChatGPT subscription.
- `Claude-API` plugin — Anthropic Claude API integration (Sonnet 5, Opus 4.5, Haiku 4.5). Requires `ANTHROPIC_API_KEY` from https://console.anthropic.com. Independent of Claude Code or Cursor subscriptions.
- New "長文" (long context) capability tag, primarily served by Claude.
- `anthropic>=0.40.0` to runtime dependencies (needed by the Claude-API plugin).
- BYOK documentation in README and INSTALLATION — clear guidance on which pools require a separate billing account.
- `scripts/setup_ollama.sh` — one-shot setup for Mac + Surface Ollama hosts; validates endpoint reachability, pulls required models if missing, smoke-tests each pool, and writes `SURFACE_IP` to `.env` for the Surface pool. Idempotent.

### Fixed
- `Ollama` plugin now strips the legacy `ollama/` model prefix before posting to the native `/api/chat` endpoint — pools that shipped with `ollama/gemma4:e2b`-style configs no longer fail with HTTP 404 "model not found". Backward compatible: existing configs are auto-normalised on the wire.

### Changed
- `Ollama-Surface` pool default model switched from `ollama/gemma4:e2b` to `qwen2.5-coder:1.5b` (suitable for i5/8 GB CPU-only hosts). Mac pool stays on `gemma4:e2b`.

### Removed
- ChatGPT-GO plugin (`providers/chatgpt.py`) — ChatGPT GO subscription does not include API access. See `docs/PLUGIN_DEVELOPMENT.md` to re-add if you have OpenAI Platform credentials.
- Updated provider count from 11 to 12 (after ChatGPT-GO removal + OpenAI-API + Claude-API additions).

## [0.1.0] — 2026-09-20

The first public release of llm-router.

### Added

**Core**
- Capability-based router with `prefer`/`fallback`/`forbid`/`require` filters.
- Plugin registry with auto-discovery of files in `providers/`.
- Hot reload of `capabilities.yaml`, `pools.yaml`, and individual plugin files.
- YAML-first configuration; no database required to run.
- Append-only JSONL audit log with daily rotation.

**Providers (10 pools shipped)**
- `MiniMax-M3` — MiniMax, tagged `general`, `code`.
- `glm53` — Zhipu GLM-5.3, tagged `general`, `code`, `long-context`.
- `gemini-flash` — Google Gemini Flash, tagged `cheap`, `vision`, `long-context`.
- `gemini-pro` — Google Gemini Pro, tagged `reasoning`, `vision`, `long-context`.
- `nvidia-cloud` — NVIDIA Cloud (NIM), tagged `code`, `reasoning`.
- `volcano-ark-deepseek` — ByteDance Volcano Ark / DeepSeek, tagged `code`, `reasoning`.
- `volcano-ark-qwen` — ByteDance Volcano Ark / Qwen, tagged `general`, `code`.
- `volcano-ark-doubao` — ByteDance Volcano Ark / Doubao, tagged `general`, `vision`.
- `openrouter-free` — OpenRouter free tier, tagged `cheap`, `general`.
- `ollama-local` — Ollama (local), tagged `local`, `private`, `general`.

**Multi-agent orchestration**
- `Pipeline` primitive — sequential LLM chains with per-step capability routing.
- `DAG` primitive — arbitrary directed graphs of LLM calls.
- `Debate` primitive — N agents respond in parallel, a judge picks the best.
- Step-level retry independent of the parent call.
- Per-pipeline cost budget enforcement.

**Memory**
- Working memory (in-process, one `Pipeline.run()` lifetime).
- Episodic memory (SQLite-backed, per `session_id`).
- Semantic memory (pluggable; Chroma / Qdrant / pgvector adapters).
- Per-request opt-in via the `memory={...}` kwarg.

**CLI**
- `llm-router init` — generate starter config files.
- `llm-router serve` — run the HTTP daemon.
- `llm-router chat` — one-shot chat from the terminal.
- `llm-router doctor` — validate config and connectivity.
- `llm-router reload` — manually trigger hot reload.
- `llm-router agent run <name>` — run a named agent pipeline.

**HTTP API**
- `POST /v1/chat` — OpenAI-compatible chat completions.
- `POST /v1/chat/stream` — server-sent-events streaming.
- `GET /v1/pools` — list pools and live health/quota status.
- `GET /healthz` — liveness probe.
- `GET /readyz` — readiness probe (returns 503 until at least one pool is healthy).

**Documentation**
- README (English) and README.zh-TW (Traditional Chinese).
- `docs/ARCHITECTURE.md` — six-layer deep dive with sequence diagram.
- `docs/PLUGIN_DEVELOPMENT.md` — Hello World plugin walkthrough.
- `docs/CONFIGURATION.md` — every YAML knob and env var.
- `INSTALLATION.md` — pip / Docker / source install paths.
- `CONTRIBUTING.md` — code style, PR process, provider PR template.
- `docs/FAQ.md` — 15+ common questions.

**Quality**
- `pytest` suite with `respx` for HTTP mocking.
- `mypy --strict` clean across `llm_router/`.
- `ruff` lint and format enforced in CI.
- Pre-commit hooks for format, lint, types.
- GitHub Actions CI on Python 3.11 and 3.12.

### Notes

This is an alpha release. The plugin API (`ProviderPlugin`) is stable, but
routing semantics may still evolve before v0.2.0. Anything documented as
"experimental" in the docs may change without a SemVer major bump until v1.0.0.

### Known limitations

- Web UI is not yet shipped — use `GET /v1/pools` for now.
- Fine-tuned model registry is not yet shipped (planned for v0.5.0).
- OpenTelemetry exporter ships as an optional extra, not bundled.

## [0.0.x] — Internal pre-releases

Pre-public development. Not documented here.

---

[Unreleased]: https://github.com/llm-router/llm-router/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/llm-router/llm-router/releases/tag/v0.1.0
