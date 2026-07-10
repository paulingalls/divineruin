-- Scope-owned Veil Wards (Phase 4 / M24 — sprint-040 story-003).
-- A Veil Ward belongs to a SCOPE, never to a caster: its effects apply to every caster in
-- that scope, while Resonance and Hollow Echo stay per-caster. See
-- docs/game_mechanics/veil_ward_scope_model.md (settled in story-001).
--
-- This table is the home of LOCATION-scoped wards only. ENCOUNTER-scoped wards ride
-- CombatState inside combat_instances.data JSONB (the combat row's deletion IS the
-- encounter duration), per the settled combat-persistence-jsonb-ssot constraint. One home
-- each, no dual state — db_mutations_veil_ward fails loud if handed an encounter scope.
--
-- Columns:
--   ward_id     surrogate PK; the DB generates it (mirrors 004_auth_tables), so writers
--               never supply one.
--   scope_kind  'location' (the only kind persisted here) — carried so the row is
--               self-describing and the encounter/location split stays legible.
--   scope_id    the location id the ward covers.
--   source      the archetype/entity that raised it (cleric, druid, artificer, sacred_site).
--   expires_at  absolute expiry compared to NOW() at read time (the workspace_rentals
--               pattern). NULL = no absolute expiry. Expiry is LAZY: nothing sweeps this
--               table; a read simply does not return an expired row, so M24 needs no
--               world-clock tick loop.
--   dismissible ORTHOGONAL to expires_at, and that is the whole point. Both a Cleric's
--               out-of-combat ward ("until dismissed") and a Sacred site ("permanent") carry
--               expires_at NULL, but only the Cleric's may be dismissed. Deriving
--               dismissibility from expires_at would let a party dispel a Sacred site.
--
-- (scope_kind, scope_id) is a NON-UNIQUE lookup index on purpose: many wards may cover one
-- scope. Were it unique, deploying the Artificer's 1-hour small anchor at a Sacred site
-- would overwrite the permanent row and silently drop the ward an hour later. Resolution is
-- a boolean OR over covering rows (scope_model §3), so coexistence is free.

CREATE TABLE IF NOT EXISTS veil_wards (
  ward_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_kind  TEXT NOT NULL,
  scope_id    TEXT NOT NULL,
  source      TEXT NOT NULL,
  expires_at  TIMESTAMPTZ,
  dismissible BOOLEAN NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_veil_wards_scope ON veil_wards (scope_kind, scope_id);

-- Retire the per-player ward flag that migration 045 seeded at players.data {veil_ward}.
-- This is the FIRST migration in this codebase to REMOVE a key from players.data — every
-- prior migration only added them. Idempotent via the `WHERE data ? 'key'` guard: the house
-- backfill idiom, inverted.
--
-- No ward state is carried forward. A boolean with no scope and no duration cannot be mapped
-- onto a scoped, duration-bound ward, and wards are ephemeral by design. There is no
-- dual-state window: after this migration players.data.veil_ward does not exist and nothing
-- reads it.
--
-- NOTE for local dev: the fast-lane veil_wards round-trip test needs this migration applied
-- to the dev DB at :55432 — run `bun run migrate` first. CI does this before both test lanes.
UPDATE players SET data = data - 'veil_ward' WHERE data ? 'veil_ward';
