"""Tests for world news generation module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_anthropic_response(text: str) -> MagicMock:
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_response.usage = MagicMock()
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 80
    return mock_response


def _patch_client(mock_response):
    mock_create = AsyncMock(return_value=mock_response)
    return patch("world_news._client.messages.create", mock_create)


class TestGenerateWorldNews:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_events(self):
        mock_pool = AsyncMock()
        mock_pool.fetchval = AsyncMock(return_value=None)
        mock_pool.fetch = AsyncMock(return_value=[])

        with patch("world_news.db.get_pool", AsyncMock(return_value=mock_pool)):
            from world_news import generate_world_news

            result = await generate_world_news("player_1")

        assert result is None

    @pytest.mark.asyncio
    async def test_generates_news_from_events(self):
        import json

        mock_pool = AsyncMock()
        mock_pool.fetchval = AsyncMock(return_value=None)
        mock_pool.fetch = AsyncMock(
            return_value=[
                {"data": json.dumps({"type": "trade", "description": "Iron prices rose"})},
                {"data": json.dumps({"type": "conflict", "description": "Bandits spotted"})},
            ]
        )
        mock_pool.execute = AsyncMock()

        mock_response = _mock_anthropic_response(
            "Trade winds shift as iron prices climb. Bandit raids threaten the northern roads."
        )

        with (
            patch("world_news.db.get_pool", AsyncMock(return_value=mock_pool)),
            _patch_client(mock_response) as mock_create,
            patch("world_news.synthesize_to_file", AsyncMock()),
        ):
            from world_news import generate_world_news

            result = await generate_world_news("player_1")

        assert result is not None
        assert "title" in result
        assert "summary" in result
        assert result["id"].startswith("news_")
        mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_tts_failure_gracefully(self):
        import json

        mock_pool = AsyncMock()
        mock_pool.fetchval = AsyncMock(return_value=None)
        mock_pool.fetch = AsyncMock(
            return_value=[
                {"data": json.dumps({"type": "event", "description": "Something happened"})},
            ]
        )
        mock_pool.execute = AsyncMock()

        mock_response = _mock_anthropic_response("A brief news update.")

        with (
            patch("world_news.db.get_pool", AsyncMock(return_value=mock_pool)),
            _patch_client(mock_response),
            patch("world_news.synthesize_to_file", AsyncMock(side_effect=Exception("TTS failed"))),
        ):
            from world_news import generate_world_news

            result = await generate_world_news("player_1")

        assert result is not None
        assert result["audio_url"] is None
