-- Mentor variants catalog (Phase 2 / M9 — story-001).
-- Seeded from content/mentor_variants.json — the single source of truth for the
-- martial style-variant library: a mentor-taught variant of a base elective
-- technique that overrides the technique's cost/effect/narration on activation
-- and carries a cultural-attribution string for the DM voice. Keyed by a globally
-- unique variant id (<ability_id>_<culture_slug>); the base ability_id and
-- teaching mentor_id live inside the JSONB data column. Both Python
-- (apps/agent/mentor_variants.py) and TS (apps/server/src/mentor_variants.ts) load
-- this table at startup, mirroring the M8 spells table (migration 032).
-- Character-state tables (the unlocked-variant rows + multi-session learning
-- progress) land in a later migration with story-002. Reuses set_updated_at()
-- from migration 001.

CREATE TABLE IF NOT EXISTS mentor_variants (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_mentor_variants_updated_at
  BEFORE UPDATE ON mentor_variants
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
