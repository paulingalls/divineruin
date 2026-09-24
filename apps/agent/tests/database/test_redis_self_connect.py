import asyncio
import os
import socket
import subprocess
import uuid
from typing import ClassVar

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
        pass


@pytest.mark.asyncio
async def test_self_connected_socket_discards_its_own_get_reply(caplog):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    try:
        sock.connect(sock.getsockname())
    except OSError as exc:
        sock.close()
        pytest.skip(f"OS refuses loopback self-connect: {exc}")
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
        assert "self-connect" in caplog.text
    finally:
        await client.aclose()
        db._redis = previous
        SelfSocketConnection.sock = None


@pytest.mark.asyncio
async def test_real_valkey_get_reads_value():
    url = os.environ.get("REDIS_URL")
    container = None
    client = None
    previous = db._redis
    try:
        if not url:
            container = subprocess.check_output(
                ["docker", "run", "--rm", "-d", "-p", "127.0.0.1:0:6379", "valkey/valkey:8-alpine"],
                text=True,
            ).strip()
            port = subprocess.check_output(["docker", "port", container, "6379/tcp"], text=True).strip().split(":")[-1]
            url = f"redis://127.0.0.1:{port}"
        client = aioredis.from_url(url, decode_responses=True)
        db._redis = client
        for _ in range(50):
            try:
                await client.ping()
                break
            except aioredis.ConnectionError:
                await asyncio.sleep(0.1)
        else:
            pytest.fail("Valkey did not become ready")
        key = f"test:self-connect:{uuid.uuid4()}"
        await client.set(key, "ordinary-value", ex=30)
        assert await db._cache_get(key) == "ordinary-value"
        await client.delete(key)
    finally:
        db._redis = previous
        try:
            if client is not None:
                await client.aclose()
        finally:
            if container:
                subprocess.run(["docker", "rm", "-f", container], check=True, capture_output=True)
