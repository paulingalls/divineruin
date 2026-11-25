CREATE TABLE zhael_foretold_words (
    player_id TEXT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
    npc_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    data JSONB NOT NULL,
    PRIMARY KEY (player_id, npc_id, session_id)
);
