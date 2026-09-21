# Installation

This guide covers the full setup: prerequisites, three install paths, verification, and troubleshooting.

---

## Prerequisites

llm-router is small. You probably already have most of these.

### Required

- **Python 3.11 or newer.** Check with `python --version`.
- **pip** (bundled with Python).
- **Internet egress** to your chosen providers (unless you only use Ollama locally).
- **~50 MB disk** for the package and its dependencies.

### Optional

- **Ollama** (only if you want the `ollama-local` pool): https://ollama.com/download
- **Docker** (only if you use the Docker install path): https://docs.docker.com/get-docker/
- **A CUDA-capable GPU** (only for local Ollama models above ~7B parameters).
- **`make`** (only for contributors running the test suite via `make test`).

### Platform notes

| OS                      | Notes                                                       |
|-------------------------|-------------------------------------------------------------|
| macOS 13+ (Apple Silicon)| Works natively. Ollama uses Metal.                          |
| macOS 13+ (Intel)       | Works. Ollama runs in CPU mode.                             |
| Ubuntu 22.04+           | Recommended Linux. Pre-built wheels available.              |
| Windows 11 + WSL2       | Recommended for Windows. Native Windows also works.         |
| Other Linux             | Should work; please open an issue if it does not.           |

---

## Install path A — pip (recommended)

Best for: developers, contributors, anyone who wants to `import llm_router` from a script.

```bash
# 1. Create a virtual environment
python3.11 -m venv .venv

# 2. Activate it
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows PowerShell
# .venv\Scripts\activate.bat       # Windows cmd

# 3. Upgrade pip and install
pip install --upgrade pip
pip install llm-router

# 4. Verify
llm-router --version
```

You should see something like:

```
llm-router 0.1.0 (python 3.11.x)
```

### Installing from source (contributors)

```bash
git clone https://github.com/llm-router/llm-router.git
cd llm-router
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

The `[dev]` extra adds `pytest`, `mypy`, `ruff`, `respx`, and friends.

---

## Install path B — Docker

Best for: production, isolation, no host Python.

```bash
# Pull the image
docker pull ghcr.io/llm-router/llm-router:0.1.0

# Run it
docker run -d \
  --name llm-router \
  --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/.env:/app/.env:ro \
  ghcr.io/llm-router/llm-router:0.1.0
```

Verify:

```bash
docker logs llm-router
curl http://localhost:8080/healthz
```

### docker-compose

```yaml
# compose.yaml
services:
  router:
    image: ghcr.io/llm-router/llm-router:0.1.0
    ports: ["8080:8080"]
    volumes:
      - ./config:/app/config
      - ./.env:/app/.env:ro
    restart: unless-stopped
```

```bash
docker compose up -d
```

---

## Install path C — system Python (not recommended)

You *can* install with `pip install --user llm-router`, but you lose dependency isolation. Only do this if you fully understand what you are installing alongside it.

---

## Verifying your installation

### 1. The CLI works

```bash
llm-router --version
llm-router doctor
```

`doctor` should report green for: Python version, config dir, plugin discovery, network egress to each provider you have keys for.

### 2. Generate a starter config

```bash
mkdir -p ./config
llm-router init
```

This writes `config/capabilities.yaml`, `config/pools.yaml`, and `config/agents.yaml.example`.

### 3. Start the daemon

```bash
llm-router serve
```

You should see:

```
INFO  boot  llm-router 0.1.0  pid=12345  config=./config
INFO  registry  discovered 12 plugins: MiniMax-M3, glm53, gemini-flash, gemini-pro, nvidia-cloud, volcano-ark-deepseek, volcano-ark-qwen, volcano-ark-doubao, openrouter-free, openai-api, claude-api, ollama-local
INFO  serve  http://0.0.0.0:8080
```

Pools whose required env var is unset are loaded but marked unhealthy — they are silently skipped by the router. To enable every pool, fill in `.env` for the BYOK providers as described below.

### 4. Make a test call

```bash
curl -X POST http://localhost:8080/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "capability": "general",
    "messages": [{"role": "user", "content": "Reply with the word pong."}]
  }'
```

A working install returns a JSON body with `text`, `pool`, `cost_usd`, and `latency_ms`.

### 5. Confirm audit log

```bash
tail -n 1 config/audit.jsonl | jq .
```

You should see a record like:

```json
{
  "ts": "2026-09-20T10:11:12.345Z",
  "capability": "general",
  "pool": "glm53",
  "latency_ms": 842,
  "status": "ok"
}
```

---

## Setting up Ollama (optional)

llm-router ships two Ollama pools out of the box — `Ollama-Mac` (the local
daemon at `http://localhost:11434`) and `Ollama-Surface` (a LAN peer at
`http://$SURFACE_IP:11434`). Both reach into the same `ollama` plugin and
discover the model you point them at via `config/pools.yaml`.

