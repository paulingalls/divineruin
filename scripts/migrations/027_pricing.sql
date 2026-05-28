-- M5.4 close-prep: economic pricing SSOT (story-011).
-- pricing is DB-loaded content (content/pricing.json), seeded by
-- scripts/seed_content.py and read by both TS (apps/server/src/pricing.ts) and
-- Python (apps/agent/pricing_queries.py). It holds the cross-language economic
-- constants — repair cost by rarity, disposition price multipliers, silver/gold —
-- that were previously hand-mirrored in durability.py/workspace.py <-> repair.ts.
-- Mirrors the recipes content table (migration 019): id PK + JSONB data + trigger.

CREATE TABLE IF NOT EXISTS pricing (
  id TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_pricing_updated_at
  BEFORE UPDATE ON pricing
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
