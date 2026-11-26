CREATE TABLE hollowed_hallucinations (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_hollowed_hallucinations_updated_at
  BEFORE UPDATE ON hollowed_hallucinations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
