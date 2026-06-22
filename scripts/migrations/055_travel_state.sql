-- Player travel state (Phase 4 / M4.6b — story-002).
-- A travelling party's in-flight journey state lives in players.data JSONB at {travel_state}:
-- null when not travelling, or a dict (current route/mode/progress) once story-003's travel tool
-- begins a segment (gm_combat §Travel and Exploration). It sits beside {death_history},
-- {maxhp_override}, {hollow_killed}, {conditions} — no new table, mirroring the death-system layout.
-- The travel tool reads null-as-not-travelling, so this backfill is not required for correctness —
-- it seeds the key on existing players so the path is immediately queryable/consistent. Idempotent:
-- only rows lacking the key are touched.

UPDATE players
  SET data = jsonb_set(data, '{travel_state}', 'null'::jsonb)
  WHERE NOT (data ? 'travel_state');
