#!/usr/bin/env bash
set -uo pipefail
part="$1"
shift
: "${PROOF_E2E_ARTIFACTS:?E2E provider required}"
log="$(mktemp)"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "e2e:$part start $started pid=$$ lane=${PROOF_LANE_SLOT:?} ports=$E2E_API_PORT,$E2E_APP_PORT,$E2E_WEB_PORT,$E2E_LH_DEBUG_PORT" | tee "$log"
# The clone wrapper runs from the snapshot root; Playwright resolves filters in e2e.
bun scripts/proof-db-clone.ts 'cd e2e && bunx playwright test --reporter=list' "$(printf '%q ' "$@")" 2>&1 | tee -a "$log"
status=${PIPESTATUS[0]}
echo "e2e:$part stop $(date -u +%Y-%m-%dT%H:%M:%SZ) pid=$$ status=$status" | tee -a "$log"
if [ "$status" -ne 0 ]; then
  dest="$PROOF_E2E_ARTIFACTS/e2e-$part-$(date +%Y%m%d-%H%M%S)-$$"
  mkdir -p "$dest" && {
    cp "$log" "$dest/run.log" || true
    cp -R e2e/test-results "$dest/test-results" || true
  }
  echo "E2E failure artifacts: $dest" >&2
fi
rm -f "$log"
exit "$status"
