-- Racial Resonance bonus table (Phase 3 / M3.4 — story-001).
-- Seeded from content/racial_resonance_bonuses.json — the single source of truth for the
-- six races' mechanically distinct relationships with Resonance (spec magic.md 221-293).
-- Per the Phase-3 audit guidance the racial layer lives in its OWN seeded table, decoupled
-- from creation_races.RaceData, so RaceData stays lean. Loaded at agent + async-worker
-- startup by apps/agent/racial_resonance.load_racial_resonance(); the data JSONB is the
-- heterogeneous per-race modifier map (each race carries only its own keys). Mirrors the
-- M8 spells table (migration 032). Seeding is scripts/seed_content.py's job (TABLE_MAP),
-- not this migration. Reuses set_updated_at() from migration 001.

CREATE TABLE IF NOT EXISTS racial_resonance_bonuses (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_racial_resonance_bonuses_updated_at
  BEFORE UPDATE ON racial_resonance_bonuses
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
