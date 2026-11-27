-- Legacy Bless did not record which caster buffed each recipient.
CREATE FUNCTION pg_temp.without_unowned_bless(conditions jsonb) RETURNS jsonb
LANGUAGE SQL IMMUTABLE AS $$
    SELECT COALESCE(jsonb_agg(condition ORDER BY ordinal), '[]'::jsonb)
    FROM jsonb_array_elements(conditions) WITH ORDINALITY AS entries(condition, ordinal)
    WHERE condition->>'type' IS DISTINCT FROM 'blessed'
       OR condition ? 'sustaining_caster_ids'
$$;

CREATE FUNCTION pg_temp.clean_combat_bless(combat jsonb) RETURNS jsonb
LANGUAGE SQL IMMUTABLE AS $$
    SELECT CASE WHEN jsonb_typeof(combat->'participants') = 'array'
        THEN jsonb_set(combat, '{participants}', (
            SELECT COALESCE(jsonb_agg(
                CASE WHEN participant->'conditions' @> '[{"type":"blessed"}]'
                    THEN jsonb_set(participant, '{conditions}', pg_temp.without_unowned_bless(participant->'conditions'))
                    ELSE participant END ORDER BY ordinal), '[]'::jsonb)
            FROM jsonb_array_elements(combat->'participants') WITH ORDINALITY AS entries(participant, ordinal)
        ))
        ELSE combat END
$$;

UPDATE players
SET data = jsonb_set(data, '{conditions}', pg_temp.without_unowned_bless(data->'conditions'))
WHERE data->'conditions' @> '[{"type":"blessed"}]'
  AND data->'conditions' <> pg_temp.without_unowned_bless(data->'conditions');

WITH cleaned AS (
    SELECT combat_id,
           CASE WHEN jsonb_typeof(data->'round_checkpoints') = 'array'
               THEN jsonb_set(pg_temp.clean_combat_bless(data), '{round_checkpoints}', (
                   SELECT COALESCE(jsonb_agg(
                       CASE WHEN checkpoint ? 'combat'
                           THEN jsonb_set(checkpoint, '{combat}', pg_temp.clean_combat_bless(checkpoint->'combat'))
                           ELSE checkpoint END ORDER BY ordinal), '[]'::jsonb)
                   FROM jsonb_array_elements(data->'round_checkpoints') WITH ORDINALITY AS entries(checkpoint, ordinal)
               ))
               ELSE pg_temp.clean_combat_bless(data) END AS data
    FROM combat_instances
)
UPDATE combat_instances AS live SET data = cleaned.data
FROM cleaned WHERE live.combat_id = cleaned.combat_id AND live.data <> cleaned.data;

DROP FUNCTION pg_temp.clean_combat_bless(jsonb);
DROP FUNCTION pg_temp.without_unowned_bless(jsonb);
