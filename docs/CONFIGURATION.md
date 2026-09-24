# Configuration Reference

K.H.A.V.I.S. reads three categories of configuration:

1. **YAML files** in `config/` — declarative routing and pool definitions.
2. **Environment variables** (and `.env`) — secrets and runtime overrides.
3. **Command-line flags** — boot-time toggles.

This document covers all three. The on-disk format is the source of truth — the daemon re-reads it on hot reload.

---

## `config/capabilities.yaml`

Maps a capability tag to an ordered list of pools, plus routing constraints.

```yaml
capabilities:
  <capability-name>:
    prefer: [<pool-id>, ...]           # ordered preference list
    fallback: [<pool-id>, ...]         # used when every prefer pool is unhealthy
    max_cost_usd: <float>              # per-request ceiling
    max_latency_ms: <int>              # soft target — router prefers faster pools when tied
    require: [<tag>, ...]              # hard capability filter
    forbid: [<tag>, ...]               # exclude pools carrying any of these tags

routing:
  retry_on: [<error-class>, ...]       # default: [429, 503, timeout]
  max_retries: <int>                   # default: 3
  cooldown_seconds: <int>              # default: 60
  sticky_session: <bool>               # default: true
  jitter_ms: <int>                     # default: 50 — anti-thundering-herd delay

defaults:
  temperature: 0.7
  max_tokens: 1024
  stream: true
```

### Example: full file

```yaml
capabilities:
  code:
    prefer: [MiniMax-M3, volcano-ark-deepseek, glm53]
    fallback: [nvidia-cloud, openrouter-free]
    max_cost_usd: 0.01
    forbid: [experimental]

  vision:
    prefer: [gemini-pro, gemini-flash, volcano-ark-doubao]
    max_latency_ms: 4000

  long-context:
    prefer: [gemini-pro, gemini-flash, glm53]
    require: [long-context]

  local:
    prefer: [ollama-local]
    fallback: [glm53]                  # opt-in local→cloud
    max_cost_usd: 0.0                  # local must cost $0

  cheap:
    prefer: [openrouter-free, ollama-local, gemini-flash]
    max_cost_usd: 0.001

routing:
  retry_on: [429, 503, 504, timeout]
  max_retries: 3
  cooldown_seconds: 90
  jitter_ms: 75

defaults:
  temperature: 0.7
  max_tokens: 2048
```

---

## `config/pools.yaml`

Declares each pool, its plugin, its auth, and per-pool overrides.

```yaml
pools:
  - name: <pool-id>                    # unique; matches capability pool references
    plugin: <PythonClassName>          # class name in providers/*.py
    enabled: <bool>                    # default: true
    auth:
      api_key: ${ENV_VAR_NAME}         # resolved at boot from .env / process env
      # or
      api_key_file: /run/secrets/key   # mounted secret
      # or
      oauth:                           # for providers that use OAuth
        client_id: ${CLIENT_ID}
        client_secret: ${CLIENT_SECRET}
        token_url: https://...
    options:                           # passed to plugin constructor
      base_url: https://...
      model: gpt-4o-mini
      region: us-east-1
    tags:                              # additive; merged with plugin's class capabilities
      - code
      - cheap
    overrides:
      temperature: 0.3                 # force this pool's default temperature
      max_tokens: 512
    rate_limit:                        # local back-pressure (independent of provider quota)
      requests_per_minute: 60
      tokens_per_minute: 200000

health_check:
  interval_seconds: 30
  timeout_seconds: 5
  failure_threshold: 3                 # mark unhealthy after N consecutive failures

audit:
  log_file: audit.jsonl
  rotate: daily
  retain_days: 30
```

### Example: full file (excerpt)

```yaml
pools:
  - name: MiniMax-M3
    plugin: MiniMaxProvider
    auth:
      api_key: ${MiniMax_API_KEY}
    options:
      base_url: https://api.MiniMax.tech
      model: MiniMax-M3
    tags: [general, code]

  - name: glm53
    plugin: GLMProvider
    auth:
      api_key: ${GLM_API_KEY}
    options:
      base_url: https://open.bigmodel.cn/api/paas/v4
      model: glm-5.3
    tags: [general, code, long-context]

  - name: ollama-local
    plugin: OllamaProvider
    auth: {}                            # no auth for local
    options:
      base_url: http://localhost:11434
      model: llama3.1:8b
    tags: [local, private, general]

  - name: openai-api                    # BYOK: https://platform.openai.com
    plugin: OpenAIProvider
    auth:
      api_key: ${OPENAI_API_KEY}
    options:
      model: gpt-5-mini
    tags: [code, reasoning, tools]

  - name: claude-api                    # BYOK: https://console.anthropic.com
    plugin: AnthropicProvider
    auth:
      api_key: ${ANTHROPIC_API_KEY}
    options:
      model: claude-haiku-4-5-20251001
    tags: [reasoning, tools, long-context]
```

