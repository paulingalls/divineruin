UPDATE players
SET data = jsonb_set(data, '{speed}', '30'::jsonb)
WHERE jsonb_typeof(data) = 'object' AND NOT data ? 'speed';
