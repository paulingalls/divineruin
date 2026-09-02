#!/usr/bin/env bash
# Provision a fresh git worktree (or the primary checkout) for work.
#
# `git worktree add` materializes only TRACKED files, so a teammate worktree
# starts broken: no node_modules, no apps/agent/.venv, no gitignored Expo
# generated types, no .env, and no database. This script installs all of that
# and brings up an ISOLATED per-worktree docker stack (own ports + project name,
# see scripts/worktree-common.sh), then migrates + seeds it.
#
# Declared as system_context stack.worktree_bootstrap = "bash scripts/init-worktree.sh".
# The xp-agents runner runs it with cwd = the new worktree and treats a non-zero
# exit as FATAL — no agent starts, the worktree is left standing for inspection.
#
#   * Idempotent — every step is a safe no-op or safe regenerate on a warm
#     checkout, so re-running is always safe.
#   * Fail-loud — a half-provisioned worktree must never host an agent.
#   * .env is never clobbered — local edits (real API keys) are sacred.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# shellcheck source=scripts/worktree-common.sh
source "$REPO_ROOT/scripts/worktree-common.sh"

# Expo typegen dev-server port band. Deliberately above the mobile/e2e ports
# (8082 app/web, 8085 web-prod, 3001 playwright) so a typegen server never
# serves its bundle into a running e2e run. We SCAN this band (not a fixed
# port): concurrent worktree bootstraps must not all grab the same port.
TYPEGEN_PORT_MIN=8890
TYPEGEN_PORT_MAX=8899
TYPEGEN_LOCK_ROOT="${TMPDIR:-/tmp}/divineruin-typegen-ports"

ROUTER_TYPES="$REPO_ROOT/apps/mobile/.expo/types/router.d.ts"
EXPO_ENV_TYPES="$REPO_ROOT/apps/mobile/expo-env.d.ts"

# ── Expo generated types ──────────────────────────────────────────────────────
# WHY: apps/mobile has `typedRoutes: true`, so expo-router emits router.d.ts with
# the augmented `Href` type. Both router.d.ts and expo-env.d.ts are gitignored
# and generated, so a bare worktree lacks them. Without router.d.ts a BOGUS route
# compiles clean (Href falls back to permissive `string`) — a false green that is
# TS2322 in the primary. expo-router writes both files at dev-server STARTUP
# (no bundling; ~seconds); there is no standalone typegen command in SDK 55.

# Release a reservation only when this bootstrap still owns it.
# Args: <port>
release_typegen_port() {
  local port="$1" lock_dir owner
  lock_dir="$TYPEGEN_LOCK_ROOT/$port"
  [ -f "$lock_dir/pid" ] || return 0
  owner="$(<"$lock_dir/pid")"
  [ "$owner" = "$$" ] || return 0
  rm -f "$lock_dir/pid"
  rmdir "$lock_dir" 2>/dev/null || true
}

# Atomically reserve an unbound port. A failed mkdir belongs to another
# bootstrap; a dead owner is reaped before one retry.
# Args: <port>
reserve_typegen_port() {
  local port="$1" lock_dir owner
  lock_dir="$TYPEGEN_LOCK_ROOT/$port"
  if ! mkdir "$lock_dir" 2>/dev/null; then
    [ -f "$lock_dir/pid" ] || return 1
    owner="$(<"$lock_dir/pid")"
    case "$owner" in
      ''|*[!0-9]*) return 1 ;;
    esac
    if kill -0 "$owner" 2>/dev/null; then
      return 1
    fi
    rm -f "$lock_dir/pid"
    rmdir "$lock_dir" 2>/dev/null || return 1
    mkdir "$lock_dir" 2>/dev/null || return 1
  fi
  if ! printf '%s\n' "$$" > "$lock_dir/pid"; then
    rm -f "$lock_dir/pid"
    rmdir "$lock_dir" 2>/dev/null || true
    echo "init-worktree: could not record the owner of typegen port $port." >&2
    return 2
  fi
  if lsof -ti ":$port" -sTCP:LISTEN >/dev/null 2>&1; then
    release_typegen_port "$port"
    return 1
  fi
}

# Echo a reserved, unbound port in [start,end]; fail loud (never a default) when
# none is available. A default could hand typegen a foreign Metro's port.
# Args: <start> <end>
pick_typegen_port() {
  local start="$1" end="$2" span base i p status
  if ! mkdir -p "$TYPEGEN_LOCK_ROOT"; then
    echo "init-worktree: could not create the typegen port lock root $TYPEGEN_LOCK_ROOT." >&2
    return 2
  fi
  span=$((end - start + 1))
  base=$((RANDOM % span))
  for ((i = 0; i < span; i++)); do
    p=$((start + (base + i) % span))
    if reserve_typegen_port "$p"; then
      echo "$p"
      return 0
    else
      status=$?
      [ "$status" -eq 1 ] || return "$status"
    fi
  done
  echo "init-worktree: no free port in ${start}-${end} for the typegen dev server." >&2
  echo "               Free one (lsof -ti :${start}-${end}) and re-run." >&2
  return 1
}

