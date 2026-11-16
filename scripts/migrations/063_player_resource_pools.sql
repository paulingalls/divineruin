WITH missing AS (
    SELECT p.player_id, pool.key,
           (formula->>'base')::int
           + COALESCE(floor(((p.data->'attributes'->>(formula->>'attribute'))::numeric - 10) / 2)::int, 0)
           + CASE WHEN (formula->>'level_divisor')::int = 0 THEN 0
                  ELSE (p.data->>'level')::int / (formula->>'level_divisor')::int END AS maximum
    FROM players p
    JOIN archetypes a ON a.id = p.data->>'class'
    CROSS JOIN (VALUES ('stamina'), ('focus')) AS pool(key)
    CROSS JOIN LATERAL (SELECT a.data->'resource'->(pool.key || '_formula') AS formula) f
    WHERE formula IS NOT NULL AND formula <> 'null'::jsonb AND NOT p.data ? pool.key
), patches AS (
    SELECT player_id, jsonb_object_agg(key, jsonb_build_object('current', maximum, 'max', maximum)) AS patch
    FROM missing
    GROUP BY player_id
)
UPDATE players p SET data = p.data || patches.patch
FROM patches WHERE p.player_id = patches.player_id;
