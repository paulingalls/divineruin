-- Player Resonance state (Phase 3 / M3.1 — story-002).
-- Resonance is the hidden per-caster stat the M3.1 system tracks. It lives in
-- players.data JSONB at {resonance,current} (no new table), beside hp/focus/stamina.
-- Only `current` (the authoritative int) is stored; the stable/flickering/overreach
-- STATE is re-derived at read time via apps/agent/resonance.get_resonance_state
-- (single source of truth, no drift). Read (db_mutations_resonance.read_player_resonance)
-- defaults to current 0 when the key is absent, so this backfill is not required for
-- correctness — it seeds the key on existing players so the path is immediately
-- queryable/consistent. Idempotent: only rows lacking the key are touched.

UPDATE players
  SET data = jsonb_set(data, '{resonance}', '{"current": 0}'::jsonb)
  WHERE NOT (data ? 'resonance');
