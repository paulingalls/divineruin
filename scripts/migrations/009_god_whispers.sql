CREATE TABLE god_whispers (
  id TEXT PRIMARY KEY,
  player_id TEXT NOT NULL,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_god_whispers_player ON god_whispers (player_id);
