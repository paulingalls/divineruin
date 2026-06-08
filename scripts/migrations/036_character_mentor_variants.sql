-- Character mentor variants — unlocked variants + in-flight training (Phase 2 / M9 — story-002).
-- Mirrors migration 033 (character_spells + spell_learning_progress) for the Martial Mentor
-- System. character_mentor_variants is the unlocked set (one row per player per unlocked
-- variant); mentor_variant_learning_progress tracks the multi-session mentor loop in discrete
-- cycles. variant_id references the mentor_variants catalog (migration 035).
--
-- last_activity_id makes cycle accrual idempotent under a worker retry (debt b20815f92023):
-- the worker advances a cycle in the completion block BEFORE narration, so an LLM-narration
-- failure + retry would otherwise re-advance. advance_learning_cycle increments only for a
-- NEW activity id. The same column is backported to spell_learning_progress here so the spell
-- training track gets the same guard.

CREATE TABLE IF NOT EXISTS character_mentor_variants (
  player_id            TEXT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  variant_id           TEXT NOT NULL REFERENCES mentor_variants(id) ON DELETE CASCADE,
  acquisition_track    TEXT NOT NULL,
  midpoint_decision_id TEXT,
  date_unlocked        TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, variant_id)
);

CREATE TABLE IF NOT EXISTS mentor_variant_learning_progress (
  player_id            TEXT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  variant_id           TEXT NOT NULL REFERENCES mentor_variants(id) ON DELETE CASCADE,
  cycles_completed     INTEGER NOT NULL DEFAULT 0,
  cycles_required      INTEGER NOT NULL,
  midpoint_decision_id TEXT,
  last_activity_id     TEXT,
  started_at           TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, variant_id)
);

ALTER TABLE spell_learning_progress ADD COLUMN IF NOT EXISTS last_activity_id TEXT;
