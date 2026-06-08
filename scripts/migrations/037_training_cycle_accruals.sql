-- Worker accrual idempotency ledger (Phase 2 / M9 — story-002, debt b20815f92023).
-- The async worker applies a training activity's completion accrual BEFORE narration;
-- an LLM-narration failure + retry would re-run the accrual. Cycle-based tracks
-- (spell, mentor variant) guard this with last_activity_id on their progress rows.
-- skill_practice has no per-cycle progress row — it increments a shared skill_advancement
-- counter (also written by the live check() session-use path), so it can't reuse that
-- guard. This ledger is a worker-owned claim: apply_skill_practice_advancement claims the
-- activity_id once (INSERT ... ON CONFLICT DO NOTHING) and applies the counter increment
-- only on a fresh claim, so a retry of the same completion is a no-op.

CREATE TABLE IF NOT EXISTS training_cycle_accruals (
  activity_id TEXT PRIMARY KEY,
  applied_at  TIMESTAMPTZ DEFAULT NOW()
);
