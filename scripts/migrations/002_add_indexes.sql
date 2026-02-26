-- GIN indexes on content table JSONB columns
CREATE INDEX idx_locations_data ON locations USING GIN (data);
CREATE INDEX idx_npcs_data ON npcs USING GIN (data);
CREATE INDEX idx_items_data ON items USING GIN (data);
CREATE INDEX idx_quests_data ON quests USING GIN (data);
CREATE INDEX idx_events_data ON events USING GIN (data);
CREATE INDEX idx_factions_data ON factions USING GIN (data);

-- Expression indexes on commonly queried JSONB fields
CREATE INDEX idx_locations_region ON locations ((data->>'region'));
CREATE INDEX idx_locations_tier ON locations ((data->>'tier'));
CREATE INDEX idx_npcs_faction ON npcs ((data->>'faction'));
CREATE INDEX idx_items_type ON items ((data->>'type'));
CREATE INDEX idx_items_tier ON items ((data->>'tier'));
CREATE INDEX idx_quests_type ON quests ((data->>'type'));
CREATE INDEX idx_events_type ON events ((data->>'type'));

-- State table join column indexes
CREATE INDEX idx_player_inventory_player ON player_inventory (player_id);
CREATE INDEX idx_player_inventory_item ON player_inventory (item_id);
CREATE INDEX idx_player_quests_player ON player_quests (player_id);
CREATE INDEX idx_player_quests_quest ON player_quests (quest_id);
CREATE INDEX idx_player_reputation_player ON player_reputation (player_id);
CREATE INDEX idx_player_reputation_faction ON player_reputation (faction_id);
CREATE INDEX idx_npc_dispositions_npc ON npc_dispositions (npc_id);
CREATE INDEX idx_npc_dispositions_player ON npc_dispositions (player_id);
CREATE INDEX idx_world_events_log_event ON world_events_log (event_id);
CREATE INDEX idx_world_events_log_timestamp ON world_events_log (timestamp);
CREATE INDEX idx_session_summaries_player ON session_summaries (player_id);
