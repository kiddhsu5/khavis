#!/usr/bin/env bash
# Aliyun ECS deploy helper for llm-router-bot.
#
# Prerequisites:
#   - aliyun CLI configured (`aliyun configure`)
#   - container registry (CR) namespace created
#   - ECS instance reachable via SSH or in same VPC as registry

set -euo pipefail

REGION="${ALIYUN_REGION:-cn-hangzhou}"
NAMESPACE="${ALIYUN_CR_NAMESPACE:-llm-router}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "== Building image =="
docker build -t "$NAMESPACE/llm-router-bot:$IMAGE_TAG" -f deploy/Dockerfile .

echo "== Pushing to Aliyun CR =="
# Tag + push to the registry. Replace <registry-id> with your actual CR endpoint.
REGISTRY="${ALIYUN_REGISTRY_ID:-${NAMESPACE}.registry.aliyuncs.com}"
docker tag "$NAMESPACE/llm-router-bot:$IMAGE_TAG" "$REGISTRY/$NAMESPACE/llm-router-bot:$IMAGE_TAG"
docker push "$REGISTRY/$NAMESPACE/llm-router-bot:$IMAGE_TAG"

echo "== Pulling on ECS + restarting =="
ALIYUN_ECS_HOST="${ALIYUN_ECS_HOST:-llm-router-bot}"
ssh "$ALIYUN_ECS_HOST" <<EOF
  set -eu
  cd ~/llm-router-bot || git clone https://github.com/kiddhsu5/llm-router.git llm-router-bot
  cd llm-router-bot
  git pull --ff-only
  docker pull $REGISTRY/$NAMESPACE/llm-router-bot:$IMAGE_TAG
  docker compose -f deploy/docker-compose.yml --env-file .env up -d
EOF

echo "Done."