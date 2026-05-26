-- M5.3 Quality Outcomes & Experimentation: per-category bonus-property + flaw tables.
-- quality_outcomes is DB-loaded content (content/quality_outcomes.json), seeded by
-- scripts/seed_content.py. Per decision quality-outcomes-storage it is Python-only:
-- the Python rules engine (apps/agent/quality_outcomes.py) resolves quality; no TS
-- consumer reads it, so no TS accessor is built. Mirrors the recipes content table
-- (migration 019): id PK (the crafting category) + JSONB data + updated_at trigger.

CREATE TABLE IF NOT EXISTS quality_outcomes (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_quality_outcomes_updated_at
  BEFORE UPDATE ON quality_outcomes
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
