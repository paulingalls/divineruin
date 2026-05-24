-- player_known_recipes (migration 019) declared player_id with no foreign key,
-- so deleting a player orphaned their known-recipe rows (concern fc0ecdcd1766).
-- Restore the migration-008 convention: a players CASCADE FK.
--
-- Scope (decision player-fk-cascade-scope): this corrects player_known_recipes
-- only — the M5.1 table in active development. The same gap is systemic: every
-- per-player table added after migration 008 (009_god_whispers, 012_story_moments,
-- 014_skill_advancement, 016_training_activities, 019_recipes) plus some pre-008
-- ones (003_player_map_progress, tables in 001) also lack the players FK. That
-- broad backfill is deferred to a dedicated FK-consistency migration (debt) rather
-- than bundled here. Safe ALTER: player_known_recipes is new in 019 and only
-- learn_recipe writes it at runtime, so no orphan rows can block the constraint.

ALTER TABLE player_known_recipes
  ADD CONSTRAINT fk_player_known_recipes_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;
