-- Archetype chassis table (Phase 2 / M2.1).
-- Seeded from content/archetypes.json — the single source of truth for the 18
-- archetype chassis (HP, resource formulas, save/armor/weapon proficiencies,
-- starting skills), folding the previously scattered ARCHETYPE_HP_CONFIG
-- (hp_scaling), ARCHETYPE_RESOURCE_CONFIG (rules_engine), and CLASSES
-- (creation_classes) code constants into one DB-loaded content config.
-- Both Python (apps/agent/archetypes.py) and TS (apps/server/src/archetypes.ts)
-- load this at startup (constraint 8508fdb1abc3, wisdom bb73edd9b94d).

CREATE TABLE IF NOT EXISTS archetypes (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_archetypes_updated_at
  BEFORE UPDATE ON archetypes
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