---

## `config/agents.yaml` *(optional)*

Pre-declares multi-agent pipelines you can invoke by name.

```yaml
agents:
  code-reviewer:
    steps:
      - name: planner
        capability: reasoning
        prompt: "Plan a code review for:\n{input}"
      - name: reviewer
        capability: code
        depends_on: [planner]
        prompt: "Review:\n{planner.output}"
      - name: summarizer
        capability: cheap
        depends_on: [reviewer]
        prompt: "Summarize findings in 3 bullets:\n{reviewer.output}"
    budget_usd: 0.05

  researcher:
    type: debate                       # pipeline | dag | debate
    agents:
      - name: optimist
        capability: reasoning
      - name: skeptic
        capability: reasoning
    rounds: 3
    judge:
      capability: reasoning
```

Invoke:

```bash
khavis agent run code-reviewer --input "src/auth.py"
```

Or from Python:

```python
from khavis import Router
router = Router.from_yaml("config/")
result = router.agent("code-reviewer").run(input="src/auth.py")
```

---

## Environment variables

| Variable                  | Purpose                                            |
|---------------------------|----------------------------------------------------|
| `KHAVIS_CONFIG_DIR`   | Directory holding `capabilities.yaml`, `pools.yaml`. Defaults to `./config`. |
| `KHAVIS_LOG_LEVEL`    | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. Default: `INFO`. |
| `KHAVIS_HTTP_PORT`    | Port for `khavis serve`. Default: `8080`.      |
| `KHAVIS_AUDIT_FILE`   | Override the audit JSONL path.                     |
| `KHAVIS_NO_RELOAD`    | Set `1` to disable hot reload (production).       |
| `SURFACE_IP`              | LAN IP of the second Ollama host (Surface) used by the `Ollama-Surface` pool. Falls back to `surface.local` when unset. Set automatically by `bash scripts/setup_ollama.sh --surface --ip <addr>`. |
| `<POOL>_API_KEY`          | Per-pool API key, referenced as `${...}` in `pools.yaml`. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Standard OTLP env var; honored by the OTEL plugin. |

### `.env` loading

K.H.A.V.I.S. uses `python-dotenv` (or stdlib `os.environ` precedence, whichever is higher in the search path). On boot:

1. Load `.env` from `KHAVIS_CONFIG_DIR/../.env` if present.
2. Existing process env wins — `.env` only fills gaps.
3. Secrets referenced as `${VAR}` in YAML are resolved after env loading.

Sample `.env`:

```bash
MiniMax_API_KEY=sk-...
GLM_API_KEY=...
GEMINI_API_KEY=...
NVIDIA_NIM_API_KEY=...
ARK_API_KEY=...
OPENROUTER_API_KEY=...
# Optional (BYOK — see README "BYOK" section)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Hot reload behavior

K.H.A.V.I.S. watches the config directory and individual plugin files with `watchdog`. On change:

| What changed            | What happens                                              |
|-------------------------|-----------------------------------------------------------|
| `capabilities.yaml`     | Routing table reloaded in place. In-flight requests use the previous table until they finish. |
| `pools.yaml`            | Per-pool `enabled`, `tags`, `overrides`, `rate_limit` are reapplied. Pools are *not* recreated (no re-auth). |
| `providers/<file>.py`   | That single plugin module is re-imported and its pool instance is replaced. Auth is re-read. In-flight requests on the old instance are allowed to complete (up to 30 s). |
| `.env`                  | Re-loaded; new env vars apply to subsequent pool construction (i.e., after a plugin reload). |

Reload is logged at INFO with the diff:

```
INFO  config.reload  pools.yaml  +1 ~2 -0  capabilities.yaml  ~3
```

To trigger reload manually: `khavis reload`.

To disable hot reload (production hardening): set `KHAVIS_NO_RELOAD=1`.

---

## Validation

`khavis doctor` validates:

- All YAML files parse.
- Every pool referenced in `capabilities.yaml` is declared in `pools.yaml`.
- Every plugin class exists in `providers/`.
- Every `${ENV_VAR}` resolves.
- No duplicate pool IDs.
- No circular `depends_on` in `agents.yaml`.

Run it after any config change:

```bash
khavis doctor
```
