CREATE TABLE IF NOT EXISTS story_moments (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  session_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  moment_key TEXT NOT NULL,
  description TEXT NOT NULL,
  template_id TEXT NOT NULL,
  asset_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_story_moments_session ON story_moments (session_id);
