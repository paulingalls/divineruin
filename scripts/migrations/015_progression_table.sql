-- Level progression reference/admin table (seeded from content JSON)
CREATE TABLE IF NOT EXISTS level_progression (
    id TEXT PRIMARY KEY,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER set_level_progression_updated_at
    BEFORE UPDATE ON level_progression
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
