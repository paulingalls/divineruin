"""Tests for async god whisper generation (mocked LLM + TTS + DB)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from god_whisper_generator import generate_god_whisper


class TestGenerateGodWhisper:
    @pytest.mark.asyncio
    @patch("god_whisper_generator.db.create_god_whisper", new_callable=AsyncMock, return_value="whisper_abc123")
    @patch("god_whisper_generator.synthesize_to_file", new_callable=AsyncMock, return_value="whisper_test.mp3")
    @patch("god_whisper_generator.client")
    async def test_generates_whisper(self, mock_client, mock_tts, mock_db):
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Your blade has spoken well today.")]
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        # Patch the push notification (imported dynamically inside the function)
        with patch("god_whisper_generator.send_push_notification", new_callable=AsyncMock):
            whisper_id = await generate_god_whisper("player_1", "kaelen", "defeated enemies with honor")

        assert whisper_id == "whisper_abc123"

        # Verify LLM was called
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        assert "Kaelen" in call_kwargs["messages"][0]["content"]

        # Verify TTS was called
        mock_tts.assert_called_once()
        assert "player_1" in mock_tts.call_args[0][2]  # output path includes player

        # Verify DB record created
        mock_db.assert_called_once()
        whisper_data = mock_db.call_args[0][1]
        assert whisper_data["deity_id"] == "kaelen"
        assert whisper_data["status"] == "pending"
        assert whisper_data["narration_text"] == "Your blade has spoken well today."

    @pytest.mark.asyncio
    @patch("god_whisper_generator.db.create_god_whisper", new_callable=AsyncMock, return_value="whisper_xyz")
    @patch("god_whisper_generator.synthesize_to_file", new_callable=AsyncMock, return_value="w.mp3")
    @patch("god_whisper_generator.client")
    async def test_sends_push_notification(self, mock_client, mock_tts, mock_db):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="The threads tighten.")]
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("god_whisper_generator.send_push_notification", new_callable=AsyncMock) as mock_push:
            await generate_god_whisper("player_1", "zhael")

        mock_push.assert_called_once()
        title = mock_push.call_args[0][1]
        assert "Zhael" in title
