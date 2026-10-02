ALTER TABLE players ADD COLUMN inventory_revision BIGINT NOT NULL DEFAULT 0
  CHECK (inventory_revision >= 0);

CREATE FUNCTION bump_inventory_revision() RETURNS TRIGGER AS $$
DECLARE
  owners TEXT[];
  owner TEXT;
BEGIN
  IF TG_OP = 'INSERT' THEN
    owners := ARRAY[NEW.player_id];
  ELSIF TG_OP = 'DELETE' THEN
    owners := ARRAY[OLD.player_id];
  ELSE
    owners := ARRAY[OLD.player_id, NEW.player_id];
  END IF;
  FOR owner IN SELECT DISTINCT unnest(owners) ORDER BY 1 LOOP
    UPDATE players SET inventory_revision = inventory_revision + 1
      WHERE player_id = owner;
  END LOOP;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_inventory_revision AFTER INSERT OR UPDATE OR DELETE
  ON player_inventory FOR EACH ROW EXECUTE FUNCTION bump_inventory_revision();
