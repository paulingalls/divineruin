-- Spell catalog (Phase 2 / M8 — story-001).
-- Seeded from content/spells.json — the single source of truth for the ELECTIVE
-- spell library, keyed by magic source (arcane/divine/primal). Caster CORE spells
-- stay archetype_abilities rows (ability_type=core, seam 235ae150c5d3); this table
-- holds only the learnable elective catalog. Borrows Phase-3 Magic's M3.3 schema
-- minimally (the JSONB data column is forward-compatible with the full catalog's
-- resonance_by_source / terrain_effects / audio_cue / concentration fields).
-- Both Python (apps/agent/spells.py) and TS (apps/server/src/spells.ts) load this
-- table at startup, mirroring the M2.2 archetype_abilities table (migration 030).
-- character_spells + spell_learning_progress land in migration 033 (story-002).
-- Reuses set_updated_at() from migration 001.

CREATE TABLE IF NOT EXISTS spells (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_spells_updated_at
  BEFORE UPDATE ON spells
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
