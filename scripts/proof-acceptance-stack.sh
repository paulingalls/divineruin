#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
if uv sync --check --frozen --project apps/agent; then
  exec uv run --no-sync --frozen --directory apps/agent python ../../scripts/proof_acceptance_stack.py "$@"
fi
provider_env="$(mktemp -d)"
trap 'rm -rf -- "$provider_env"' EXIT
UV_NO_SYNC=0 UV_PROJECT_ENVIRONMENT="$provider_env/.venv" \
  uv run --frozen --directory apps/agent env -u UV_PROJECT_ENVIRONMENT python ../../scripts/proof_acceptance_stack.py "$@"
