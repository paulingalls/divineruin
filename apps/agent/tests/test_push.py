"""Tests for push notification helper — URL validation and timeout."""

import os
from unittest.mock import AsyncMock, patch

from push import send_push_notification


class TestServerUrlValidation:
    async def test_rejects_ftp_protocol(self):
        with patch.dict(os.environ, {"SERVER_URL": "ftp://evil.com", "INTERNAL_SECRET": "s"}):
            with patch("push.logger") as mock_logger:
                await send_push_notification("player_1", "Test", "Body")
                mock_logger.error.assert_called_once()
                assert "invalid protocol" in mock_logger.error.call_args[0][0].lower()

    async def test_rejects_file_protocol(self):
        with patch.dict(os.environ, {"SERVER_URL": "file:///etc/passwd", "INTERNAL_SECRET": "s"}):
            with patch("push.logger") as mock_logger:
                await send_push_notification("player_1", "Test", "Body")
                mock_logger.error.assert_called_once()

    async def test_accepts_http(self):
        with patch.dict(os.environ, {"SERVER_URL": "http://localhost:3001", "INTERNAL_SECRET": "s"}):
            mock_resp = AsyncMock()
            mock_resp.status = 200

            mock_session = AsyncMock()
            mock_session.post.return_value.__aenter__.return_value = mock_resp

            mock_session_ctx = AsyncMock()
            mock_session_ctx.__aenter__.return_value = mock_session
            mock_session_ctx.__aexit__.return_value = False

            with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
                await send_push_notification("player_1", "Test", "Body")
                mock_session.post.assert_called_once()

    async def test_accepts_https(self):
        with patch.dict(os.environ, {"SERVER_URL": "https://api.example.com", "INTERNAL_SECRET": "s"}):
            mock_resp = AsyncMock()
            mock_resp.status = 200

            mock_session = AsyncMock()
            mock_session.post.return_value.__aenter__.return_value = mock_resp

            mock_session_ctx = AsyncMock()
            mock_session_ctx.__aenter__.return_value = mock_session
            mock_session_ctx.__aexit__.return_value = False

            with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
                await send_push_notification("player_1", "Test", "Body")
                mock_session.post.assert_called_once()

    async def test_timeout_is_set(self):
        """Verify that a timeout is configured on the session."""
        with patch.dict(os.environ, {"SERVER_URL": "http://localhost:3001", "INTERNAL_SECRET": "s"}):
            mock_resp = AsyncMock()
            mock_resp.status = 200

            mock_session = AsyncMock()
            mock_session.post.return_value.__aenter__.return_value = mock_resp

            mock_session_ctx = AsyncMock()
            mock_session_ctx.__aenter__.return_value = mock_session
            mock_session_ctx.__aexit__.return_value = False

            with patch("aiohttp.ClientSession", return_value=mock_session_ctx) as mock_cls:
                await send_push_notification("player_1", "Test", "Body")
                call_kwargs = mock_cls.call_args[1]
                assert "timeout" in call_kwargs
                assert call_kwargs["timeout"].total == 5
