"""Tests for the bounded connect-retry hook used by db.get_pool()."""

from unittest.mock import AsyncMock

import asyncpg
import pytest

import db


@pytest.mark.asyncio
async def test_retries_transient_error_then_succeeds(monkeypatch, caplog):
    """A transient ConnectionError on the first attempt should be retried and succeed."""
    mock_conn = object()
    fake_connect = AsyncMock(side_effect=[ConnectionError("...rejected SSL upgrade"), mock_conn])
    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    fake_sleep = AsyncMock()
    monkeypatch.setattr("db.asyncio.sleep", fake_sleep)

    with caplog.at_level("WARNING"):
        result = await db._connect_with_retry("postgres://test")

    assert result is mock_conn
    assert fake_connect.await_count == 2
    fake_sleep.assert_awaited_once()
    assert any("attempt" in record.message.lower() for record in caplog.records)


@pytest.mark.asyncio
async def test_raises_original_exception_after_exhausting_budget(monkeypatch):
    """A persistent transient error should propagate the original exception after all attempts."""
    original = ConnectionError("...rejected SSL upgrade")
    fake_connect = AsyncMock(side_effect=[original, original, original])
    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    monkeypatch.setattr("db.asyncio.sleep", AsyncMock())

    with pytest.raises(ConnectionError) as exc_info:
        await db._connect_with_retry("postgres://test")

    assert exc_info.value is original
    assert fake_connect.await_count == db._CONNECT_ATTEMPTS


@pytest.mark.asyncio
async def test_non_transient_error_raises_immediately_without_retry(monkeypatch):
    """A non-transient error (e.g. bad credentials) should raise on the first attempt, no sleep."""
    fake_connect = AsyncMock(side_effect=asyncpg.InvalidPasswordError("bad password"))
    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    fake_sleep = AsyncMock()
    monkeypatch.setattr("db.asyncio.sleep", fake_sleep)

    with pytest.raises(asyncpg.InvalidPasswordError):
        await db._connect_with_retry("postgres://test")

    fake_connect.assert_awaited_once()
    fake_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_backoff_sequence_is_linear(monkeypatch):
    """Backoff between retries should follow the linear sequence 0.25s, 0.5s."""
    original = ConnectionError("...rejected SSL upgrade")
    fake_connect = AsyncMock(side_effect=[original, original, original])
    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    fake_sleep = AsyncMock()
    monkeypatch.setattr("db.asyncio.sleep", fake_sleep)

    with pytest.raises(ConnectionError):
        await db._connect_with_retry("postgres://test")

    sleep_calls = [call.args[0] for call in fake_sleep.await_args_list]
    assert sleep_calls == [0.25, 0.5]
