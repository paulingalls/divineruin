#!/usr/bin/env bash
set -euo pipefail

# launchd runs an installed copy outside any checkout, so the plist names the source repo.
SOURCE="${SUPER_SOURCE:-$(cd "$(dirname "$0")/.." && pwd -P)}"
TARGET="${SUPER_WORKTREE:-$HOME/.xp/super/divineruin}"
mkdir -p "$(dirname "$TARGET")"
TARGET="$(cd "$(dirname "$TARGET")" && pwd -P)/$(basename "$TARGET")"
ART="$(dirname "$TARGET")/flake-artifacts"
mkdir -p "$ART"
LOG="$ART/super-$(date +%Y%m%d-%H%M%S)-$$.log"
TESTED=unresolved
touch "$LOG"
echo "Super log: $LOG"

finish() {
  local status=$?
  trap - EXIT
  if ! printf 'summary: super status=%s commit=%s log=%s\n' "$status" "$TESTED" "$LOG" | tee -a "$LOG"; then
    status=1
  fi
  if [ "$status" -ne 0 ]; then
    if ! osascript - "$LOG" >>"$LOG" 2>&1 <<'APPLESCRIPT'
on run argv
  display notification ("Failed; log: " & item 1 of argv) with title "Divine Ruin super tests"
end run
APPLESCRIPT
    then
      echo "ERROR: macOS notification delivery failed; log: $LOG" | tee -a "$LOG" >&2
    fi
  fi
  exit "$status"
}
trap finish EXIT

exec 9>"$TARGET.lock"
if ! /usr/bin/lockf -s -t 0 9; then
  echo "ERROR: another super run holds $TARGET.lock" | tee -a "$LOG" >&2
  exit 1
fi

export ALLOW_PAID_TESTS= REQUIRE_REAL_LLM=
export REQUIRE_DOCKER=1 TESTCONTAINERS_RYUK_DISABLED=true
unset WT_PORT_OFFSET COMPOSE_PROJECT_NAME POSTGRES_HOST_PORT VALKEY_HOST_PORT
unset DATABASE_URL REDIS_URL E2E_API_PORT E2E_APP_PORT E2E_WEB_PORT E2E_LH_DEBUG_PORT
unset LIVEKIT_ACCEPTANCE_UDP_PORT LIVEKIT_ACCEPTANCE_CONTAINER TYPEGEN_PORT_MIN TYPEGEN_PORT_MAX

prepare() {
  [ "$#" -le 1 ] || { echo "Usage: $0 [ref]" >&2; return 1; }
  docker info >/dev/null
  cd "$SOURCE"
  git fetch origin refs/heads/main:refs/remotes/origin/main
  local commit common target_common
  commit="$(git rev-parse --verify "${1:-origin/main}^{commit}")"
  echo "Source: $SOURCE; origin/main: $(git rev-parse origin/main); ref: ${1:-origin/main}"
  common="$(git rev-parse --path-format=absolute --git-common-dir)"
  if [ -e "$TARGET" ]; then
    [ "$(git -C "$TARGET" rev-parse --show-toplevel)" = "$TARGET" ]
    target_common="$(git -C "$TARGET" rev-parse --path-format=absolute --git-common-dir)"
    [ "$common" = "$target_common" ]
    [ "$(git -C "$TARGET" rev-parse --absolute-git-dir)" != "$(git rev-parse --absolute-git-dir)" ]
    git worktree list --porcelain | grep -Fx "worktree $TARGET"
    [ -z "$(git -C "$TARGET" status --porcelain --untracked-files=no)" ]
    git -C "$TARGET" checkout --detach "$commit"
  else
    git worktree add --detach "$TARGET" "$commit"
  fi
  cd "$TARGET"
  [ -z "$(git symbolic-ref -q HEAD || true)" ]
  echo "Target: $TARGET; detached HEAD: $(git rev-parse HEAD)"
  echo "Checkout identity: $(git rev-parse --absolute-git-dir)"
  echo "Provider artifacts: $TARGET/flake-artifacts"
  bash scripts/init-worktree.sh
}

set +e
(set -e; prepare "$@") 2>&1 | tee -a "$LOG"
statuses=("${PIPESTATUS[@]}")
set -e
[ "${statuses[0]}" -eq 0 ] || exit "${statuses[0]}"
[ "${statuses[1]}" -eq 0 ] || exit "${statuses[1]}"
TESTED="$(git -C "$TARGET" rev-parse HEAD)"
cd "$TARGET"
set +e
bunx proof run --fresh --set super 2>&1 | tee -a "$LOG"
statuses=("${PIPESTATUS[@]}")
set -e
[ "${statuses[0]}" -eq 0 ] || exit "${statuses[0]}"
exit "${statuses[1]}"
