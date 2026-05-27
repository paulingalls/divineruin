#!/usr/bin/env bash
# Provision Postgres + Redis for the test/push gate WITHOUT relying on a dev .env.
#
# SOURCE this (do not exec) so the exported DATABASE_URL/REDIS_URL reach the caller:
#   source scripts/test-env.sh
#
# Idempotent and additive:
#   - If DATABASE_URL is already set (a dev with .env, or CI's service vars), this is
#     a NO-OP — it never overrides an existing environment.
#   - Otherwise it brings up the docker-compose postgres+redis (reusing them if already
#     running), waits for Postgres to report healthy, applies migrations + seeds content,
#     and exports DATABASE_URL/REDIS_URL pointing at those services.
#
# This lets the pre-push hook (and any local test run) provision its own DB instead of
# depending on a sourced .env. Requires Docker (the pre-push hook already hard-gates on it).

if [ -n "${DATABASE_URL:-}" ]; then
  echo "  test-env: DATABASE_URL already set — using the existing environment."
  return 0 2>/dev/null || exit 0
fi

_te_root="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
_te_compose="$_te_root/docker-compose.yml"

# Reachability probe (bash /dev/tcp — no nc dependency).
_te_reachable() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3>&- 3<&-; }

echo "  test-env: DATABASE_URL unset — ensuring postgres (:5433) + redis (:6379)..."
# Bring up ONLY the services not already listening, so we never collide with a
# Postgres/Redis a dev (or a prior run) is already running on these ports.
_te_up=""
_te_reachable 5433 || _te_up="$_te_up postgres"
_te_reachable 6379 || _te_up="$_te_up redis"
if [ -n "$_te_up" ]; then
  # shellcheck disable=SC2086
  docker compose -f "$_te_compose" up -d $_te_up
fi

# If WE started Postgres, wait for it to be query-ready — not merely TCP-listening.
# A cold container maps :5433 before initdb finishes, so a bare TCP probe would let
# migrate.ts connect mid-startup and fail ("the database system is starting up").
# The compose healthcheck is pg_isready, so poll the container's health (up to ~60s).
# A REUSED Postgres (already reachable before we ran) is by definition already ready.
case " $_te_up " in
  *" postgres "*)
    _te_pg_cid="$(docker compose -f "$_te_compose" ps -q postgres)"
    for _ in $(seq 1 60); do
      [ "$(docker inspect -f '{{.State.Health.Status}}' "$_te_pg_cid" 2>/dev/null)" = "healthy" ] && break
      sleep 1
    done
    ;;
esac

# Compose maps postgres to host 5433 with the documented dev credentials/db; redis
# is reused at 6379 (compose or a pre-existing instance — cache, no schema needed).
export DATABASE_URL="postgresql://divineruin:divineruin_dev@localhost:5433/divineruin"
export REDIS_URL="redis://localhost:6379"

echo "  test-env: applying migrations + content seed..."
( cd "$_te_root" && bun run scripts/migrate.ts )
( cd "$_te_root/scripts" && uv sync && uv run python seed_content.py )

unset _te_root _te_compose _te_up _te_pg_cid
echo "  test-env: ready (DATABASE_URL -> :5433, REDIS_URL -> :6379)."
