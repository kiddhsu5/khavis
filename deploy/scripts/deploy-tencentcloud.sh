#!/usr/bin/env bash
# Tencent Cloud Lighthouse / CVM deploy helper for llm-router-bot.
#
# Prerequisites:
#   - tccli configured (`tccli configure`)
#   - TCR namespace created (Tencent Container Registry)
#   - CVM/Lighthouse instance reachable via SSH

set -euo pipefail

REGION="${TENCENTCLOUD_REGION:-ap-guangzhou}"
NAMESPACE="${TENCENTCLOUD_TCR_NAMESPACE:-llm-router}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "== Building image =="
docker build -t "$NAMESPACE/llm-router-bot:$IMAGE_TAG" -f deploy/Dockerfile .

echo "== Pushing to TCR =="
REGISTRY="${TENCENTCLOUD_TCR_REGISTRY:-${NAMESPACE}.tencentcr.com}"
docker tag "$NAMESPACE/llm-router-bot:$IMAGE_TAG" "$REGISTRY/$NAMESPACE/llm-router-bot:$IMAGE_TAG"
docker push "$REGISTRY/$NAMESPACE/llm-router-bot:$IMAGE_TAG"

echo "== Pulling on CVM + restarting =="
TENCENTCLOUD_VM_HOST="${TENCENTCLOUD_VM_HOST:-llm-router-bot}"
ssh "$TENCENTCLOUD_VM_HOST" <<EOF
  set -eu
  cd ~/llm-router-bot || git clone https://github.com/kiddhsu5/llm-router.git llm-router-bot
  cd llm-router-bot
  git pull --ff-only
  docker pull $REGISTRY/$NAMESPACE/llm-router-bot:$IMAGE_TAG
  docker compose -f deploy/docker-compose.yml --env-file .env up -d
EOF

echo "Done."