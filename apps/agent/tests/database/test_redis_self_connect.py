import asyncio
import socket
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis
from redis.asyncio.connection import Connection, ConnectionPool

import db


class SelfSocketConnection(Connection):
    sock: ClassVar[socket.socket | None] = None

    async def _connect(self):
        sock = type(self).sock
        assert sock is not None
        self._reader, self._writer = await asyncio.open_connection(sock=sock)

    async def on_connect_check_health(self, check_health=True):
        # Skip the HELLO/SELECT handshake, which a self-connected socket would answer with its own
        # bytes; the parser still has to attach to the stream.
        self._parser.on_connect(self)


def _self_connected_socket() -> socket.socket:
    # macOS refuses an IPv4 self-connect (EINVAL) but allows one on ::1, the family the
    # production self-connect used; Linux allows both.
    refusals = []
    for family, host in ((socket.AF_INET6, "::1"), (socket.AF_INET, "127.0.0.1")):
        sock = None
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.bind((host, 0))
            sock.connect(sock.getsockname())
            return sock
        except OSError as exc:
            if sock is not None:
                sock.close()
            refusals.append(f"{host}: {exc}")
    pytest.skip(f"OS refuses loopback self-connect: {refusals}")


@pytest.mark.asyncio
async def test_self_connected_socket_discards_its_own_get_reply(caplog):
    sock = _self_connected_socket()
    assert sock.getsockname() == sock.getpeername()
    sock.setblocking(False)
    SelfSocketConnection.sock = sock
    client = aioredis.Redis(
        connection_pool=ConnectionPool(connection_class=SelfSocketConnection, decode_responses=True)
    )
    previous = db._redis
    db._redis = client
    try:
        assert await db._cache_get("self-connect-key") is None
        assert db._redis is None
        assert "TCP self-connect" in caplog.text
    finally:
        await client.aclose()
        db._redis = previous
        SelfSocketConnection.sock = None


@pytest.mark.asyncio
async def test_non_string_reply_that_is_not_an_echo_is_not_called_a_self_connect(caplog):
    client = AsyncMock()
    client.get = AsyncMock(return_value=["GET", "another-key"])
    client.connection_pool.disconnect = AsyncMock()
    previous = db._redis
    db._redis = client
    try:
        assert await db._cache_get("self-connect-key") is None
        assert db._redis is None
        assert any(record.msg == db.DESYNCED_REPLY_LOG for record in caplog.records)
        assert "TCP self-connect" not in caplog.text
    finally:
        db._redis = previous
