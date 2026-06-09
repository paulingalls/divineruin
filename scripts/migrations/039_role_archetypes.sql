-- Role archetypes catalog (Phase 6 / M6.1 — story-001).
-- Seeded from content/role_archetypes.json — the single source of truth for the
-- NPC role-archetype templates: per-archetype combat stats (inlined; no
-- CreatureStatBlock until Phase 7 Bestiary), services, inventory pool, knowledge
-- domains, and disposition baseline. Keyed by a globally unique archetype id
-- (e.g. guard, merchant_alchemist); the full template lives in the JSONB data
-- column. Both Python (apps/agent/role_archetypes.py, story-002) and TS
-- (apps/server/src/role_archetypes.ts, story-003) load this table at startup,
-- mirroring the M9 mentor_variants table (migration 035). Reuses set_updated_at()
-- from migration 001.

CREATE TABLE IF NOT EXISTS role_archetypes (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_role_archetypes_updated_at
  BEFORE UPDATE ON role_archetypes
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
