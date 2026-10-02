#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
spec="${1:-}"
case "$spec" in specs/*.e2e.ts) ;; *) echo 'Expected one specs/*.e2e.ts path' >&2; exit 2 ;; esac
[[ "$spec" != *..* && -s "$root/e2e/$spec" ]] || { echo 'Missing or empty spec' >&2; exit 2; }
shift
[[ "$#" = 0 || ( "$#" = 1 && "$1" = --list ) ]] || { echo 'Only --list is supported' >&2; exit 2; }
child=''
report=''
cleanup() {
  local status="$1"
  trap - EXIT
  if [ -n "$child" ]; then kill "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi
  if declare -F _te_teardown >/dev/null; then _te_teardown; fi
  if [ -n "$report" ]; then cat "$report"; rm -f "$report"; fi
  exit "$status"
}
trap 'cleanup $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
[ -r scripts/worktree-common.sh ] || exit 1
source scripts/worktree-common.sh
wt_expected_env
export PORT="$E2E_API_PORT"
unset DATABASE_URL REDIS_URL
[ -r scripts/test-env.sh ] || exit 1
source scripts/test-env.sh
[ -n "${DATABASE_URL:-}" ] && [ -n "${REDIS_URL:-}" ] || { echo "Missing fixture service URLs" >&2; exit 1; }
declare -F _te_teardown >/dev/null
cd e2e
if [ "${1:-}" = --list ]; then
  report="$(mktemp)"
  bunx playwright test --project=chromium "$spec" "$@" > "$report" 2>&1 &
else
  bunx playwright test --project=chromium "$spec" "$@" &
fi
child=$!
wait "$child"
child=''

if [ -n "$report" ]; then
  rg -q '^Total: [1-9][0-9]* tests? in 1 file$' "$report" || { echo "No selected tests" >&2; exit 1; }
fi
