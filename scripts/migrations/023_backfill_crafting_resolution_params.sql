-- Backfill the story-005 resolution gate inputs onto in-flight crafting activities
-- (story-005). resolve_crafting now FAILS LOUD (raises) if an in_progress crafting
-- activity's parameters lack workspace_required / workspace_access / crafting_tier /
-- tainted_materials, and the async worker reverts-and-reraises on that exception
-- (infinite retry). Activities created before this change — by either the Python
-- tool path or the live TS REST path — predate those keys, so without this backfill
-- they would wedge the worker the moment story-005 ships.
--
-- A fresh DB has no in_progress crafting rows, so this is a no-op there; on a
-- deployed DB it rewrites exactly the at-risk rows. Idempotent: the `||` merge just
-- overwrites the four keys, so re-running is safe. Forward-only (no down-migration).
--
-- Value sourcing:
--   workspace_required  <- recipes.data->>'workspace_required' (the recipe's requirement)
--   tainted_materials   <- recipes.data->'tainted_materials' (ARROW, not ->>, to keep
--                          the JSON boolean — a stringified "true"/"false" would always
--                          be truthy and break the tainted gate)
--   crafting_tier       <- the player's CURRENT crafting tier (skill_advancement),
--                          defaulting to 'untrained'. Historical tier-at-creation is
--                          unrecoverable; current tier is the honest best-effort for a
--                          one-time backfill (mirrors the producers' default).
--   workspace_access    <- LENIENT: {field, workspace_required}, sorted+deduped to match
--                          the producers' sorted(accessible) shape. These crafts were
--                          accepted before the gate existed; granting access to the
--                          required workspace lets them complete rather than retroactively
--                          failing on a gate they could not anticipate. (New crafts get
--                          the player's real accessible set from the producers.)
--
-- Recipe join is an INNER join on recipes: an in-flight craft whose recipe_id no longer
-- matches a recipe row (deleted content — content is append-only, so this is effectively
-- impossible) is skipped and will fail loud at resolution. Accepted edge.

UPDATE async_activities a
SET data = jsonb_set(
  a.data,
  '{parameters}',
  (a.data -> 'parameters') || jsonb_build_object(
    'workspace_required', r.data ->> 'workspace_required',
    'workspace_access', (
      SELECT jsonb_agg(DISTINCT w ORDER BY w)
      FROM unnest(ARRAY['field', r.data ->> 'workspace_required']) AS t(w)
    ),
    'crafting_tier', COALESCE(
      (SELECT sa.tier FROM skill_advancement sa
       WHERE sa.player_id = a.player_id AND sa.skill_id = 'crafting'),
      'untrained'
    ),
    'tainted_materials', COALESCE(r.data -> 'tainted_materials', 'false'::jsonb)
  )
)
FROM recipes r
WHERE a.data ->> 'activity_type' = 'crafting'
  AND a.data ->> 'status' = 'in_progress'
  AND r.id = a.data -> 'parameters' ->> 'recipe_id';
