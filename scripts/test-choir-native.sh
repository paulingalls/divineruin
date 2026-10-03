#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
child=''
cleanup() {
  local status="$1"
  trap - EXIT
  if [ -n "$child" ]; then kill "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi
  if declare -F _te_teardown >/dev/null; then _te_teardown; fi
  exit "$status"
}
trap 'cleanup $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
source scripts/worktree-common.sh
wt_expected_env
unset DATABASE_URL REDIS_URL
source scripts/test-env.sh
[ -n "${DATABASE_URL:-}" ] && [ -n "${REDIS_URL:-}" ] || exit 1
bun apps/mobile/scripts/verify-choir-encounter.ts &
child=$!
wait "$child"
child=''
