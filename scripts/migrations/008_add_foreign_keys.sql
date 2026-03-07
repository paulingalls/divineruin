-- Add missing foreign key constraints for player_id references

ALTER TABLE async_activities
  ADD CONSTRAINT fk_async_activities_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

ALTER TABLE world_news_items
  ADD CONSTRAINT fk_world_news_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

ALTER TABLE push_tokens
  ADD CONSTRAINT fk_push_tokens_player
  FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE;

-- Index for auth code verification lookups
CREATE INDEX idx_auth_codes_verify
  ON auth_codes (account_id, used, expires_at DESC);
