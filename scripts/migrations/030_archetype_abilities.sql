-- Archetype abilities (Phase 2 / M2.2).
-- Seeded from content/archetype_abilities.json — the single source of truth for
-- every archetype's activatable abilities: core actives + casters' fixed core
-- spells (ability_type=core), core reactions (reaction), and L4/L8 elective
-- techniques (elective). Cost is a structured object {stamina, focus, scaling}.
-- Both Python (apps/agent/abilities.py, story-002) and TS (apps/server/src/
-- abilities.ts, story-003) load this table at startup, mirroring the M2.1
-- archetypes table (migration 029). Reuses set_updated_at() from migration 001.

CREATE TABLE IF NOT EXISTS archetype_abilities (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_archetype_abilities_updated_at
  BEFORE UPDATE ON archetype_abilities
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Per-character learned/equipped abilities. Core abilities are always-known
-- (derived from the archetype — no row needed); this table tracks chosen
-- elective techniques (equipped, swappable on long rest) and, later, abilities
-- acquired via training/scrolls/mentors. Written by story-004 (swap on long
-- rest); created here so the loader/tool stories have the schema in place.
-- player_id carries the players(player_id) ON DELETE CASCADE FK that every
-- per-player table follows (migrations 008/020/021, debt ac2ad5230209); deleting
-- a player drops their ability rows. ability_id cascades too: retiring an ability
-- removes the dangling character_abilities rows rather than failing the DELETE.
CREATE TABLE IF NOT EXISTS character_abilities (
  player_id   TEXT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  ability_id  TEXT NOT NULL REFERENCES archetype_abilities(id) ON DELETE CASCADE,
  equipped    BOOLEAN NOT NULL DEFAULT TRUE,
  acquired_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, ability_id)
);

CREATE INDEX IF NOT EXISTS idx_character_abilities_player
  ON character_abilities (player_id);
