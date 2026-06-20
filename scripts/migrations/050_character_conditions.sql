-- Persistent cross-encounter status conditions (Phase 4 / M4.3 — story-004).
-- Conditions that survive a fight (Wounded/Exhausted/Hollowed — those whose catalog spec marks
-- persists_across_encounters) live in players.data JSONB at {conditions}: a list of condition
-- dicts ({type, duration, source, stacks?, stage?}), beside {resonance}, {veil_ward},
-- {concentration} (decision persistent-conditions-jsonb — no new table). In-combat conditions are
-- NOT here; they ride combat_instances.data via save_combat_state. Read
-- (db_mutations_conditions.read_player_conditions) defaults to [] when the key is absent, so this
-- backfill is not required for correctness — it seeds the key on existing players so the path is
-- immediately queryable/consistent. Idempotent: only rows lacking the key are touched.

UPDATE players
  SET data = jsonb_set(data, '{conditions}', '[]'::jsonb)
  WHERE NOT (data ? 'conditions');
