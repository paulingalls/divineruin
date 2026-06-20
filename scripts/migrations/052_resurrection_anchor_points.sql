-- Resurrection anchor + cost state (Phase 4 / M4.4 — story-003).
-- Seeds two players.data JSONB keys the resurrection loop reads/writes (decision
-- death-system-module-layout — no new table):
--   maxhp_override           -- negative int, the death-7+ -1-maxHP-per-level fraying (0 = none)
--   last_rested_settlement_id -- anchor tier-3 (null until a long-rest caller writes it; forward-seam)
-- Reads default these (apply_maxhp_override_delta COALESCEs to 0; read_last_rested defaults None),
-- so this backfill is not required for correctness — it seeds the keys on existing players so the
-- path is immediately consistent/queryable. Idempotent: only rows lacking a key are touched.

UPDATE players
  SET data = jsonb_set(data, '{maxhp_override}', '0'::jsonb)
  WHERE NOT (data ? 'maxhp_override');

UPDATE players
  SET data = jsonb_set(data, '{last_rested_settlement_id}', 'null'::jsonb)
  WHERE NOT (data ? 'last_rested_settlement_id');
