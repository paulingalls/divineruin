-- M5.2 Workspace rentals (sprint-013 story-002). Per-player, LOCATION-BOUND
-- workspace access grants read by the server crafting gate (story-006 REST):
-- accessibleWorkspaceTier(player_id, location_id) in apps/server/src/workspace.ts.
-- A rental grants access only at location_id; expires_at NULL = standing/permanent,
-- non-NULL = a timed rental (active while expires_at > NOW()). Surrogate id PK so a
-- re-rent appends a new row rather than overwriting history (mirrors async_activities).
--
-- Per-player table, so it carries the players(player_id) ON DELETE CASCADE FK that
-- every per-player table must (migration 021 backfilled the rest). New table — no
-- orphan rows can exist, so no pre-ALTER DELETE is needed. workspace_type/source
-- stay TEXT validated in code (parseWorkspaceType), mirroring skill_advancement.tier
-- / player_known_recipes.learned_via — not DB-constrained enums.
--
-- The write path (the "rent a workspace" mutation) is owned by story-004; it adds
-- any pricing/audit columns (daily_cost, rental_start) it needs via a later
-- forward-only migration. Forward-only (no down-migration), per convention.

CREATE TABLE IF NOT EXISTS workspace_rentals (
  id TEXT PRIMARY KEY,
  player_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  workspace_type TEXT NOT NULL,
  source TEXT NOT NULL,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE workspace_rentals
  ADD CONSTRAINT fk_workspace_rentals_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

-- accessibleWorkspaceTier filters by (player_id, location_id) then expiry.
CREATE INDEX IF NOT EXISTS idx_workspace_rentals_player_location
  ON workspace_rentals (player_id, location_id);
