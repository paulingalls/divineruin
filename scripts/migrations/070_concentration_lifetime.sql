-- Existing concentration spells get a fresh lifetime from the migration boundary.
WITH combat_origins AS (
    SELECT DISTINCT ON (participant->>'id')
           participant->>'id' AS player_id,
           jsonb_build_object(
               'combat_id', combat_id,
               'started_round', COALESCE(data->'wrap_continuation'->'outgoing_round', data->'round_number')
           ) AS origin
    FROM combat_instances
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(data->'participants') = 'array' THEN data->'participants' ELSE '[]'::jsonb END
    ) AS participant
    WHERE participant->>'type' = 'player'
    ORDER BY participant->>'id', updated_at DESC, combat_id
), legacy AS (
    SELECT players.player_id, (players.data->'concentration') || '{"elapsed_seconds":0}'::jsonb
           || COALESCE(combat_origins.origin, '{}'::jsonb) AS concentration
    FROM players LEFT JOIN combat_origins USING (player_id)
    WHERE players.data->'concentration'->>'spell_id' IS NOT NULL
      AND NOT (players.data->'concentration' ? 'elapsed_seconds')
)
UPDATE players SET data = jsonb_set(data, '{concentration}', legacy.concentration)
FROM legacy WHERE players.player_id = legacy.player_id;

CREATE FUNCTION pg_temp.concentration_lifetime_checkpoint(checkpoint jsonb) RETURNS jsonb
LANGUAGE SQL IMMUTABLE AS $$
    SELECT CASE WHEN jsonb_typeof(checkpoint->'players') = 'object'
        THEN jsonb_set(checkpoint, '{players}', (
            SELECT COALESCE(jsonb_object_agg(player_id,
                CASE WHEN image->'data'->'concentration'->>'spell_id' IS NOT NULL
                       AND NOT (image->'data'->'concentration' ? 'elapsed_seconds')
                    THEN jsonb_set(image, '{data,concentration}',
                        (image->'data'->'concentration') || jsonb_build_object(
                            'elapsed_seconds', 0,
                            'combat_id', checkpoint->'combat_id',
                            'started_round', checkpoint->'round_number'
                        ))
                    ELSE image END), '{}'::jsonb)
            FROM jsonb_each(checkpoint->'players') AS entries(player_id, image)
        ))
        ELSE checkpoint END
$$;

WITH normalized AS (
    SELECT combat_id, jsonb_set(data, '{round_checkpoints}', (
        SELECT COALESCE(jsonb_agg(pg_temp.concentration_lifetime_checkpoint(checkpoint) ORDER BY ordinal), '[]'::jsonb)
        FROM jsonb_array_elements(data->'round_checkpoints') WITH ORDINALITY AS entries(checkpoint, ordinal)
    )) AS data
    FROM combat_instances WHERE jsonb_typeof(data->'round_checkpoints') = 'array'
)
UPDATE combat_instances AS live SET data = normalized.data
FROM normalized WHERE live.combat_id = normalized.combat_id AND live.data <> normalized.data;

DROP FUNCTION pg_temp.concentration_lifetime_checkpoint(jsonb);
