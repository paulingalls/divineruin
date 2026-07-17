#!/usr/bin/env bash
# Tear down a git worktree's isolated docker stack — the counterpart to
# scripts/init-worktree.sh. `init` brings the per-worktree stack UP, but nothing
# tore it DOWN on worktree removal (cleanup only removes the git worktree),
# leaking containers + volumes. This is the missing teardown.
#
#   (no args)   docker compose down -v for THIS checkout's stack (its .env /
#               derived COMPOSE_PROJECT_NAME). Refuses the PRIMARY stack
#               (dr-divineruin, your shared dev DB) unless --force.
#   --force     tear down even dr-divineruin (deliberate primary reset).
#   --sweep     down -v every running dr-* worktree stack whose git worktree is
#               GONE. Never touches dr-divineruin or a live worktree's stack.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
COMPOSE_FILE="$REPO_ROOT/docker-compose.yml"

# shellcheck source=scripts/worktree-common.sh
source "$REPO_ROOT/scripts/worktree-common.sh"

_down() {  # <project>
  local proj="$1"
  echo "==> docker compose down -v (project $proj)"
  COMPOSE_PROJECT_NAME="$proj" docker compose -f "$COMPOSE_FILE" down -v
}

# Echo COMPOSE_PROJECT_NAME as recorded in this checkout's .env — the value
# `docker compose up` actually used (init-worktree.sh writes it unquoted). Empty
# when .env is absent or has no such key; callers fall back to wt_export_env.
_env_compose_project() {
  [ -f "$REPO_ROOT/.env" ] || return 0
  local line
  line="$(grep -E '^COMPOSE_PROJECT_NAME=' "$REPO_ROOT/.env" | tail -n1)" || return 0
  printf '%s' "${line#COMPOSE_PROJECT_NAME=}"
}

sweep() {
  local running live_basenames orphans proj
  # Running/stopped compose projects (names only) on this docker host.
  running="$(docker compose ls --all --format json 2>/dev/null \
    | python3 -c 'import json,sys; print("\n".join(p["Name"] for p in json.load(sys.stdin)))' 2>/dev/null || true)"
  # Live worktree basenames: `git worktree list --porcelain` emits `worktree <abs-path>`.
  live_basenames="$(git worktree list --porcelain \
    | awk '/^worktree /{p=$0; sub(/^worktree /,"",p); sub(/.*\//,"",p); print p}')"
  # shellcheck disable=SC2086  # word-split live_basenames into args (worktree slugs, no spaces)
  orphans="$(printf '%s\n' "$running" | wt_stale_worktree_projects $live_basenames)"
  if [ -z "$orphans" ]; then
    echo "sweep: no stale dr- worktree stacks."
    return 0
  fi
  echo "sweep: reaping stale worktree stacks:"
  printf '  %s\n' $orphans
  while IFS= read -r proj; do
    [ -n "$proj" ] || continue
    _down "$proj"
  done <<< "$orphans"
}

main() {
  if [ "${1:-}" = "--sweep" ]; then
    sweep
    return
  fi
  local force=0
  [ "${1:-}" = "--force" ] && force=1
  if [ -n "${1:-}" ] && [ "$force" -ne 1 ]; then
    echo "usage: teardown-worktree.sh [--sweep|--force]" >&2
    exit 2
  fi

  # Refuse the PRIMARY checkout on the reliable git-based signal, not a literal
  # project-name match: a primary dir NOT named 'divineruin' still derives a
  # dr-<basename> project, and tearing down the shared dev DB must stay gated.
  if wt_is_primary && [ "$force" -ne 1 ]; then
    echo "teardown-worktree: refusing to tear down the PRIMARY checkout's stack —" >&2
    echo "                   that is your shared dev DB. Re-run with --force to override." >&2
    exit 1
  fi

  # Target the project `docker compose up` actually used: this checkout's .env
  # COMPOSE_PROJECT_NAME (init-worktree.sh writes it), falling back to the derived
  # name when .env carries none.
  local proj
  proj="$(_env_compose_project)"
  if [ -z "$proj" ]; then
    wt_export_env
    proj="$COMPOSE_PROJECT_NAME"
  fi
  _down "$proj"
}

main "$@"
