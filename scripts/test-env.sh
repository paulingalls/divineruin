#!/usr/bin/env bash
# Provision a PER-RUN, isolated Postgres + Redis for the test/push gate WITHOUT
# relying on a dev .env — so two overlapping runs (close-pipeline back-to-back
# pushes) never collide on a shared DB or fixed ports.
#
# SOURCE this (do not exec) so the exported vars AND the teardown function reach
# the caller:
#   source scripts/test-env.sh
#
#   - NO-OP if DATABASE_URL is already set (a dev with .env, or CI's service
#     vars) — never overrides an existing environment.
#   - Otherwise it starts a uniquely-named postgres + redis on EPHEMERAL host
#     ports via `docker run`, waits for readiness, migrates + seeds, and exports
#     the run's DATABASE_URL/REDIS_URL. It also defines `_te_teardown` and leaves
#     the container ids set; the CALLER registers a trap that removes the
#     containers on exit (see .githooks/pre-push). Requires Docker.

if [ -n "${DATABASE_URL:-}" ]; then
  echo "  test-env: DATABASE_URL already set — using the existing environment."
  return 0 2>/dev/null || exit 0
fi

_te_root="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
# Per-run id keyed on the sourcing shell's PID — unique across overlapping
# `git push` processes, stable for the lifetime of one run.
_te_id="dr-test-$$"

echo "  test-env: provisioning per-run postgres + redis (${_te_id})..."

# Define teardown BEFORE the docker runs, by deterministic container NAME (the
# cid vars don't exist yet). Under `set -e`, if the SECOND `docker run` (redis)
# fails right after the FIRST (pg) starts, the script aborts before any cid is
# captured — but the caller's trap still fires _te_teardown, which removes both
# containers by their `${_te_id}-{pg,redis}` names. `docker rm -f` on a
# never-created name is a harmless no-op. The cid vars are preferred once set
# (an explicit handle), with the name as the always-defined fallback.
_te_teardown() {
  docker rm -f "${_te_pg_cid:-${_te_id}-pg}" >/dev/null 2>&1
  docker rm -f "${_te_redis_cid:-${_te_id}-redis}" >/dev/null 2>&1
  return 0
}

# A prior run that was SIGKILL'd before its trap fired leaves same-named
# containers behind (the id is PID-keyed and PIDs recycle). Clear any leftovers
# so the `docker run --name` below can't collide and abort under `set -e`.
docker rm -f "${_te_id}-pg" "${_te_id}-redis" >/dev/null 2>&1 || true

# `-p 127.0.0.1:0:<port>` lets the kernel assign a free host port atomically
# (no pick-then-bind race). Image/creds match docker-compose.yml for parity.
_te_pg_cid="$(docker run -d --name "${_te_id}-pg" -p 127.0.0.1:0:5432 \
  -e POSTGRES_USER=divineruin -e POSTGRES_PASSWORD=divineruin_dev \
  -e POSTGRES_DB=divineruin postgres:16-alpine)"
_te_redis_cid="$(docker run -d --name "${_te_id}-redis" -p 127.0.0.1:0:6379 redis:7-alpine)"

# Read the kernel-assigned ephemeral host ports (e.g. "127.0.0.1:49xxx").
_te_pg_port="$(docker port "${_te_pg_cid}" 5432/tcp | head -1)"; _te_pg_port="${_te_pg_port##*:}"
_te_redis_port="$(docker port "${_te_redis_cid}" 6379/tcp | head -1)"; _te_redis_port="${_te_redis_port##*:}"

# Wait for Postgres to be QUERY-ready (not merely TCP-listening): a cold
# container maps the port before initdb finishes. pg_isready inside the
# container is the same gate the compose healthcheck used.
echo "  test-env: waiting for postgres readiness..."
for _ in $(seq 1 60); do
  if docker exec "${_te_pg_cid}" pg_isready -U divineruin -d divineruin >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
for _ in $(seq 1 30); do
  if [ "$(docker exec "${_te_redis_cid}" redis-cli ping 2>/dev/null)" = "PONG" ]; then
    break
  fi
  sleep 1
done

export DATABASE_URL="postgresql://divineruin:divineruin_dev@localhost:${_te_pg_port}/divineruin"
export REDIS_URL="redis://localhost:${_te_redis_port}"

# NOTE: per-run *server* ports (Playwright API/mobile/web) were tried and
# reverted — `expo` bakes EXPO_PUBLIC_API_URL into the cached metro bundle, so a
# per-run API port leaves the mobile app fetching a dead port. The Playwright
# servers stay on their default ports; reuseExistingServer:false handles the
# cross-run collision. True E2E parallelism needs per-run working trees (a
# follow-up). Per-run PG/Redis above is the isolation this script delivers.

echo "  test-env: applying migrations + content seed..."
( cd "$_te_root" && bun run scripts/migrate.ts )
( cd "$_te_root/scripts" && uv sync && uv run python seed_content.py )

# Keep _te_id/_te_pg_cid/_te_redis_cid/_te_teardown in the caller's shell — the
# caller's EXIT trap needs them. Only the migrate/seed path needed _te_root.
unset _te_root
echo "  test-env: ready (DB :${_te_pg_port}, Redis :${_te_redis_port})."
