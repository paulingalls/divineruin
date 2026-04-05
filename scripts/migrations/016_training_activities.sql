-- Training activities: 5-state cycle state machine for async training
CREATE TABLE IF NOT EXISTS training_activities (
    id TEXT PRIMARY KEY,
    player_id TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'initiated',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_training_activities_player ON training_activities (player_id);
CREATE INDEX IF NOT EXISTS idx_training_activities_state ON training_activities (state);
-- Worker polls for activities whose transition_at has passed
CREATE INDEX IF NOT EXISTS idx_training_activities_transition
    ON training_activities (((data->>'transition_at')::timestamptz))
    WHERE state IN ('running_first_half', 'running_second_half');
