-- Secondary column indexes on composite PKs
-- (leading column is already indexed by the PK itself)
CREATE INDEX idx_player_inventory_item ON player_inventory (item_id);
CREATE INDEX idx_player_quests_quest ON player_quests (quest_id);
CREATE INDEX idx_player_reputation_faction ON player_reputation (faction_id);
CREATE INDEX idx_npc_dispositions_player ON npc_dispositions (player_id);

-- world_events_log lookup indexes
CREATE INDEX idx_world_events_log_event ON world_events_log (event_id);
CREATE INDEX idx_world_events_log_timestamp ON world_events_log (timestamp);
