#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/scripts/worktree-common.sh"

sweep() {
  local candidates project checkout count=0
  candidates="$(wt_sweep_candidates)" || return 1
  while IFS=$'\t' read -r project checkout; do
    [ -n "$project" ] || continue
    echo "==> removing owned stale project $project"
    wt_destroy_candidate "$project" "$checkout"
    count=$((count + 1))
  done <<< "$candidates"
  [ "$count" -gt 0 ] || echo "sweep: no owned stale worktree stacks."
}

main() {
  if [ "${1:-}" = "--sweep" ]; then
    [ "$#" -eq 1 ] || { echo "usage: teardown-worktree.sh [--sweep|--force]" >&2; return 2; }
    sweep
    return
  fi
  local force=0
  [ "${1:-}" = "--force" ] && force=1
  if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && [ "$force" -ne 1 ]; }; then
    echo "usage: teardown-worktree.sh [--sweep|--force]" >&2
    return 2
  fi
  wt_identity || { wt_die "cannot identify this Git checkout."; return 1; }
  if [ "$WT_GIT_DIR" = "$WT_COMMON_DIR" ] && [ "$force" -ne 1 ]; then
    wt_die "refusing to destroy the primary checkout. Re-run --force from this proven primary checkout."
    return 1
  fi
  local compose_ids projects present runtime_db="${DATABASE_URL:-}" runtime_redis="${REDIS_URL:-}"
  wt_validate_settings
  wt_validate_runtime_values "$runtime_db" "$runtime_redis"
  compose_ids="$(wt_resource_ids "$COMPOSE_PROJECT_NAME")"
  if [ -z "$compose_ids" ]; then
    projects="$(docker compose ls --all --format json)" || return 1
    present="$(printf '%s' "$projects" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d,list); print(int(any(x.get("Name")==sys.argv[1] for x in d)))' "$COMPOSE_PROJECT_NAME")" || return 1
    [ "$present" -eq 0 ] || { wt_die "project $COMPOSE_PROJECT_NAME exists without ownership metadata; refusing teardown."; return 1; }
  else
    wt_authorize destroy
  fi
  wt_remove_livekit
  if [ -n "$compose_ids" ]; then
    echo "==> removing checkout-owned Compose project"
    wt_run_compose down -v
  fi
}

main "$@"
