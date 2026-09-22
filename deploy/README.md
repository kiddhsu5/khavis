# llm-router Telegram bot — deployment guide

Run the dispatch bot on **Aliyun ECS / Lighthouse** or any Linux VPS.

## TL;DR (Aliyun ECS, recommended)

```bash
# 1. On the Mac — fill .env, build image, push to Aliyun Container Registry
cd /path/to/llm-router
cp deploy/.env.example .env       # fill BOT_TOKEN, ALLOWED_CHAT_IDS
ALIYUN_ECS_HOST=root@<public-ip> bash deploy/scripts/deploy-aliyun.sh

# 2. On the ECS — make sure bot.kiddhsu.taipei resolves to <public-ip>
#    (A record in your DNS provider) and inbound 80+443 are open.

# 3. After first deploy, set the webhook
curl "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook?url=https://bot.kiddhsu.taipei/webhook"

# 4. From Telegram: send /start to the bot, expect a welcome reply.
```

The deploy script does all the work — `git clone` on first run, `git pull` after, `docker compose up -d`. **It expects you to `scp .env user@host:~/llm-router-bot/.env` separately** (out-of-band secret delivery).

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | multi-stage build (Python 3.12-slim + Caddy 2.8-alpine) |
| `Caddyfile` | TLS termination, reverse proxy → `bot:8080` |
| `docker-compose.yml` | caddy + bot services, shared network |
| `entrypoint.sh` | starts Caddy, then uvicorn |
| `scripts/deploy-aliyun.sh` | ECS build+push+deploy helper |
| `scripts/deploy-tencentcloud.sh` | CVM/TCR build+push+deploy helper |
| `.env.example` | template for the secrets file |
| `certs/` (mount) | optional: existing Let's Encrypt chain + private key |

## Secrets

| Variable | Where it goes | Notes |
|---|---|---|
| `BOT_TOKEN` | `.env` (project root, used by docker-compose via `env_file`) | required |
| `WEBHOOK_SECRET` | `.env` | defaults to BOT_TOKEN if unset |
| `ALLOWED_CHAT_IDS` | `.env`, comma-separated int chat IDs | empty = reject all |
| `BACKEND_TIMEOUT_S` | optional, default 180 | per-backend hard timeout |
| `LONG_POLL_TIMEOUT_S` | optional, default 30 | getUpdates timeout |
| `BOT_MODE` | optional, `webhook` (default) or `polling` | polling skips Caddy |

A copy of `BOT_TOKEN` and `ALLOWED_CHAT_IDS` lives at `.env.example` for reference; **never** commit a real `.env`.

## TLS

The `Caddyfile` handles both modes automatically:

1. **Existing cert mounted** at `deploy/certs/bot.kiddhsu.taipei/{fullchain,privkey}.pem`: Caddy serves the cert directly. Useful when migrating from a previous deployment.
2. **No cert mounted**: Caddy auto-issues via ACME HTTP-01 on first request. Requires ports 80 + 443 to be reachable from the public internet.

For Cloudflare-fronted tenants or VPS providers that block inbound 80/443, add a Cloudflare DNS module and switch the ACME challenge to DNS-01.

The historical cert from `~/.Trash/migration-20260721*/system/caddy-data/certificates/acme-v02.api.letsencrypt.org-directory/bot.kiddhsu.taipei/` may already be expired — verify `notAfter` before reusing it.

## Mode: webhook vs polling

- **webhook** (default): Caddy serves HTTPS, Telegram POSTs updates to `/webhook`. Public endpoint required.
- **polling**: set `BOT_MODE=polling` in `.env`. The bot loops `getUpdates` itself; no public endpoint needed. Drop the `caddy` service from compose.

## Endpoints exposed

- `POST /webhook` — Telegram webhook (header `X-Telegram-Bot-Api-Secret-Token`)
- `POST /webhook/{secret}` — same, with secret in URL path (for legacy webhook registration)
- `GET /healthz` — JSON status, used by Docker healthcheck + Telegram `/status`

## First deployment checklist (Aliyun ECS)

1. **Provision ECS** — 1 vCPU / 1 GB RAM is plenty for a single-user bot. Pick an image with Docker pre-installed (Aliyun's "Container-optimized OS" works).
2. **Open inbound ports** — 22 (SSH), 80 (ACME HTTP-01), 443 (webhook).
3. **DNS** — add A record `bot.kiddhsu.taipei → <ECS public IP>`.
4. **Clone the repo on the ECS** (one-time): `ssh root@<ip> "git clone https://github.com/kiddhsu5/llm-router.git ~/llm-router-bot"`.
5. **Copy `.env` to the ECS** (out-of-band, never commit it): `scp .env root@<ip>:~/llm-router-bot/.env`.
6. **Run `deploy/scripts/deploy-aliyun.sh`** from your Mac. It pulls the image and rolls the container.
7. **Wait ~30 s**, then `ssh root@<ip> "curl -fsS https://bot.kiddhsu.taipei/healthz"` — should return `{"status":"ok",...}`.
8. **Set webhook** (one-time): `curl "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook?url=https://bot.kiddhsu.taipei/webhook"`.
9. **Smoke-test** — send `/start` to the bot in Telegram; expect a welcome reply with `chat_id`.

## Local-only testing (no cloud VPS)

```bash
cd /path/to/llm-router
BOT_MODE=polling BOT_TOKEN=... ALLOWED_CHAT_IDS=... python -m bot.main --mode polling
```

No Caddy, no port 443. Useful for development.

## Upgrading

```bash
git pull
docker compose -f deploy/docker-compose.yml build bot
docker compose -f deploy/docker-compose.yml up -d
```

The `deploy/scripts/deploy-aliyun.sh` script wraps this for you and pushes the new image to ACR.

## Troubleshooting

| Symptom | Check |
|---|---|
| `curl /healthz` returns 000 / refused | bot container not up — `docker compose logs bot` |
| `curl /healthz` 502 | Caddy can't reach bot — check `docker network inspect` |
| Telegram 400 "message to be replied not found" | bot using stale code; restart with new image |
| ACME challenge fails (no cert) | inbound 80 blocked — open it |
| Bot silent / log shows `kiddhsu5/llm-router.py not found` | wrong project_root, fix `args.project_root` in `entrypoint.sh` |

## Cleanup / uninstall

```bash
# Stop everything
docker compose -f deploy/docker-compose.yml down

# Wipe bot data (volumes)
docker volume rm llm-router-bot_caddy_data llm-router-bot_caddy_config

# Remove the cloned repo on the ECS
ssh root@<ip> "rm -rf ~/llm-router-bot"
```