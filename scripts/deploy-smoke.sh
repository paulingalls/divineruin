#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "${1:-}" =~ ^(server|agent|migrate|media)$ && $# == 1 ]] || { echo 'usage: bash scripts/deploy-smoke.sh server|agent|migrate|media' >&2; exit 2; }
source scripts/worktree-common.sh
wt_authorize connect
export SMOKE_DB="$DATABASE_URL" SMOKE_REDIS="$REDIS_URL" SMOKE_OWNER="$COMPOSE_PROJECT_NAME"
exec python3 scripts/deploy_smoke.py "$1"
