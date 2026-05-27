-- story-006: hidden per-player Crafting skill counter (+1 on each crafting Failure).
-- Spec consolation reward, game_mechanics_crafting.md:106. Per-player table carries the
-- players ON DELETE CASCADE FK per decision 63c0372460d7 (no orphan rows).

CREATE TABLE IF NOT EXISTS player_crafting_skill_counter (
  player_id  TEXT PRIMARY KEY REFERENCES players(player_id) ON DELETE CASCADE,
  counter    INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
