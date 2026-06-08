-- Per-character spell state (Phase 2 / M8 — story-002).
-- character_spells: the known ELECTIVE spell library (which spells a character has
-- learned + which are prepared). spell_learning_progress: in-flight training toward
-- an elective spell, counted in discrete cycles (the cycles=counts model; story-004
-- wires the async accrual). Caster CORE spells stay archetype_abilities rows
-- (ability_type=core, seam 235ae150c5d3) — not tracked here.
-- Mirrors the M2.2 character_abilities table (migration 030): relational typed
-- columns, players(player_id) + spells(id) FKs ON DELETE CASCADE, per-player index.
-- Written by apps/agent/character_spells.py. acquisition_track is validated in
-- Python ({training, discovery, npc_teaching}) — no DB CHECK, matching the house pattern.

CREATE TABLE IF NOT EXISTS character_spells (
  player_id         TEXT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  spell_id          TEXT NOT NULL REFERENCES spells(id) ON DELETE CASCADE,
  acquisition_track TEXT NOT NULL,
  is_prepared       BOOLEAN NOT NULL DEFAULT FALSE,
  date_learned      TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, spell_id)
);

CREATE INDEX IF NOT EXISTS idx_character_spells_player
  ON character_spells (player_id);

-- One in-flight learning row per (player, spell). Promoted into character_spells by
-- the caller (story-004) when cycles_completed reaches cycles_required, then deleted.
CREATE TABLE IF NOT EXISTS spell_learning_progress (
  player_id            TEXT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  spell_id             TEXT NOT NULL REFERENCES spells(id) ON DELETE CASCADE,
  cycles_completed     INTEGER NOT NULL DEFAULT 0,
  cycles_required      INTEGER NOT NULL,
  midpoint_decision_id TEXT,
  started_at           TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, spell_id)
);

CREATE INDEX IF NOT EXISTS idx_spell_learning_progress_player
  ON spell_learning_progress (player_id);
