-- Index on training_cycle_accruals.applied_at (Phase 6 sprint-010 / story-007).
-- prune_training_cycle_accruals (apps/agent/db_training.py) filters
-- `WHERE applied_at < NOW() - make_interval(days => $1)` every worker maintenance cycle. A
-- btree index on applied_at turns that DELETE's scan into an index range scan instead of a
-- sequential scan (close-review concern 21421dd79d88). The prune keeps the table small in
-- steady state, so this is cheap future-proofing — most valuable on the first prune against
-- the historically-unbounded ledger. Plain CREATE INDEX (not CONCURRENTLY): the migration
-- runner wraps each file in a transaction, and the table is small.

CREATE INDEX IF NOT EXISTS idx_training_cycle_accruals_applied_at
  ON training_cycle_accruals (applied_at);
