-- Skill advancement tracking: per-skill tier and use counter
CREATE TABLE IF NOT EXISTS skill_advancement (
    player_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'untrained',
    use_counter INT NOT NULL DEFAULT 0,
    narrative_moment_ready BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_skill_advancement_player ON skill_advancement (player_id);
