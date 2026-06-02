-- Archetype milestones (Phase 2 / M2.3).
-- Seeded from content/archetype_milestones.json — the single source of truth for
-- every archetype's four-tier milestone progression: the Identity (L5)
-- specialization fork plus the Power (L10) / Mastery (L15) / Legend (L20)
-- auto-grants. Records are self-contained (decision 4c0677dae1be): each embeds
-- its granted ability text directly and does NOT FK into archetype_abilities —
-- these grants are passive combat flags / markers (consumed by story-004 and
-- Phase-4 combat), not the activatable abilities that table holds.
--
-- Both Python (apps/agent/milestones.py, story-002) and TS (apps/server/src/
-- milestones.ts, story-003) load this table at startup, mirroring the M2.1
-- archetypes (029) and M2.2 archetype_abilities (030) tables. Specialization
-- choices persist later in players.data JSONB (story-004) — no per-character
-- table is needed here. Reuses set_updated_at() from migration 001.

CREATE TABLE IF NOT EXISTS archetype_milestones (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_archetype_milestones_updated_at
  BEFORE UPDATE ON archetype_milestones
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