# Kill the typegen dev server by PROCESS GROUP: `bunx expo start` runs the real
# Metro as a node CHILD, so killing only the backgrounded job leaves node holding
# the port. `set -m` (in run_typegen) makes the job a group leader; -pid targets
# the whole tree. Never sweep the port — under concurrent bootstraps the holder
# may be another worktree's Metro.
# Args: <pid>
reap_typegen() {
  local pid="${1:-}"
  [ -n "$pid" ] || return 0
  kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

# Confirm that every listener on a port belongs to the launched Expo process
# group. An absent listener is also a failure: Expo may have auto-bumped.
# Args: <port> <expected-process-group>
assert_typegen_port_owner() {
  local port="$1" expected_group="$2" listeners listener group
  listeners="$(lsof -ti ":$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -z "$listeners" ]; then
    echo "init-worktree: no listener on reserved typegen port $port." >&2
    return 1
  fi
  for listener in $listeners; do
    group="$(ps -o pgid= -p "$listener" 2>/dev/null | tr -d ' ')"
    if [ "$group" != "$expected_group" ]; then
      echo "init-worktree: listener on reserved typegen port $port is outside Expo's process group." >&2
      return 1
    fi
  done
}

cleanup_typegen() {
  reap_typegen "${1:-}"
  [ -z "${2:-}" ] || release_typegen_port "$2"
}

# Start Expo just long enough to emit the two type files, then reap it. ALWAYS
# regenerates: we wait for both files to be NEWER than a marker stamped now, so a
# stale copy on a warm checkout is refreshed rather than silently kept.
run_typegen() {
  local port pid log waited marker
  port=""; pid=""; log=""; marker=""
  trap 'cleanup_typegen "$pid" "$port"' EXIT
  trap 'cleanup_typegen "$pid" "$port"; exit 130' INT TERM HUP
  port="$(pick_typegen_port "$TYPEGEN_PORT_MIN" "$TYPEGEN_PORT_MAX")" || exit 1
  log="$(mktemp -t init-worktree-typegen)"
  marker="$(mktemp -t init-worktree-marker)"

  echo "==> regenerating Expo types (dev server on :$port, no bundling)"
  # `set -m` -> own process group so reap_typegen kills the node child too.
  # CI=1 keeps the CLI non-interactive (no port-in-use prompt, no login nag).
  set -m
  (cd "$REPO_ROOT/apps/mobile" && CI=1 bunx expo start --port "$port" >"$log" 2>&1) &
  pid=$!
  set +m

  waited=0
  until lsof -ti ":$port" -sTCP:LISTEN >/dev/null 2>&1; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "init-worktree: the typegen dev server exited before binding reserved port $port." >&2
      sed 's/^/    /' "$log" >&2
      exit 1
    fi
    if ! [ "$marker" -nt "$ROUTER_TYPES" ] && [ -f "$EXPO_ENV_TYPES" ]; then
      assert_typegen_port_owner "$port" "$pid" || true
      sed 's/^/    /' "$log" >&2
      exit 1
    fi
    sleep 0.5
    waited=$((waited + 1))
    if [ "$waited" -ge 360 ]; then
      echo "init-worktree: timed out waiting for Expo to bind reserved port $port." >&2
      sed 's/^/    /' "$log" >&2
      exit 1
    fi
  done
  if ! assert_typegen_port_owner "$port" "$pid"; then
    sed 's/^/    /' "$log" >&2
    exit 1
  fi
  release_typegen_port "$port"

  waited=0
  # Exit once router.d.ts is regenerated (newer-or-equal to the marker) AND
  # expo-env.d.ts merely EXISTS. router.d.ts is the false-green-critical file
  # (typed routes) that expo-router rewrites every startup, so gating regen on it
  # is right. expo-env.d.ts is static boilerplate expo writes ONCE and skips when
  # unchanged — requiring IT to be newer than the marker hung a warm re-run for
  # the full timeout (debt de36dd4b8a79), so we only require it to be present.
  # `! marker -nt file` (not `file -nt marker`): macOS /bin/bash compares mtime in
  # whole seconds, so a same-second write is not `-nt`; the inverted form accepts
  # an equal-second write and is false while the file is absent (marker -nt absent
  # = true), covering the fresh case too.
  until ! [ "$marker" -nt "$ROUTER_TYPES" ] && [ -f "$EXPO_ENV_TYPES" ]; do
    sleep 0.5
    waited=$((waited + 1))
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "init-worktree: the typegen dev server exited before writing its types." >&2
      sed 's/^/    /' "$log" >&2
      exit 1
    fi
    # 180s ceiling (360 * 0.5s). Measured cost is a few seconds and a crash is
    # caught instantly above, so this only fires on a true hang — well inside the
    # runner's 600s budget.
    if [ "$waited" -ge 360 ]; then
      echo "init-worktree: timed out waiting for Expo to write its generated types." >&2
      echo "               Without them, typecheck FALSE-GREENS on a bogus route." >&2
      sed 's/^/    /' "$log" >&2
      exit 1
    fi
  done

  cleanup_typegen "$pid" "$port"
  trap - EXIT INT TERM HUP
  rm -f "$log" "$marker"
  echo "    wrote apps/mobile/.expo/types/router.d.ts + apps/mobile/expo-env.d.ts"
}

