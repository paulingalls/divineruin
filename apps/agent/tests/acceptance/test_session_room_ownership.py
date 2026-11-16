"""Fault-inject a competing server transition at the shared Valkey boundary."""

import asyncio
from uuid import uuid4

import pytest

import db
from session_room_ownership import transfer_room


async def test_primary_handoff_preserves_a_competing_transition(reset_db_pool):
    redis = await db.get_redis()
    departed, successor, room = (uuid4().hex for _ in range(3))
    old, new = f"player_room:{departed}", f"player_room:{successor}"
    owner, dispatched = f"room_owner:{room}", f"room_dispatched:{room}"
    lease = f"session_lock:player:{successor}"
    task = None
    try:
        await redis.mset({old: room, owner: departed, dispatched: departed, lease: "other-request"})
        task = asyncio.create_task(transfer_room(room, departed, successor))
        await asyncio.sleep(0.05)
        assert not task.done()
        assert await redis.get(old) == room
        assert await redis.get(owner) == departed
        # The lease's holder finishes by claiming another room; promotion must refuse it.
        await redis.set(new, "another-room", ex=7200)
        await redis.delete(lease)
        with pytest.raises(RuntimeError, match="ownership changed"):
            await task
        assert await redis.get(new) == "another-room"
        assert await redis.get(old) == room
        assert await redis.get(owner) == await redis.get(dispatched) == departed
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await redis.delete(old, new, owner, dispatched, lease)
