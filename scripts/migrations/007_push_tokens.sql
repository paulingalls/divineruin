-- Push notification tokens for Expo push service
CREATE TABLE push_tokens (
  player_id TEXT NOT NULL,
  token TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'unknown',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, token)
);
