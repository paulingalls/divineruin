#!/usr/bin/env bash
# Per-worktree docker-stack isolation helpers.
#
# `git worktree add` gives each teammate checkout its own directory but they all
# share one docker host. docker-compose.yml pins Postgres/Valkey to fixed host
# ports (55432/56379); two worktrees bringing up a stack at once would collide.
# This library derives a deterministic per-checkout host-port OFFSET (and a
# compose project name) so each worktree runs its own isolated stack, while the
# PRIMARY checkout stays at offset 0 — byte-identical to today.
#
# Pure by design: this file only DEFINES functions (no side effects on source),
# so scripts/test-init-worktree.sh can source and unit-test the math, and
# scripts/init-worktree.sh sources it to `wt_export_env` before docker compose.
#
# ports: compose reads ${POSTGRES_HOST_PORT:-55432} / ${VALKEY_HOST_PORT:-56379}
# from the worktree .env; _db_lifecycle.py and ensure-db.ts already key on
# DATABASE_URL's host:port, so an offset .env transparently points them at the
# worktree's own stack — no change needed on their side.

# TRUE for the primary checkout, FALSE for a linked worktree. A linked
# worktree's absolute git dir lives under <primary>/.git/worktrees/<name>, so it
# differs from the common git dir; the primary's two paths are equal.
wt_is_primary() {
  local git_dir common_dir
  git_dir="$(git rev-parse --absolute-git-dir 2>/dev/null || echo "")"
  common_dir="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "")"
  [ -n "$git_dir" ] && [ "$git_dir" = "$common_dir" ]
}

# Pure, deterministic NON-ZERO offset for a checkout name.
#   (cksum(name) % 900 + 1) * 10  ->  [10, 9000], a multiple of 10.
# cksum is POSIX and stable per name. 900 buckets keeps same-offset collisions
# rare across a handful of concurrent worktrees; the *10 ceiling keeps the valkey
# base 56379 + 9000 = 65379 below the 65535 port max. On a rare basename hash
# collision, set WT_PORT_OFFSET to force a distinct offset (see wt_resolved_offset).
# Args: <checkout-basename>
wt_offset_for_name() {
  local sum
  sum="$(printf '%s' "$1" | cksum | awk '{print $1}')"
  echo $(( (sum % 900 + 1) * 10 ))
}

# Sanitize a checkout basename into a legal compose project name and prepend the
# `dr-` project namespace, so every stack (`dr-<name>-postgres-1`) reads as this
# project's in `docker ps` even when several projects share the docker host.
# Sanitize: lowercase, map illegal chars to '-', strip a leading non-alphanumeric
# run (compose requires ^[a-z0-9][a-z0-9_-]*$; `dr-` keeps it legal).
# Args: <checkout-basename>
wt_project_name() {
  local sanitized
  sanitized="$(printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9_-]/-/g; s/^[^a-z0-9]+//')"
  printf 'dr-%s' "$sanitized"
}

# The effective offset for THIS checkout:
#   WT_PORT_OFFSET set  -> that value verbatim (manual override / collision escape)
#   primary checkout    -> 0 (ports byte-identical to today)
#   linked worktree     -> wt_offset_for_name(basename of the checkout root)
wt_resolved_offset() {
  if [ -n "${WT_PORT_OFFSET:-}" ]; then
    echo "$WT_PORT_OFFSET"
    return 0
  fi
  if wt_is_primary; then
    echo 0
    return 0
  fi
  wt_offset_for_name "$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")"
}

# Given the running compose project names (one per line on STDIN) and the live
# git-worktree basenames (as args), echo the projects to REAP: running `dr-*`
# projects that are neither `dr-divineruin` (the primary — always protected) nor
# the project name of any live worktree. Non-`dr-*` projects are ignored.
#
# The live cross-check derives each worktree's project name with wt_project_name
# (NOT a naive `dr-<basename>`): a live worktree `story-006_Foo` runs as
# `dr-story-006_foo` after lowercase/sanitize, so a naive form would miss it and
# the sweep would `down -v` a LIVE stack. Reuse, no re-inline.
# Usage: printf '%s\n' "${running[@]}" | wt_stale_worktree_projects <basename>...
wt_stale_worktree_projects() {
  local live b proj
  live=$'dr-divineruin\n'
  for b in "$@"; do
    live+="$(wt_project_name "$b")"$'\n'
  done
  while IFS= read -r proj; do
    [ -n "$proj" ] || continue
    case "$proj" in
      dr-*) ;;
      *) continue ;;
    esac
    printf '%s\n' "$live" | grep -qxF "$proj" || echo "$proj"
  done
}

# Export the per-worktree docker/app env. docker compose reads POSTGRES_HOST_PORT
# / VALKEY_HOST_PORT / COMPOSE_PROJECT_NAME from the environment (and from the
# worktree .env init-worktree.sh writes); DATABASE_URL / REDIS_URL point the app
# and tests at the same offset stack.
wt_export_env() {
  local root name offset
  root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  name="$(basename "$root")"
  offset="$(wt_resolved_offset)"

  export WT_OFFSET="$offset"
  export POSTGRES_HOST_PORT=$(( 55432 + offset ))
  export VALKEY_HOST_PORT=$(( 56379 + offset ))
  export COMPOSE_PROJECT_NAME="$(wt_project_name "$name")"
  export DATABASE_URL="postgresql://divineruin:divineruin_dev@localhost:${POSTGRES_HOST_PORT}/divineruin"
  export REDIS_URL="redis://localhost:${VALKEY_HOST_PORT}"
}
