-- Player Veil Ward state (Phase 3 / M3.2 — story-002).
-- A Veil Ward locally reinforces the Veil: while active it halves Resonance generation,
-- grants +4 to Hollow Echo rolls, and applies -1 die / -1 DC. The ward state lives in
-- players.data JSONB at {veil_ward}: {active: bool, source: str|null} (no new table),
-- beside {resonance} and hp/focus/stamina. `active` is the authoritative flag the cast
-- path reads to halve generation; `source` is the archetype id that raised the ward.
-- Read (db_mutations_veil_ward.read_player_veil_ward) defaults to inactive when the key
-- is absent, so this backfill is not required for correctness — it seeds the key on
-- existing players so the path is immediately queryable/consistent. Idempotent: only rows
-- lacking the key are touched.

UPDATE players
  SET data = jsonb_set(data, '{veil_ward}', '{"active": false, "source": null}'::jsonb)
  WHERE NOT (data ? 'veil_ward');
