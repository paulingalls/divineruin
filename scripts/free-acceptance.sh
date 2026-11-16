#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

export ALLOW_PAID_TESTS= REQUIRE_REAL_LLM=
export REQUIRE_DOCKER=1 TESTCONTAINERS_RYUK_DISABLED=true
unset DATABASE_URL REDIS_URL

bunx proof run --staged --set land
bunx proof run --staged --set sprint
