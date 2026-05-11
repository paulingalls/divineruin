-- Training content tables: activity types (mechanic) and programs (menu)
-- Seeded from content/training_activity_types.json and content/training_programs.json.
-- Both Python (training_rules) and TS (training_state_machine) load these at startup,
-- replacing the previously duplicated hardcoded configs.

CREATE TABLE IF NOT EXISTS training_activity_types (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_training_activity_types_updated_at
  BEFORE UPDATE ON training_activity_types
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS training_programs (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_training_programs_updated_at
  BEFORE UPDATE ON training_programs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
