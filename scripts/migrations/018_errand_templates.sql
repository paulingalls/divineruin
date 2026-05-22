-- Errand templates table: companion-errand config (durations, valid destinations,
-- companion restrictions). Seeded from content/errand_templates.json.
-- Both Python (errand_tools / db_content_queries) and TS (activity_templates,
-- errand_risk) load these at startup, replacing the previously TS-only hardcoded
-- ERRAND_TEMPLATES / COMPANION_BLOCKED_ERRAND_TYPES.

CREATE TABLE IF NOT EXISTS errand_templates (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_errand_templates_updated_at
  BEFORE UPDATE ON errand_templates
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
