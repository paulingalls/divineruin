#!/usr/bin/env bash
set -euo pipefail

TARGET="${SUPER_WORKTREE:-$HOME/.xp/super/divineruin-super}"
mkdir -p "$(dirname "$TARGET")"
TARGET="$(cd "$(dirname "$TARGET")" && pwd -P)/$(basename "$TARGET")"
ART="$(dirname "$TARGET")/flake-artifacts"
mkdir -p "$ART"
LOG="$ART/super-$(date +%Y%m%d-%H%M%S)-$$.log"
TESTED=unresolved
# prepare runs in a subshell; this file tells finish that the clone validated and a stack may exist.
STACK_MARK="$ART/.stack-$$"
rm -f "$STACK_MARK"
touch "$LOG"
echo "Super log: $LOG"

finish() {
  local status=$?
  trap - EXIT
  if [ -e "$STACK_MARK" ]; then
    rm -f "$STACK_MARK"
    if ! (cd "$TARGET" && bash scripts/teardown-worktree.sh --force) >>"$LOG" 2>&1; then
      echo "ERROR: super stack teardown failed; log: $LOG" | tee -a "$LOG" >&2
      status=1
    fi
  fi
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
# Git hooks can export repository-local variables that override the target directory.
unset $(git rev-parse --local-env-vars)
export WT_PORT_OFFSET="${SUPER_PORT_OFFSET:-9000}"
unset COMPOSE_PROJECT_NAME POSTGRES_HOST_PORT VALKEY_HOST_PORT
unset DATABASE_URL REDIS_URL E2E_API_PORT E2E_APP_PORT E2E_WEB_PORT E2E_LH_DEBUG_PORT
unset LIVEKIT_ACCEPTANCE_UDP_PORT LIVEKIT_ACCEPTANCE_CONTAINER TYPEGEN_PORT_MIN TYPEGEN_PORT_MAX

validate_clone() {
  local remote="$1" root git_dir common_dir origin changes
  if ! root="$(git rev-parse --show-toplevel)" || [ "$root" != "$TARGET" ]; then
    echo "ERROR: $TARGET is not a repository root" >&2
    return 1
  fi
  git_dir="$(git rev-parse --absolute-git-dir)"
  common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
  if [ "$git_dir" != "$common_dir" ]; then
    echo "ERROR: $TARGET is a linked worktree" >&2
    return 1
  fi
  if ! origin="$(git remote get-url origin)" || [ "$origin" != "$remote" ]; then
    echo "ERROR: $TARGET origin URL does not match SUPER_REMOTE" >&2
    return 1
  fi
  if ! changes="$(git status --porcelain --untracked-files=no)"; then
    echo "ERROR: cannot check tracked status of $TARGET" >&2
    return 1
  fi
  if [ -n "$changes" ]; then
    echo "ERROR: $TARGET has tracked changes" >&2
    return 1
  fi
}

prepare() {
  [ "$#" -le 1 ] || { echo "Usage: $0 [ref]" >&2; return 1; }
  local remote="${SUPER_REMOTE:-}" ref="${1:-origin/develop}" script_root root commit develop
  if [ -z "$remote" ]; then
    script_root="$(cd "$(dirname "$0")/.." && pwd -P)"
    if ! root="$(git -C "$script_root" rev-parse --show-toplevel)" || [ "$root" != "$script_root" ]; then
      echo "ERROR: set SUPER_REMOTE when running outside the script's checkout" >&2
      return 1
    fi
    if ! remote="$(git -C "$script_root" remote get-url origin)"; then
      echo "ERROR: set SUPER_REMOTE or configure origin in $script_root" >&2
      return 1
    fi
  fi
  docker info >/dev/null
  if [ ! -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
    git clone -- "$remote" "$TARGET"
  fi
  cd "$TARGET"
  validate_clone "$remote"
  touch "$STACK_MARK"
  git fetch --prune origin
  commit="$(git rev-parse --verify --end-of-options "${ref}^{commit}")"
  develop="$(git rev-parse --verify refs/remotes/origin/develop)"
  echo "Clone: $TARGET; origin/develop: $develop; ref: $ref"
  git checkout --detach "$commit"
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
