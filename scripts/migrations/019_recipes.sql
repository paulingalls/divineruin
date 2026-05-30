-- M5.1 Recipe & Material System schema.
-- recipes + materials_catalog are DB-loaded content (content/recipes.json,
-- content/materials_catalog.json), seeded by scripts/seed_content.py and read by
-- both TS (apps/server/src/recipes.ts) and Python (apps/agent). They mirror the
-- training_content tables (migration 017): id PK + JSONB data + updated_at trigger.
-- recipe_slots is small static reference data (cap per Crafting tier), so it is
-- seeded inline here rather than from a content file. player_known_recipes is
-- per-player state, mirroring skill_advancement (migration 014).

-- Content-config tables (seeded from content/*.json) ------------------------

CREATE TABLE IF NOT EXISTS recipes (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_recipes_updated_at
  BEFORE UPDATE ON recipes
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS materials_catalog (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_materials_catalog_updated_at
  BEFORE UPDATE ON materials_catalog
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Reference table: recipe-slot capacity per Crafting skill tier --------------
-- id = crafting tier; data.max_recipe_tier = highest recipe tier learnable;
-- data.known_recipe_slots = cap, or null for unlimited (Master).
-- Untrained = 3 adopts the spec over the milestone-doc's 0 (decision d25e04f066a3).

CREATE TABLE IF NOT EXISTS recipe_slots (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_recipe_slots_updated_at
  BEFORE UPDATE ON recipe_slots
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO recipe_slots (id, data) VALUES
  ('untrained', '{"max_recipe_tier": "basic",   "known_recipe_slots": 3}'),
  ('trained',   '{"max_recipe_tier": "trained", "known_recipe_slots": 8}'),
  ('expert',    '{"max_recipe_tier": "expert",  "known_recipe_slots": 15}'),
  ('master',    '{"max_recipe_tier": "master",  "known_recipe_slots": null}')
ON CONFLICT (id) DO NOTHING;

-- Per-player state: which recipes a player knows and how they learned them ---
-- learned_via is the acquisition track (training | npc_teaching | discovery |
-- experimentation | tier_advancement); kept as TEXT and validated in code,
-- matching the skill_advancement.tier precedent (migration 014).

CREATE TABLE IF NOT EXISTS player_known_recipes (
  player_id TEXT NOT NULL,
  recipe_id TEXT NOT NULL,
  learned_via TEXT NOT NULL,
  learned_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, recipe_id)
);

CREATE INDEX IF NOT EXISTS idx_player_known_recipes_player ON player_known_recipes (player_id);
