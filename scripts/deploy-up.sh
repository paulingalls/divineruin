#!/usr/bin/env bash
set -euo pipefail
: "${DEPLOY_ENV_FILE:?supply an operator env file}"
export DEPLOY_ENV_FILE
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose=(docker compose -f "$root/deploy/compose.yml" "$@")
# Agent and worker share a tag; concurrent builds stamp different Compose service labels.
"${compose[@]}" build migrate server agent
"${compose[@]}" run --rm --no-deps -T migrate
"${compose[@]}" up -d --no-build --no-deps server agent worker
