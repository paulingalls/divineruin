"""Tests for companion idle audio generation module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_anthropic_response(text: str) -> MagicMock:
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_response.usage = MagicMock()
    mock_response.usage.input_tokens = 80
    mock_response.usage.output_tokens = 60
    return mock_response


def _patch_client(mock_response):
    mock_create = AsyncMock(return_value=mock_response)
    return patch("companion_idle._client.messages.create", mock_create)


class TestGenerateIdlePool:
    @pytest.mark.asyncio
    async def test_generates_correct_count(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        mock_response = _mock_anthropic_response(
            "Kael drums his fingers on the table.\n"
            "A yawn escapes as the fire crackles low.\n"
            "He counts the notches on his blade handle."
        )

        with (
            patch("companion_idle.db.get_pool", AsyncMock(return_value=mock_pool)),
            _patch_client(mock_response),
            patch("companion_idle.synthesize_to_file", AsyncMock()),
        ):
            from companion_idle import generate_idle_pool

            result = await generate_idle_pool("companion_kael", count=3)

        assert len(result) == 3
        for clip in result:
            assert "id" in clip
            assert "text" in clip
            assert clip["companion_id"] == "companion_kael"

    @pytest.mark.asyncio
    async def test_handles_tts_failure(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        mock_response = _mock_anthropic_response("A single line of chatter.")

        with (
            patch("companion_idle.db.get_pool", AsyncMock(return_value=mock_pool)),
            _patch_client(mock_response),
            patch("companion_idle.synthesize_to_file", AsyncMock(side_effect=Exception("TTS error"))),
        ):
            from companion_idle import generate_idle_pool

            result = await generate_idle_pool("companion_kael", count=1)

        assert len(result) == 1
        assert result[0]["audio_url"] is None


class TestGetIdleClip:
    @pytest.mark.asyncio
    async def test_returns_unheard_clip(self):
        import json

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(
            return_value={
                "id": "idle_abc123",
                "data": json.dumps(
                    {
                        "type": "idle_clip",
                        "companion_id": "companion_kael",
                        "text": "The fire pops quietly.",
                        "audio_url": "/api/audio/idle_abc123.mp3",
                        "heard": False,
                    }
                ),
            }
        )
        mock_pool.execute = AsyncMock()

        with patch("companion_idle.db.get_pool", AsyncMock(return_value=mock_pool)):
            from companion_idle import get_idle_clip

            result = await get_idle_clip("companion_kael", "player_1")

        assert result is not None
        assert result["text"] == "The fire pops quietly."
        assert result["audio_url"] == "/api/audio/idle_abc123.mp3"
        # Should have marked as heard
        mock_pool.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_no_clips(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with patch("companion_idle.db.get_pool", AsyncMock(return_value=mock_pool)):
            from companion_idle import get_idle_clip

            result = await get_idle_clip("companion_kael", "player_1")

        assert result is None