### One-shot (recommended)

```bash
# Mac only — verifies endpoint, pulls gemma4:e2b if missing, smoke-tests it.
bash scripts/setup_ollama.sh --mac

# Surface only — also writes SURFACE_IP into .env.
bash scripts/setup_ollama.sh --surface --ip 192.168.x.x

# Both at once (will prompt for / reuse SURFACE_IP).
bash scripts/setup_ollama.sh
```

The script is idempotent: re-running it skips already-present models and
only pulls what is missing. Add `--pull-only` to skip the smoke test.

### Manual steps

```bash
# 1. Install Ollama.
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull the model that fits the host (see table below).
ollama pull gemma4:e2b            # Mac
ollama pull qwen2.5:1.5b        # Surface (CPU-only)

# 3. Verify the daemon is serving.
curl http://localhost:11434/api/tags
```

### Multi-host (LAN)

Both pools are auto-discovered from `config/pools.yaml`. The Surface pool
expands `${SURFACE_IP}` against the `SURFACE_IP` env var, so once you set
that var (or let `setup_ollama.sh --surface --ip <addr>` write it), the
pool resolves to `http://<addr>:11434`.

Make sure the Surface Ollama daemon listens on `0.0.0.0:11434` (the
default on Windows / Linux is already `127.0.0.1` — set
`OLLAMA_HOST=0.0.0.0` in the Surface's environment to expose it on the
LAN).

#### One-shot Surface setup (Windows)

`scripts/setup_surface_windows.ps1` does all four steps idempotently
(set `OLLAMA_HOST=0.0.0.0` system env, open TCP 11434 in Windows
Firewall, register Ollama to auto-start, pre-pull the default model).
Run **as Administrator**:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_surface_windows.ps1

# Override the default model:
powershell -ExecutionPolicy Bypass -File scripts\setup_surface_windows.ps1 -Model gemma4:e2b

# Skip the pre-pull:
powershell -ExecutionPolicy Bypass -File scripts\setup_surface_windows.ps1 -SkipModelPull

