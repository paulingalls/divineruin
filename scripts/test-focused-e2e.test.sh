#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
fixture="$(mktemp -d)"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/scripts" "$fixture/e2e/specs" "$fixture/bin"
cp "$root/scripts/test-focused-e2e.sh" "$fixture/scripts/"
printf 'test content\n' > "$fixture/e2e/specs/target.e2e.ts"
cat > "$fixture/scripts/worktree-common.sh" <<'AUTH'
wt_expected_env() {
  [ "${FAULT:-}" != authority ] || return 31
  export E2E_API_PORT=12345 DATABASE_URL=dev REDIS_URL=dev
}
AUTH
cat > "$fixture/scripts/test-env.sh" <<'HELPER'
[ -z "${DATABASE_URL:-}" ] || return 0
_te_teardown() { printf 'cleanup\n' >> "$LOG"; rm -f "$SERVICE" "$SERVICE.redis"; }
touch "$SERVICE"
[ "${FAULT:-}" != provision ] || return 32
touch "$SERVICE.redis"
printf 'setup\n' >> "$LOG"
[ "${FAULT:-}" != exports ] || return 0
export DATABASE_URL=isolated REDIS_URL=isolated
case "${FAULT:-}" in migration|seed) return 32 ;; esac
HELPER
cat > "$fixture/bin/bunx" <<'CHILD'
#!/usr/bin/env bash
set -euo pipefail
[ "$DATABASE_URL" = isolated ]
[ "$REDIS_URL" = isolated ]
[ "$PORT" = 12345 ]
[ "$*" = 'playwright test --project=chromium specs/target.e2e.ts --list' ]
printf 'child\n' >> "$LOG"
if [ "${FAULT:-}" = interrupt ]; then echo "$$" > "$SERVICE.child"; exec sleep 20; fi
if [ "${FAULT:-}" = selection ]; then printf 'Total: 0 tests in 0 files\n'; else printf 'Total: 1 test in 1 file\n'; fi
[ "${FAULT:-}" != child ] || exit 33
CHILD
chmod +x "$fixture/bin/bunx"
export LOG="$fixture/log" SERVICE="$fixture/service" PATH="$fixture/bin:$PATH"
run() {
  : > "$LOG"
  set +e
  DATABASE_URL=caller-owned REDIS_URL=caller-owned FAULT="$1" bash "$fixture/scripts/test-focused-e2e.sh" specs/target.e2e.ts --list > "$fixture/output" 2>&1
  result=$?
  set -e
}
run ''
[ "$result" = 0 ] || { cat "$fixture/output"; echo "success failed"; exit 1; }
[ "$(cat "$LOG")" = $'setup\nchild\ncleanup' ] || { echo "setup/child/cleanup missing"; exit 1; }
[ ! -e "$SERVICE" ] || exit 1
for fault in authority provision migration seed child exports selection; do
  run "$fault"
  [ "$result" != 0 ] || { echo "false green: $fault"; exit 1; }
  [ ! -e "$SERVICE" ] && [ ! -e "$SERVICE.redis" ] || { echo "leaked service: $fault"; exit 1; }
  if [ "$fault" != child ] && [ "$fault" != selection ]; then ! rg -q child "$LOG"; fi
done
for path in worktree-common.sh test-env.sh; do
  mv "$fixture/scripts/$path" "$fixture/scripts/$path.saved"
  run ''
  [ "$result" != 0 ] || { cat "$fixture/output"; echo "missing helper false green"; exit 1; }
  ! rg -q child "$LOG"
  mv "$fixture/scripts/$path.saved" "$fixture/scripts/$path"
done
for selection in '' specs/missing.e2e.ts ../specs/target.e2e.ts; do
  if bash "$fixture/scripts/test-focused-e2e.sh" "$selection" --list > /dev/null 2>&1; then
    echo "accepted invalid selection: $selection"; exit 1
  fi
done
FAULT=interrupt bash "$fixture/scripts/test-focused-e2e.sh" specs/target.e2e.ts --list > "$fixture/output" 2>&1 &
runner=$!
for _ in $(seq 1 100); do [ -f "$SERVICE.child" ] && break; sleep 0.02; done
[ -f "$SERVICE.child" ] || { echo 'child never started'; exit 1; }
kill -TERM "$runner"
set +e
wait "$runner"
result=$?
set -e
[ "$result" = 143 ] || { echo 'interruption lost exit status'; exit 1; }
[ ! -e "$SERVICE" ] && [ ! -e "$SERVICE.redis" ] || { echo 'interruption leaked services'; exit 1; }
! kill -0 "$(cat "$SERVICE.child")" 2>/dev/null || { echo 'interruption leaked child'; exit 1; }
: > "$fixture/e2e/specs/target.e2e.ts"
if bash "$fixture/scripts/test-focused-e2e.sh" specs/target.e2e.ts --list > /dev/null 2>&1; then
  echo 'accepted empty spec'; exit 1
fi
echo 'focused runner: isolation, setup, failures, cleanup and selection passed'
