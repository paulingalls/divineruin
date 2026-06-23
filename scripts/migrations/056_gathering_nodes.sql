-- Gathering nodes catalog/state (Phase 4 / M4.6c — story-002, Gathering & Resource Discovery).
-- Seeded from content/gathering_nodes.json — the fixed gathering nodes the spec places at
-- specific locations (ore vein, herb garden, crystal deposit, timber stand, salvage site,
-- hollow residue pool). A flat catalog of id/JSONB rows: each row's `data` is
-- {location_id, node_type, resource_type, quantity, discovered, respawn_days}. `quantity` and
-- `discovered` are mutable world state — story-003's gathering tool depletes quantity and marks
-- discovered via jsonb_set; `respawn_days` is static cadence config the M16 world-sim respawn
-- tick consumes (positive N = respawn over N in-game days, 0 = one-time, -1 = persistent).
-- Reuses set_updated_at() from migration 001, mirroring the loot_tables / settlement_templates
-- content-catalog tables.

CREATE TABLE IF NOT EXISTS gathering_nodes (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_gathering_nodes_updated_at
  BEFORE UPDATE ON gathering_nodes
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
