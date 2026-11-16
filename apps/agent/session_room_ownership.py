"""Atomic primary handoff shares the server's room-transition fencing protocol."""

import asyncio

import db

OWNERSHIP_SECONDS = 7200

# Server transitions hold player and room leases across LiveKit RPCs. This entire
# handoff fits in one command, so checking those leases also fences our writes.
_TRANSFER = """
for i = 5, 7 do
    if redis.call('EXISTS', KEYS[i]) == 1 then return 0 end
end
local old = redis.call('GET', KEYS[1])
local successor = redis.call('GET', KEYS[2])
local owner = redis.call('GET', KEYS[3])
local dispatched = redis.call('GET', KEYS[4])
-- Direct dev-server dispatches have no server-owned room records.
if not old and not successor and not owner and not dispatched then return 1 end
if old ~= ARGV[1] or owner ~= ARGV[2] or dispatched ~= ARGV[2]
    or (successor and successor ~= ARGV[1]) then return -1 end
redis.call('DEL', KEYS[1])
redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[4])
redis.call('SET', KEYS[3], ARGV[3], 'EX', ARGV[4])
redis.call('SET', KEYS[4], ARGV[3], 'EX', ARGV[4])
return 1
"""


async def transfer_room(room: str, departed: str, successor: str) -> None:
    redis = await db.get_redis()
    keys = [
        f"player_room:{departed}",
        f"player_room:{successor}",
        f"room_owner:{room}",
        f"room_dispatched:{room}",
        f"session_lock:player:{departed}",
        f"session_lock:player:{successor}",
        f"session_lock:room:{room}",
    ]
    async with asyncio.timeout(35):
        while True:
            result = await redis.eval(_TRANSFER, len(keys), *keys, room, departed, successor, OWNERSHIP_SECONDS)
            if result == 1:
                return
            if result != 0:
                raise RuntimeError(f"Room ownership changed before primary handoff in {room}")
            await asyncio.sleep(0.025)
