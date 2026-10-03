#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec bun apps/mobile/scripts/verify-choir-encounter.ts
