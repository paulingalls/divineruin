-- Companions catalog + per-player relationship state (Phase 6 / M6.4 — story-002).
-- companions is seeded from content/companions.json — the single source of truth for the 4
-- companions (Kael/Lira/Tam/Sable): narrative subset, typed ability buckets, and scaling_rules.
-- A flat id/JSONB catalog mirroring role_archetypes (migration 039) and settlement_templates
-- (migration 040). The agent (apps/agent/companion_profiles.py) loads it at startup, fail-loud,
-- and scale_companion_stats_to_player_level reads scaling_rules to derive per-level stats.
--
-- companion_relationships is per-player runtime state (NOT content-seeded): the named
-- relationship tier (stored as an int 1-5; story-003 maps it to New/Warming/Trusted/Bonded/
-- Legendary), session count driving tier advancement, and session memories. story-003 reads
-- and writes it; story-002 only creates the table. Reuses set_updated_at() from migration 001.

CREATE TABLE IF NOT EXISTS companions (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_companions_updated_at
  BEFORE UPDATE ON companions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS companion_relationships (
  player_id TEXT NOT NULL,
  companion_id TEXT NOT NULL,
  relationship_tier INT NOT NULL DEFAULT 1,
  session_count INT NOT NULL DEFAULT 0,
  session_memories JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, companion_id)
);

CREATE TRIGGER update_companion_relationships_updated_at
  BEFORE UPDATE ON companion_relationships
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_companion_relationships_player
  ON companion_relationships (player_id);
