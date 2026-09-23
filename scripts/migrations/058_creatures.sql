CREATE TABLE IF NOT EXISTS creatures (
  id text PRIMARY KEY,
  data jsonb NOT NULL,
  name text GENERATED ALWAYS AS (data->>'name') STORED,
  category text GENERATED ALWAYS AS (data->>'category') STORED,
  tier integer GENERATED ALWAYS AS ((data->>'tier')::integer) STORED,
  level integer GENERATED ALWAYS AS ((data->>'level')::integer) STORED
);

CREATE INDEX IF NOT EXISTS idx_creatures_category ON creatures (category);
CREATE INDEX IF NOT EXISTS idx_creatures_tier ON creatures (tier);
CREATE INDEX IF NOT EXISTS idx_creatures_name ON creatures (name);
