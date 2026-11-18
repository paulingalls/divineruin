ALTER TABLE players ADD COLUMN patron_revision BIGINT NOT NULL DEFAULT 0
  CHECK (patron_revision >= 0);

CREATE FUNCTION stamp_patron_revision() RETURNS TRIGGER AS $$
BEGIN
  NEW.patron_revision := OLD.patron_revision + 1;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_patron_revision BEFORE UPDATE OF data ON players
  FOR EACH ROW WHEN (OLD.data IS DISTINCT FROM NEW.data)
  EXECUTE FUNCTION stamp_patron_revision();
