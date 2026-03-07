-- World news items generated from world simulation events
CREATE TABLE world_news_items (
  id TEXT PRIMARY KEY,
  player_id TEXT NOT NULL,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_world_news_player ON world_news_items (player_id);
CREATE INDEX idx_world_news_created ON world_news_items (created_at);
