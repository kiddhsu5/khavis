# llm-router Telegram bot — deployment guide

This directory holds everything you need to run the dispatch bot on an
Aliyun / Tencent Cloud VPS.

## TL;DR

```bash
# 1. Fill in secrets
cp .env.example .env             # BOT_TOKEN, ALLOWED_CHAT_IDS
cp deploy/certs/.placeholder deploy/certs/bot.kiddhsu.taipei/
#   ↑ drop fullchain.pem + privkey.pem here

# 2. Build + push
docker build -t llm-router-bot:latest -f deploy/Dockerfile .

# 3. Boot
docker compose -f deploy/docker-compose.yml --env-file .env up -d

# 4. Health check
curl -s https://bot.kiddhsu.taipei/healthz | jq
# expect: {"status":"ok","backends":{"claude":"ok","codex":"ok","llm-router":"ok"}}
```

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | multi-stage build (Python 3.12 + Caddy 2.8) |
| `Caddyfile` | TLS termination, reverse proxy → `bot:8080` |
| `docker-compose.yml` | caddy + bot services, shared network |
| `entrypoint.sh` | starts Caddy, then uvicorn |
| `scripts/deploy-aliyun.sh` | ECS build+push+deploy helper |
| `scripts/deploy-tencentcloud.sh` | CVM/TCR build+push+deploy helper |
| `certs/` | placeholder for LE chain + private key |

## Secrets — never commit these

| Variable | Where it goes |
|---|---|
| `BOT_TOKEN` | `.env` (project root, used by docker-compose via `env_file`) |
| `WEBHOOK_SECRET` | `.env` (defaults to BOT_TOKEN if unset) |
| `ALLOWED_CHAT_IDS` | `.env`, comma-separated integer chat IDs |
| `BACKEND_TIMEOUT_S` | optional, default 180 |
| `LONG_POLL_TIMEOUT_S` | optional, default 30 |

## TLS

Place the existing Let's Encrypt material at:

```
deploy/certs/bot.kiddhsu.taipei/
├── fullchain.pem
└── privkey.pem
```

The historical material lives in `~/.Trash/migration-20260721*/system/caddy-data/certificates/acme-v02.api.letsencrypt.org-directory/bot.kiddhsu.taipei/`. Verify `notAfter` first; if expired, drop the `tls` block from the `Caddyfile` and let Caddy re-issue.

## Mode: webhook vs polling

- **webhook** (default): Caddy serves HTTPS, Telegram POSTs updates to `/webhook`. Public endpoint required.
- **polling**: `BOT_MODE=polling` in `.env`. The bot loops `getUpdates` itself; no public endpoint needed. Drop the `caddy` service from compose.

## Endpoints exposed

- `POST /webhook` — Telegram webhook (header `X-Telegram-Bot-Api-Secret-Token`)
- `POST /webhook/{secret}` — same, with secret in URL path (for legacy webhook registration)
- `GET /healthz` — JSON status, used by Docker healthcheck + Telegram `/status`

## First deployment checklist

1. VPS: 1 vCPU / 1 GB RAM is plenty for a single-user bot.
2. Open inbound 443/TCP (80 only if you want LE renewal from this host).
3. `git clone https://github.com/kiddhsu5/llm-router.git`
4. Fill `.env` with `BOT_TOKEN`, `ALLOWED_CHAT_IDS`.
5. Drop TLS material at `deploy/certs/bot.kiddhsu.taipei/`.
6. `docker compose -f deploy/docker-compose.yml --env-file .env up -d`.
7. Set webhook: `curl "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook?url=https://bot.kiddhsu.taipei/webhook"`.
8. From Telegram, `/start` should reply with a welcome message.

## Local-only testing (no cloud)

```bash
cd /path/to/llm-router
BOT_MODE=polling BOT_TOKEN=... ALLOWED_CHAT_IDS=$(st .. /id .. ) python -m bot.main --mode polling
```

The bot uses long-polling, talks to Telegram directly, and dispatches to local `claude`/`codex`/`llm-router` processes. No Caddy, no port 443.

## Upgrading

```bash
git pull
docker compose -f deploy/docker-compose.yml build bot
docker compose -f deploy/docker-compose.yml up -d
```

The `deploy/scripts/deploy-aliyun.sh` and `deploy/scripts/deploy-tencentcloud.sh` scripts wrap this for you.