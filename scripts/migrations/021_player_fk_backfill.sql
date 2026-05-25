-- Systemic players CASCADE-FK backfill (debt ac2ad5230209, deferred by migration
-- 020's header). Migrations 008 (async_activities, world_news_items, push_tokens)
-- and 020 (player_known_recipes) added players(player_id) ON DELETE CASCADE FKs,
-- but every other per-player table added before/since lacked it — so deleting a
-- player orphaned their rows instead of cascading. This closes the gap for the
-- remaining ten tables.
--
-- Each table: DELETE orphan rows (player_id with no matching players row) BEFORE
-- the ALTER. A fresh DB has no rows, so the DELETE is a no-op; on a deployed DB
-- holding orphans tied to already-hard-deleted players, those rows are exactly
-- what the CASCADE would have removed — clearing them lets the constraint add
-- succeed (an un-cleared orphan would fail the ALTER). Mirrors migration 020's
-- pattern. Forward-only (no down-migration), per convention.

-- migration 001 per-player tables
DELETE FROM player_inventory WHERE player_id NOT IN (SELECT player_id FROM players);
ALTER TABLE player_inventory
  ADD CONSTRAINT fk_player_inventory_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

DELETE FROM player_quests WHERE player_id NOT IN (SELECT player_id FROM players);
ALTER TABLE player_quests
  ADD CONSTRAINT fk_player_quests_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

DELETE FROM player_reputation WHERE player_id NOT IN (SELECT player_id FROM players);
ALTER TABLE player_reputation
  ADD CONSTRAINT fk_player_reputation_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

DELETE FROM npc_dispositions WHERE player_id NOT IN (SELECT player_id FROM players);
ALTER TABLE npc_dispositions
  ADD CONSTRAINT fk_npc_dispositions_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

DELETE FROM session_summaries WHERE player_id NOT IN (SELECT player_id FROM players);
ALTER TABLE session_summaries
  ADD CONSTRAINT fk_session_summaries_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

-- later per-player tables (003, 009, 012, 014, 016)
DELETE FROM player_map_progress WHERE player_id NOT IN (SELECT player_id FROM players);
ALTER TABLE player_map_progress
  ADD CONSTRAINT fk_player_map_progress_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

DELETE FROM god_whispers WHERE player_id NOT IN (SELECT player_id FROM players);
ALTER TABLE god_whispers
  ADD CONSTRAINT fk_god_whispers_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

DELETE FROM story_moments WHERE player_id NOT IN (SELECT player_id FROM players);
ALTER TABLE story_moments
  ADD CONSTRAINT fk_story_moments_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

DELETE FROM skill_advancement WHERE player_id NOT IN (SELECT player_id FROM players);
ALTER TABLE skill_advancement
  ADD CONSTRAINT fk_skill_advancement_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

DELETE FROM training_activities WHERE player_id NOT IN (SELECT player_id FROM players);
ALTER TABLE training_activities
  ADD CONSTRAINT fk_training_activities_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;
