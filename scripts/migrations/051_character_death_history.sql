-- Permanent character death history (Phase 4 / M4.4 — story-001).
-- Death always returns the character; the escalating cost is keyed off a permanent death count
-- that never resets (docs/game_mechanics/game_mechanics_combat.md §The Cost Engine). The history
-- lives in players.data JSONB at {death_history}: {"count": int, "costs": [<DeathCost dict>, ...]},
-- beside {conditions}, {resonance}, {veil_ward} (decision death-system-module-layout — no new table).
-- Read (db_mutations_death.read_death_history) defaults to {"count": 0, "costs": []} when the key is
-- absent, so this backfill is not required for correctness — it seeds the key on existing players so
-- the path is immediately queryable/consistent. Idempotent: only rows lacking the key are touched.

UPDATE players
  SET data = jsonb_set(data, '{death_history}', '{"count": 0, "costs": []}'::jsonb)
  WHERE NOT (data ? 'death_history');
