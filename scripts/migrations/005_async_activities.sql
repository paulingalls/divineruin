-- Async activities: timer-based activities that resolve offline
CREATE TABLE async_activities (
  id TEXT PRIMARY KEY,
  player_id TEXT NOT NULL,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_async_activities_player ON async_activities (player_id);
CREATE INDEX idx_async_activities_status ON async_activities ((data->>'status'));
CREATE INDEX idx_async_activities_resolve ON async_activities ((data->>'resolve_at'))
  WHERE data->>'status' = 'in_progress';

CREATE TRIGGER trg_async_activities_updated_at BEFORE UPDATE ON async_activities
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
