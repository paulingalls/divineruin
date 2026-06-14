-- Player resonance flickering_bonus (Phase 3 / M3.5 — story-001).
-- The Thessyn Deep Adaptation band-shift (+1 Flickering threshold after 10+ sessions) becomes a
-- PERSISTED field at players.data {resonance,flickering_bonus} so read_player_resonance, the cast
-- packet, and a fresh-session hydration all derive one state and cannot diverge. read defaults to
-- 0 when the key is absent, so this backfill is not required for correctness — it seeds the key on
-- existing players so the path is immediately queryable/consistent. Idempotent: only rows lacking
-- the key are touched. Uses the sibling-preserving merge (COALESCE + ||) so `current` survives.

UPDATE players
  SET data = jsonb_set(data, '{resonance}',
        COALESCE(data->'resonance', '{}'::jsonb) || jsonb_build_object('flickering_bonus', 0))
  WHERE NOT (data->'resonance' ? 'flickering_bonus');
