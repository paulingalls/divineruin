CREATE TABLE sink_event_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id TEXT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
    sink_category TEXT NOT NULL,
    sink_type TEXT NOT NULL,
    item_id TEXT NOT NULL,
    amount_sp BIGINT NOT NULL CHECK (amount_sp > 0),
    context JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX sink_event_log_player_id_idx ON sink_event_log (player_id);