# ── .env ──────────────────────────────────────────────────────────────────────
# Generate .env from .env.example ONLY when absent (local edits are sacred), with
# this worktree's offset ports baked in. compose reads POSTGRES_HOST_PORT /
# VALKEY_HOST_PORT / COMPOSE_PROJECT_NAME from .env on LATER invocations (e.g. a
# teammate's `bun run test:all` -> ensure-db.ts) when this script's exported env
# is gone; DATABASE_URL / REDIS_URL point the app + tests at the offset stack.
write_env_if_absent() {
  if [ -f "$REPO_ROOT/.env" ]; then
    echo "==> .env present — leaving it untouched"
    return 0
  fi
  echo "==> writing .env (from .env.example, offset $WT_OFFSET)"
  DATABASE_URL="$DATABASE_URL" REDIS_URL="$REDIS_URL" \
  POSTGRES_HOST_PORT="$POSTGRES_HOST_PORT" VALKEY_HOST_PORT="$VALKEY_HOST_PORT" \
  COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
  python3 - "$REPO_ROOT/.env.example" "$REPO_ROOT/.env" <<'PY'
import os, sys
src, dst = sys.argv[1], sys.argv[2]
# Keys we set/override so the worktree stack is self-describing in .env.
overrides = {k: os.environ[k] for k in (
    "DATABASE_URL", "REDIS_URL",
    "POSTGRES_HOST_PORT", "VALKEY_HOST_PORT", "COMPOSE_PROJECT_NAME",
)}
seen = set()
out = []
for line in open(src):
    stripped = line.lstrip()
    if "=" in stripped and not stripped.startswith("#"):
        key = stripped.split("=", 1)[0].strip()
        if key in overrides:
            out.append(f"{key}={overrides[key]}\n")
            seen.add(key)
            continue
    out.append(line)
if out and not out[-1].endswith("\n"):
    out.append("\n")
for key, val in overrides.items():
    if key not in seen:
        out.append(f"{key}={val}\n")
open(dst, "w").write("".join(out))
PY
}

# ── docker stack ──────────────────────────────────────────────────────────────
# Bring up THIS worktree's isolated Postgres+Valkey. Guard against a foreign
# holder of our offset host ports (a rare basename-hash collision) with a
# loud, actionable failure rather than compose's cryptic bind error.
start_stack() {
  echo "==> docker stack: project=$COMPOSE_PROJECT_NAME pg=$POSTGRES_HOST_PORT valkey=$VALKEY_HOST_PORT"
  # Our own running stack already holds the ports on a re-run — that's fine.
  if [ -z "$(docker compose ps --status running -q postgres 2>/dev/null)" ]; then
    local pair port label
    for pair in "$POSTGRES_HOST_PORT:postgres" "$VALKEY_HOST_PORT:valkey"; do
      port="${pair%%:*}"; label="${pair##*:}"
      if lsof -ti "tcp:$port" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "init-worktree: host port $port ($label) is already in use by another" >&2
        echo "               process/worktree (offset collision). Set WT_PORT_OFFSET" >&2
        echo "               to a distinct value and re-run." >&2
        exit 1
      fi
    done
  fi
  # --wait blocks until BOTH services pass their compose healthcheck (Postgres's
  # is pg_isready), so a cold volume is query-ready before migrate/seed — which
  # talk to the DB directly with no readiness wait of their own.
  docker compose up -d --remove-orphans --wait --wait-timeout 120
}

# ── run ───────────────────────────────────────────────────────────────────────
main() {
  wt_export_env
  echo "==> provisioning worktree: project=$COMPOSE_PROJECT_NAME offset=$WT_OFFSET"

  echo "==> bun install"
  bun install

  # e2e/ is NOT a workspace member (root package.json lists only apps/* and
  # packages/*) and carries its own lockfile, so the root install above reaches
  # none of its deps. Without this the pre-push gate's Playwright lane dies in a
  # fresh worktree with ERR_MODULE_NOT_FOUND on '@playwright/test', and so does
  # `bun run lint:e2e`.
  echo "==> bun install (e2e)"
  ( cd "$REPO_ROOT/e2e" && bun install )

  write_env_if_absent

  echo "==> uv sync (apps/agent)"
  ( cd "$REPO_ROOT/apps/agent" && uv sync )

  run_typegen

  start_stack

  echo "==> migrate"
  bun run migrate
  echo "==> seed"
  bun run seed

  echo
  echo "Worktree provisioned. Verify with: bun run lint && bun run lint:e2e && bun run test:all"
}

# Only run when EXECUTED, never when sourced (test harnesses may source for the
# helpers above without bootstrapping).
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
