-- Hollow-killed mark (Phase 4 / M4.4 — story-007).
-- A character that dies under any Hollowed stage is permanently marked: a divine_revivify cast on
-- the corpse is refused (gm_combat §The Hollowed Death; content/spells.json divine_revivify
-- "Doesn't work on Hollow-killed"). The mark lives in players.data JSONB at {hollow_killed}: bool,
-- beside {death_history}, {maxhp_override}, {conditions} (decision death-system-module-layout — no
-- new table). Read (db_mutations_resurrection.read_hollow_killed) defaults to False when the key is
-- absent, so this backfill is not required for correctness — it seeds the key on existing players so
-- the path is immediately queryable/consistent. Idempotent: only rows lacking the key are touched.

UPDATE players
  SET data = jsonb_set(data, '{hollow_killed}', 'false'::jsonb)
  WHERE NOT (data ? 'hollow_killed');
