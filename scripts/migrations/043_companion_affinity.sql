-- Companion relationship affinity (Phase 6 / M6.4 — story-003, HYBRID model).
-- companion_relationships (migration 042) gets an `affinity` column: the accumulated errand
-- relationship_change (+1/0/-1), clamped >= 0. The HYBRID relationship tier = a floor derived
-- from session_count (spec session bands) nudged UP by at most one band when affinity is strong
-- (apps/agent/companion_relationship.py:effective_tier_rank). The existing relationship_tier
-- column is kept as a denormalized cache of the effective rank for external readers (HUD,
-- debugging) — the agent re-derives the rank from session_count + affinity on every read and
-- never trusts the cached column. session_count + affinity are the authoritative inputs.

ALTER TABLE companion_relationships
  ADD COLUMN IF NOT EXISTS affinity INT NOT NULL DEFAULT 0;
