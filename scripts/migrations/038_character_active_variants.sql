-- Character active variants — which unlocked mentor variant currently overrides a base
-- technique on activation (Phase 2 / M9 — story-003).
--
-- A player may unlock several variants of the same base technique over time (the unlocked
-- SET lives in character_mentor_variants, migration 036), but only ONE can be active on a
-- given technique at a time. The PRIMARY KEY (player_id, ability_id) enforces that invariant
-- by construction: set_active_variant upserts ON CONFLICT (player_id, ability_id), so training
-- a second variant for the same technique REPLACES the active one (one variant per technique;
-- swap requires re-training). The async worker sets the active variant when training completes
-- (async_worker_training promotion), and request_ability_activation reads it to override the
-- base technique's cost/effect/narration.

CREATE TABLE IF NOT EXISTS character_active_variants (
  player_id   TEXT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
  ability_id  TEXT NOT NULL REFERENCES archetype_abilities(id) ON DELETE CASCADE,
  variant_id  TEXT NOT NULL REFERENCES mentor_variants(id) ON DELETE CASCADE,
  activated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (player_id, ability_id)
);
