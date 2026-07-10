-- Loot tables catalog (M4.7 — story-002, Loot & Currency Drops by Role).
-- Seeded from content/loot_tables.json — the single source of truth for role-scaled
-- loot drops. A flat catalog of id/JSONB rows: each row's `drops` is a list of
-- {item_id, chance, quantity} base entries that encounter_loot.derive_role_loot scales
-- by the defeated enemy's encounter role (drop-chance / quantity modifiers). Enemies
-- reference a table by `loot_table_id` (content/encounter_templates.json); multiple
-- enemies may share one shared table, while bosses/named enemies get bespoke tables.
-- combat_end (apps/agent/combat_end.py) resolves the table on victory via
-- db_content_queries.get_loot_table. Reuses set_updated_at() from migration 001,
-- mirroring the settlement_templates / role_archetypes content-catalog tables.

CREATE TABLE IF NOT EXISTS loot_tables (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_loot_tables_updated_at
  BEFORE UPDATE ON loot_tables
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
