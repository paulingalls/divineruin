CREATE TABLE merchant_state (
  npc_id TEXT PRIMARY KEY REFERENCES npcs(id),
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER update_merchant_state_updated_at
  BEFORE UPDATE ON merchant_state
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
