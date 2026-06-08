/**
 * Anti-silent-skip sentinel shared by the live-DB test lanes.
 *
 * Live-DB suites use `describe.skipIf(!hasDb)` so the env-free unit lane stays
 * green. The danger is the reverse: a lane that is *supposed* to exercise the DB
 * (it sets `REQUIRE_DB=1`, e.g. package.json `test:server`) silently skipping and
 * going green if `DATABASE_URL` ever drifts to unset. Each such lane registers a
 * one-line sentinel test that calls this helper, so the lane fails loud instead.
 *
 * Pure on purpose: throws a plain Error rather than using `expect`, so the shared
 * production package carries no `bun:test` dependency. Callers keep their own
 * `test(...)` wrapper. (Closes concern 6658d858ebb7 — the rule-of-three sentinel
 * duplication across scripts/test_content, apps/server db + locations-load.)
 */
export function assertDbRequired(hasDb: boolean): void {
  if (process.env.REQUIRE_DB && !hasDb) {
    throw new Error(
      "REQUIRE_DB is set but DATABASE_URL is unset — this live-DB lane would silently " +
        "skip its DB tests and go green. Provision DATABASE_URL (scripts/test-env.sh).",
    );
  }
}
