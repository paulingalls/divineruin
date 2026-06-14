-- Player concentration state (Phase 3 / M3.4 — story-002).
-- A caster sustains at most one concentration spell at a time. It lives in players.data JSONB
-- at {concentration,spell_id} (no new table), beside {resonance} and {veil_ward}. `spell_id`
-- (str) is the active concentration spell; NULL means not concentrating. Read
-- (db_mutations_concentration.read_player_concentration) defaults to None when the key is
-- absent, so this backfill is not required for correctness — it seeds the key on existing
-- players so the path is immediately queryable/consistent. Idempotent: only rows lacking the
-- key are touched.

UPDATE players
  SET data = jsonb_set(data, '{concentration}', '{"spell_id": null}'::jsonb)
  WHERE NOT (data ? 'concentration');