# Tear it all back down:
powershell -ExecutionPolicy Bypass -File scripts\setup_surface_windows.ps1 -Uninstall
```

The script is safe to re-run. It detects an existing Ollama Windows
service and restarts it to pick up the new env var; otherwise it
registers a startup scheduled task that runs `ollama serve`.

### Telegram dispatch (optional)

If you want to drive llm-router from a phone, see
[`docs/TELEGRAM_BOT.md`](docs/TELEGRAM_BOT.md). Three commands:

```bash
pip install -e ".[bot]"                                     # bot extras
cp deploy/.env.example .env                                # BOT_TOKEN, ALLOWED_CHAT_IDS
python -m bot.main --mode polling                          # local dev
# OR
docker compose -f deploy/docker-compose.yml up -d          # webhook + Caddy
```

In Telegram: `/start`, `/help`, `/status`, `/pools`, `/run <prompt>`.
A single user prompt is fanned out to Claude Code + OpenAI Codex +
this 12-pool gateway in parallel; the bot returns each backend's
result plus a synthesized consensus. Tokens come from `@BotFather`;
allowlist chat IDs are read from `ALLOWED_CHAT_IDS` in `.env`.

### Recommended model pairing

| Host | Recommended model | Why |
|------|-------------------|-----|
| Mac (M-series, 8 GB+, Metal) | `gemma4:e2b` (5.1 B, ~7 GB) | Multimodal (vision / audio / tools), runs comfortably on Apple GPUs. |
| Surface Pro 7+ (i5 / 8 GB, CPU only) | `qwen2.5:1.5b` (~1 GB) | General-purpose 1.5 B, fits in 8 GB system RAM, runs on CPU without OOM. |

If you want a different model on either pool, override it in
`config/pools.yaml` under the corresponding pool's `model:` field.

---

## BYOK — Bring Your Own Keys

Not every pool works out of the box. Some need a **separate API account** billed directly by the provider — that is the BYOK model: you keep control of every bill and there is no llm-router markup.

### Pools that work with your existing accounts

These are loaded automatically as soon as you paste the relevant env var into `.env`:

| Pool                    | Account you need             | Notes                                            |
|-------------------------|------------------------------|--------------------------------------------------|
| `MiniMax-M3`            | MiniMax API key              | https://api.MiniMax.chat                         |
| `GLM-5.3`               | ZhipuAI / BigModel key       | https://open.bigmodel.cn                          |
| `DeepSeek-V4-Pro`       | ByteDance Volcano Ark key    | Shared across all three Volcano sub-pools        |
| `DeepSeek-V4.1-Flash`   | (same ByteDance key)         |                                                  |
| `GLM-5.3-Flash`         | (same ByteDance key)         |                                                  |
| `Google-Gemini`         | Google AI Studio key         | One key serves both Flash and Pro variants       |
| `OpenRouter-Free`       | OpenRouter free API key      |                                                  |
| `Ollama-Mac`            | None — local                 | Install Ollama from https://ollama.com/download  |
| `Ollama-Surface`        | None — LAN                   | Set `SURFACE_IP` to the host's reachable IP      |

### Pools that need a separate API account (optional but enabled)

These pools ship **enabled in code** but the integration test will skip them gracefully if their env var is unset. Add them only when you actually pay for them:

| Pool                    | Account you need                                       | Where to sign up                                       |
|-------------------------|--------------------------------------------------------|--------------------------------------------------------|
| `OpenAI-API`            | OpenAI Platform API key                                | https://platform.openai.com/api-keys                   |
| `Claude-API`            | Anthropic API key                                      | https://console.anthropic.com                          |
| `NVIDIA-Cloud`          | NVIDIA NIM API key (paid GPU credits)                  | https://build.nvidia.com                               |

> **Subtle but important:** OpenAI Platform API access is billed separately from ChatGPT Plus / ChatGPT GO subscriptions. Anthropic API access is separate from Claude Code or Cursor Pro. If you have one but not the other, set only the env vars you actually have keys for — the router will route around the missing ones automatically.

---

## Troubleshooting

### `llm-router: command not found`

Your virtualenv is not active. Run `source .venv/bin/activate` (or the Windows equivalent) and try again.

### `ModuleNotFoundError: No module named 'llm_router'`

You installed somewhere Python is not looking. Try:

```bash
which python
which pip
python -m pip show llm-router
```

If `python -m pip show` finds the package but plain `python` does not, you have multiple Pythons. Use `python -m llm_router ...` or fix your `PATH`.

### `Permission denied` on `/var/log/llm-router`

The audit log path is not writable. Either:

- Change `audit.log_file` in `pools.yaml` to a writable path.
- Or run with a user that owns the directory.

### Provider returns `401 Unauthorized`

Your API key is missing or wrong. Check:

```bash
echo $MiniMax_API_KEY     # should print a non-empty string
```

And that the `${VAR}` reference in `pools.yaml` matches the env var name exactly (case-sensitive).

### Provider returns `429 Too Many Requests`

Expected behavior! The router will fall back automatically. If you see it in the audit log with `retries > 0` and `status: "ok"`, the fallback worked. If `status: "error"`, no pool could serve the request — your cooldown may be too long, or you have exhausted every configured pool.

### Hot reload is not picking up my YAML edit

Make sure:

- You are editing the file the daemon loaded (check `INFO boot` log line for `config=...`).
- You did not set `LLM_ROUTER_NO_RELOAD=1`.
- Your editor did an atomic save (some editors truncate + rewrite, which trips the watcher; use `mv` instead of `>` if so).

### `llm-router doctor` reports a missing plugin

A plugin class name in `pools.yaml` does not exist in `providers/`. Check:

- The class name spelling matches exactly (case-sensitive).
- The file is `providers/<lowercase>.py` (or whatever you referenced).
- The file has no syntax errors (`python -c "import providers.acme"` should succeed).

### Docker container exits immediately

```bash
docker logs llm-router
```

Common causes:

- `config/` not mounted (`/app/config` is empty inside the container).
- `.env` not mounted (the daemon exits with "no API keys found").
- Port `8080` already in use (`-p 8081:8080` to remap).

---

## Upgrading

```bash
pip install --upgrade llm-router
# or for Docker
docker pull ghcr.io/llm-router/llm-router:latest
```

Breaking changes between minor versions are listed in [`CHANGELOG.md`](../CHANGELOG.md). Patch versions are always backward compatible.

---

## Uninstalling

```bash
pip uninstall llm-router
# Optional cleanup
rm -rf config/audit.jsonl config/memory.db
```

For Docker:

```bash
docker stop llm-router && docker rm llm-router
docker image rm ghcr.io/llm-router/llm-router:0.1.0
```
