ALTER TABLE player_inventory ADD COLUMN tainted BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE player_inventory DROP CONSTRAINT player_inventory_pkey;
ALTER TABLE player_inventory ADD PRIMARY KEY (player_id, item_id, tainted);
