CREATE TABLE player_map_progress (
  player_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, location_id)
);
CREATE TRIGGER trg_player_map_progress_updated_at BEFORE UPDATE ON player_map_progress
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
