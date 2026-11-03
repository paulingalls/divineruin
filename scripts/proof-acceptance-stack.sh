#!/usr/bin/env bash
set -euo pipefail
exec uv run --frozen --directory apps/agent python ../../scripts/proof_acceptance_stack.py "$@"
