-- M5.3 Experimentation: remember material combinations that produce nothing.
-- Per-player state (mirrors player_known_recipes, migration 019/020). Records ONLY
-- no-match combinations (no recipe produces the intended output) so the player isn't
-- prompted to fruitlessly repeat them; a roll-failure on a real recipe is retryable and
-- is NOT recorded (decision experimentation-dedup-no-match-only). The composite PK is the
-- dedup key. players ON DELETE CASCADE FK per decision 63c0372460d7.

CREATE TABLE IF NOT EXISTS player_failed_experiments (
  player_id TEXT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  intended_output TEXT NOT NULL,
  material_combination TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, intended_output, material_combination)
);

CREATE INDEX IF NOT EXISTS idx_player_failed_experiments_player
  ON player_failed_experiments (player_id);
