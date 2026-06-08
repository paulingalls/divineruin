"""Tests for check_god_whisper_triggers — favor-threshold whisper generation."""

from unittest.mock import AsyncMock, patch

import pytest


class TestCheckGodWhisperTriggers:
    @pytest.mark.asyncio
    @patch("async_worker.db_mutations_divine.mark_favor_whisper_level", new_callable=AsyncMock)
    @patch("god_whisper_generator.generate_god_whisper", new_callable=AsyncMock, return_value="whisper_1")
    @patch("async_worker.db_activity_queries.get_pending_god_whispers", new_callable=AsyncMock, return_value=[])
    @patch("async_worker.db.get_pool")
    async def test_generates_whisper_above_threshold(self, mock_pool, mock_pending, mock_gen, mock_mark):
        import json

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "player_id": "player_1",
                    "favor": json.dumps(
                        {
                            "patron": "kaelen",
                            "level": 25,
                            "max": 100,
                            "last_whisper_level": 0,
                        }
                    ),
                }
            ]
        )
        mock_pool.return_value = mock_conn

        from async_worker import check_god_whisper_triggers

        count = await check_god_whisper_triggers()
        assert count == 1
        mock_gen.assert_called_once_with("player_1", "kaelen")
        mock_mark.assert_called_once_with("player_1", 25)

    @pytest.mark.asyncio
    @patch("async_worker.db.get_pool")
    async def test_skips_below_cooldown(self, mock_pool):
        import json

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "player_id": "player_1",
                    "favor": json.dumps(
                        {
                            "patron": "kaelen",
                            "level": 35,
                            "max": 100,
                            "last_whisper_level": 25,
                        }
                    ),
                }
            ]
        )
        mock_pool.return_value = mock_conn

        from async_worker import check_god_whisper_triggers

        count = await check_god_whisper_triggers()
        # 35 - 25 = 10 < 25 cooldown
        assert count == 0

    @pytest.mark.asyncio
    @patch("async_worker.db.get_pool")
    async def test_no_players_returns_zero(self, mock_pool):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool.return_value = mock_conn

        from async_worker import check_god_whisper_triggers

        count = await check_god_whisper_triggers()
        assert count == 0
