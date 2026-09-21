# Frequently Asked Questions

> **15+ common questions about llm-router.** If yours is not here, open a [Discussion](https://github.com/llm-router/llm-router/discussions).

---

## General

### 1. How is llm-router different from OpenRouter?

OpenRouter is a **hosted gateway**. You send requests to OpenRouter's servers, OpenRouter calls upstream providers on your behalf, and you pay OpenRouter.

llm-router is a **self-hosted router** that runs on your machine. You send requests to *your* process, which calls the providers directly using *your* API keys. There is no llm-router company in the loop.

|                       | OpenRouter              | llm-router                          |
|-----------------------|-------------------------|-------------------------------------|
| Hosting               | Their cloud             | Your box                            |
| Billing               | Through OpenRouter      | Through your existing subscriptions |
| Free tier access      | Yes (rate-limited)      | Yes (your own free-tier keys)       |
| Local models          | No                      | Yes (Ollama)                        |
| Custom routing rules  | Limited                 | Unlimited YAML                      |
| Data passes through   | OpenRouter servers      | Never leaves your machine*          |

\* *Aside from the actual provider calls you make.*

### 2. How is llm-router different from LiteLLM?

[LiteLLM](https://github.com/BerriAI/litellm) is a translation layer. It gives you a uniform Python API to call many providers, and it is excellent at that job.

llm-router is built on top of the same idea but adds:

- **Routing decisions.** LiteLLM lets you *call* a provider; llm-router decides *which* provider to call for you.
- **Capability matching.** You request `code`, not `gpt-4o`.
- **Fallback chains.** Quota hits trigger automatic rerouting, not exceptions.
- **Multi-agent orchestration.** Built-in `Pipeline` / `DAG` / `Debate` primitives.
- **Three-tier memory.** Working, episodic, semantic — out of the box.
- **Audit & cost tracking.** Append-only JSONL, per-call attribution.

If you only need a thin wrapper, LiteLLM is great. If you need a *router*, llm-router is built for you.

### 3. Is llm-router a SaaS?

No. There is no llm-router cloud. The whole project is self-hosted Apache 2.0 software. If someone is selling you "llm-router as a service", they are a third party.

### 4. What license is llm-router under?

[Apache License 2.0](../LICENSE). You can use it commercially, modify it, distribute it, and ship it inside proprietary products, as long as you keep the license notice and clearly mark any changes you make.

---

## Setup & usage

### 5. Can I use my own API keys?

Yes — that is the entire point. Every pool in `pools.yaml` references `${ENV_VAR}` placeholders. Put your keys in `.env` (or your secret manager) and the router picks them up at boot. llm-router never sees, stores, or proxies your keys to anyone other than the providers themselves.

### 5b. What's BYOK — and which plugins need a separate API account?

**BYOK = Bring Your Own Key.** Some pools are powered by accounts you almost certainly already have (MiniMax, ZhipuAI, Google AI Studio, ByteDance Volcano Ark, OpenRouter, local Ollama). A small handful require a *separate* API account billed directly by the upstream provider. These plugins are still enabled in the code by default — the integration test runner just skips them gracefully when the env var is unset.

| Plugin        | Requires separate API account? | Where to sign up                          |
|---------------|--------------------------------|-------------------------------------------|
| `MiniMax-M3`  | No                             | you already have it                       |
| `GLM-5.3`     | No                             | you already have it                       |
| `Google-Gemini` | No                           | you already have it                       |
| Volcano Ark (×3) | No                          | you already have it                       |
| `OpenRouter-Free` | No                         | you already have it                       |
| Ollama (×2)   | No                             | local                                     |
| **`OpenAI-API`**   | **Yes**                  | https://platform.openai.com               |
| **`Claude-API`**   | **Yes**                  | https://console.anthropic.com             |
| **`NVIDIA-Cloud`** | **Yes** (paid GPU)     | https://build.nvidia.com                   |

Note that an **OpenAI Platform API key** is different from a ChatGPT Plus or ChatGPT GO subscription; an **Anthropic API key** is different from Claude Code or Cursor Pro. If you only have the subscription tier and not the platform tier, simply leave the env var empty — the router will route around the missing pool.

### 6. How do I add a new LLM provider?

Write a single Python file under `providers/`, register it in `pools.yaml`, tag it in `capabilities.yaml`. The registry auto-discovers it on boot (or hot-reload). The full walkthrough is in [`PLUGIN_DEVELOPMENT.md`](PLUGIN_DEVELOPMENT.md). It usually takes 30–90 minutes for a straightforward provider.

### 7. Does llm-router support fine-tuned models?

In v0.1.0, fine-tuned models are supported via per-pool `options.model` overrides — set the model name in `pools.yaml` to your fine-tuned ID and the provider plugin will request it. A first-class fine-tuned registry with hot-swap is planned for **v0.5.0**.

### 8. Can I run llm-router without any cloud provider?

Yes. Point every pool at `ollama-local`, and the router becomes a pure local-model dispatcher. You lose failover diversity but gain full offline operation. This is a popular setup for air-gapped environments.

### 9. Does llm-router work behind a corporate proxy / firewall?

Yes. Set `HTTPS_PROXY` and `HTTP_PROXY` in the environment (standard `requests`/`httpx` conventions), and all provider calls will go through it. Self-signed CA certificates can be passed via `SSL_CERT_FILE`.

### 10. How much overhead does llm-router add?

For a happy-path request: ~1–3 ms of in-process routing logic on top of the provider's own latency. We measure overhead at p99 < 10 ms in benchmarks with 10 pools active. The routing layer does not stream bytes through itself — once a provider is selected, tokens stream directly to the caller.

---

## Privacy & data

### 11. What data does llm-router collect?

**None, by default.** llm-router does not phone home. There is no telemetry, no usage beacon, no "phone home if it crashes" opt-out.

What it *does* do locally:

- Writes an audit log (`config/audit.jsonl`) with: timestamp, capability, pool used, token counts, cost, latency, status.
- Caches episodic memory in a local SQLite file if you opt in.

You can disable the audit log entirely (`audit.log_file: /dev/null` on Unix, or remove the section). You can disable episodic memory by simply not requesting it.

### 12. Where do my prompts go?

Directly to the provider whose pool served the request. llm-router does not proxy, log, or store the prompt content unless you explicitly enable a memory backend that does so.

### 13. Is llm-router SOC 2 / HIPAA / GDPR compliant?

llm-router itself is just code — it inherits the compliance posture of wherever you run it. If you run it on a SOC 2-compliant cloud, in a HIPAA BAA, or under a GDPR-compliant data processing agreement, the *router* does not change that. What you should worry about is the same as without llm-router: which providers you send data to, and under what contract.

The audit log is designed to help you demonstrate compliance (who accessed what, when), not to undermine it. Disable it if your auditor objects.

### 14. Can I disable hot reload for compliance reasons?

Yes — set `LLM_ROUTER_NO_RELOAD=1` in the environment, or run with `--no-reload`. The router will refuse to re-read config until restarted.

---

## Operations

### 15. How do I monitor llm-router in production?

Three options, pick one:

1. **Audit log.** Ship `audit.jsonl` to your log aggregator (Vector, Filebeat, Fluent Bit). Every request is one line.
2. **OpenTelemetry.** Install the optional `llm_router.otel` plugin and set `OTEL_EXPORTER_OTLP_ENDPOINT`. Metrics, traces, and logs all flow through OTLP.
3. **`GET /v1/pools`.** Returns live health and quota for every configured pool. Hit it from your existing blackbox exporter.

### 16. Can I run multiple llm-router instances for high availability?

Yes, but you probably do not need to. A single llm-router process can serve thousands of requests per second on commodity hardware (the bottleneck is provider latency, not the router). If you do run multiple, they are stateless — point them at the same `config/` (read-only) and the same `audit/` directory (with file locking).

### 17. How do I upgrade without downtime?

llm-router supports zero-downtime config reloads (hot reload), but binary upgrades require a restart. Recommended:

1. Start the new version on a different port.
2. Smoke-test it (`llm-router doctor`, a few `/v1/chat` calls).
3. Flip your reverse proxy from the old version to the new.
4. Shut down the old version.

The audit log format is append-only and versioned; old logs remain readable after upgrade.

### 18. What's on the roadmap?

See the [README roadmap](../README.md#roadmap). Highlights: cost budgeting (v0.2.0), built-in RAG (v0.3.0), OpenAI-compatible server mode (v0.4.0), web UI (v0.6.0), stable v1.0 API.

---

## Troubleshooting quick links

- `llm-router doctor` — first thing to run.
- [`INSTALLATION.md`](../INSTALLATION.md) — common install errors.
- [`docs/CONFIGURATION.md`](CONFIGURATION.md) — every YAML knob.
- [GitHub Issues](https://github.com/llm-router/llm-router/issues) — bug reports.
- [GitHub Discussions](https://github.com/llm-router/llm-router/discussions) — questions.
