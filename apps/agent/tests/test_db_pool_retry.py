"""Tests for the bounded connect-retry hook used by db.get_pool()."""

from unittest.mock import AsyncMock, call

import asyncpg
import pytest

import db


@pytest.mark.parametrize(
    "transient",
    [
        ConnectionError("...rejected SSL upgrade"),
        asyncpg.CannotConnectNowError("the database system is starting up"),
        asyncpg.TooManyConnectionsError("sorry, too many clients already"),
    ],
    ids=["rejected_ssl_upgrade", "starting_up", "too_many_clients"],
)
@pytest.mark.asyncio
async def test_retries_transient_error_then_succeeds(monkeypatch, caplog, transient):
    """Each transient connect-setup error on the first attempt is retried, then succeeds."""
    mock_conn = object()
    fake_connect = AsyncMock(side_effect=[transient, mock_conn])
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
async def test_forwards_pool_connect_arguments_unchanged(monkeypatch):
    """asyncpg's Pool calls the hook with the DSN plus loop/connection_class/record_class.

    Every attempt must forward them through untouched — a dropped connection_class
    makes Pool._get_new_connection reject the connection with an InterfaceError.
    """
    mock_conn = object()
    fake_connect = AsyncMock(side_effect=[ConnectionError("boom"), mock_conn])
    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    monkeypatch.setattr("db.asyncio.sleep", AsyncMock())
    sentinel_loop = object()

    result = await db._connect_with_retry(
        "postgres://test",
        loop=sentinel_loop,
        connection_class=asyncpg.Connection,
        record_class=asyncpg.Record,
    )

    assert result is mock_conn
    expected = call(
        "postgres://test",
        loop=sentinel_loop,
        connection_class=asyncpg.Connection,
        record_class=asyncpg.Record,
    )
    assert fake_connect.await_args_list == [expected, expected]


@pytest.mark.asyncio
async def test_raises_last_exception_after_exhausting_budget(monkeypatch):
    """A persistent transient error propagates — the last failure — after all attempts."""
    failures = [ConnectionError(f"...rejected SSL upgrade #{i}") for i in range(3)]
    fake_connect = AsyncMock(side_effect=failures)
    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    monkeypatch.setattr("db.asyncio.sleep", AsyncMock())

    with pytest.raises(ConnectionError) as exc_info:
        await db._connect_with_retry("postgres://test")

    assert exc_info.value is failures[-1]
    assert fake_connect.await_count == db._CONNECT_ATTEMPTS == len(failures)


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
