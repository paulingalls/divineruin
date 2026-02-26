-- Trigger function to auto-update updated_at on row modification
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Content tables (authored, static)

CREATE TABLE locations (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_locations_updated_at BEFORE UPDATE ON locations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE npcs (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_npcs_updated_at BEFORE UPDATE ON npcs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE items (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_items_updated_at BEFORE UPDATE ON items
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE quests (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_quests_updated_at BEFORE UPDATE ON quests
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE events (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_events_updated_at BEFORE UPDATE ON events
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE factions (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_factions_updated_at BEFORE UPDATE ON factions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE lore_entries (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_lore_entries_updated_at BEFORE UPDATE ON lore_entries
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE encounter_templates (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_encounter_templates_updated_at BEFORE UPDATE ON encounter_templates
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE inventory_pools (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_inventory_pools_updated_at BEFORE UPDATE ON inventory_pools
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE voice_registry (
  character_id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_voice_registry_updated_at BEFORE UPDATE ON voice_registry
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- State tables (live, changing)

CREATE TABLE players (
  player_id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_players_updated_at BEFORE UPDATE ON players
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE player_inventory (
  player_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, item_id)
);
CREATE TRIGGER trg_player_inventory_updated_at BEFORE UPDATE ON player_inventory
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE player_quests (
  player_id TEXT NOT NULL,
  quest_id TEXT NOT NULL,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, quest_id)
);
CREATE TRIGGER trg_player_quests_updated_at BEFORE UPDATE ON player_quests
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE player_reputation (
  player_id TEXT NOT NULL,
  faction_id TEXT NOT NULL,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, faction_id)
);
CREATE TRIGGER trg_player_reputation_updated_at BEFORE UPDATE ON player_reputation
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE npc_dispositions (
  npc_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (npc_id, player_id)
);
CREATE TRIGGER trg_npc_dispositions_updated_at BEFORE UPDATE ON npc_dispositions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE npc_state (
  npc_id TEXT PRIMARY KEY,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_npc_state_updated_at BEFORE UPDATE ON npc_state
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE region_state (
  region_id TEXT PRIMARY KEY,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_region_state_updated_at BEFORE UPDATE ON region_state
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE combat_instances (
  combat_id TEXT PRIMARY KEY,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_combat_instances_updated_at BEFORE UPDATE ON combat_instances
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE world_events_log (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_id TEXT NOT NULL,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  data JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE session_summaries (
  player_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, session_id)
);
CREATE TRIGGER trg_session_summaries_updated_at BEFORE UPDATE ON session_summaries
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE god_agent_state (
  god_id TEXT PRIMARY KEY,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_god_agent_state_updated_at BEFORE UPDATE ON god_agent_state
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE world_flags (
  flag_name TEXT PRIMARY KEY,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_world_flags_updated_at BEFORE UPDATE ON world_flags
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
