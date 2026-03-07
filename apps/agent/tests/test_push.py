"""Tests for push notification helper — URL validation and timeout."""

import os
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

from push import send_push_notification


def _mock_aiohttp_session(status: int = 200):
    """Build a mock aiohttp.ClientSession that works as a nested async context manager."""
    mock_resp = MagicMock()
    mock_resp.status = status

    @asynccontextmanager
    async def _post_ctx(*args, **kwargs):
        yield mock_resp

    mock_session = MagicMock()
    mock_session.post = _post_ctx

    @asynccontextmanager
    async def _session_ctx(*args, **kwargs):
        yield mock_session

    return _session_ctx, mock_session


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
            session_ctx, _mock_session = _mock_aiohttp_session()
            with patch("aiohttp.ClientSession", session_ctx):
                await send_push_notification("player_1", "Test", "Body")

    async def test_accepts_https(self):
        with patch.dict(os.environ, {"SERVER_URL": "https://api.example.com", "INTERNAL_SECRET": "s"}):
            session_ctx, _mock_session = _mock_aiohttp_session()
            with patch("aiohttp.ClientSession", session_ctx):
                await send_push_notification("player_1", "Test", "Body")

    async def test_timeout_is_set(self):
        """Verify that a timeout is configured on the session."""
        with patch.dict(os.environ, {"SERVER_URL": "http://localhost:3001", "INTERNAL_SECRET": "s"}):
            captured_kwargs: dict = {}

            @asynccontextmanager
            async def _capturing_session(**kwargs):
                captured_kwargs.update(kwargs)
                mock_resp = MagicMock()
                mock_resp.status = 200

                @asynccontextmanager
                async def _post_ctx(*a, **kw):
                    yield mock_resp

                session = MagicMock()
                session.post = _post_ctx
                yield session

            with patch("aiohttp.ClientSession", _capturing_session):
                await send_push_notification("player_1", "Test", "Body")
                assert "timeout" in captured_kwargs
                assert captured_kwargs["timeout"].total == 5
