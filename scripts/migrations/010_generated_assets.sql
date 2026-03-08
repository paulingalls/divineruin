CREATE TABLE IF NOT EXISTS generated_assets (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL,
  variables JSONB NOT NULL DEFAULT '{}',
  file_path TEXT NOT NULL,
  aspect_ratio TEXT NOT NULL,
  category TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_generated_assets_template ON generated_assets (template_id);
CREATE INDEX idx_generated_assets_category ON generated_assets (category);
