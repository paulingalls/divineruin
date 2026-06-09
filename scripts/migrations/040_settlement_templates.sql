-- Settlement templates catalog (Phase 6 / M6.2 — story-002).
-- Seeded from content/settlement_templates.json — the single source of truth for
-- settlement population templates. A flat catalog of id/JSONB rows discriminated by a
-- `kind` field: tier rows (id = SettlementSize: hamlet/village/town/city) carry per-role
-- {min,max} count ranges; personality rows (id = trait) carry role-frequency and
-- disposition modifiers, a price multiplier, and a description. The agent
-- (apps/agent/settlement_templates.py) loads this table at startup, fail-loud, mirroring
-- the role_archetypes table (migration 039). story-003 consumes it to generate scaled,
-- personality-flavored NPC populations. Reuses set_updated_at() from migration 001.

CREATE TABLE IF NOT EXISTS settlement_templates (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_settlement_templates_updated_at
  BEFORE UPDATE ON settlement_templates
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
