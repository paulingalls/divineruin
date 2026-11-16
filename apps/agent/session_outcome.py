"""Player-owned session outcomes keep re-entry recaps tied to their producer."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import db
import db_queries

logger = logging.getLogger("divineruin.session_outcome")

TTL_S = 7200
WAIT_S = 15
State = Literal["saved", "failed"]

# KEYS[2] is the server's player_room:<player_id> (apps/server/src/session-rooms.ts), set to the
# new room before its DM is dispatched. A dispatch whose room it no longer names was taken over.
_REGISTER = """
local room = redis.call('GET', KEYS[2])
if room and room ~= ARGV[4] then return -1 end
local current = redis.call('GET', KEYS[1])
if (current or '') ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""
_COMPLETE = """
local raw = redis.call('GET', KEYS[1])
if raw then
    local current = cjson.decode(raw)
    if current.state == 'live' then
        if current.session_id ~= ARGV[1] then return 0 end
        redis.call('SET', KEYS[1], ARGV[2], 'KEEPTTL')
        return 1
    end
end
if ARGV[3] == 'guest' then
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[4])
    return 1
end
return 0
"""


@dataclass
class Predecessor:
    observed: bytes | str | None
    summary: dict | None
    prior_summary: dict | None
    skip_reason: str = ""
    session_id: str = ""


def _decode(raw: bytes | str | None) -> dict | None:
    if raw is None:
        return None
    record = json.loads(raw)
    if (
        not isinstance(record, dict)
        or not isinstance(record.get("session_id"), str)
        or not record["session_id"]
        or record.get("state") not in ("live", "saved", "failed")
    ):
        raise ValueError("Invalid session outcome record")
    return record


async def resolve_predecessor(player_id: str) -> Predecessor:
    redis = await db.get_redis()
    key = f"session_outcome:{player_id}"
    reason = ""
    predecessor_id = ""
    async with asyncio.timeout(WAIT_S) as deadline:
        raw = await redis.get(key)
        record = _decode(raw)
        if record is not None:
            predecessor_id = record["session_id"]
        try:
            while record is not None and record["state"] == "live":
                await asyncio.sleep(0.05)
                next_raw = await redis.get(key)
                next_record = _decode(next_raw)
                if next_record is not None and next_record["session_id"] != predecessor_id:
                    raise RuntimeError(f"Session outcome owner changed during startup for {player_id}")
                raw, record = next_raw, next_record
                if record is None:
                    reason = "predecessor outcome disappeared"
                    break
        except asyncio.CancelledError:
            if not deadline.expired():
                raise
            reason = "predecessor outcome timed out"
    prior = await db_queries.get_last_session_summary(player_id)
    if record is not None and record["state"] == "failed":
        reason = "predecessor failed"
    if predecessor_id and not reason and (prior is None or prior.get("session_id") != predecessor_id):
        reason = "predecessor summary missing or mismatched"
    return Predecessor(raw, None if reason else prior, prior, reason, predecessor_id)


async def complete(player_id: str, session_id: str, state: State, *, guest_saved: bool = False) -> None:
    redis = await db.get_redis()
    await redis.eval(
        _COMPLETE,
        1,
        f"session_outcome:{player_id}",
        session_id,
        json.dumps({"session_id": session_id, "state": state}),
        "guest" if guest_saved else "owner",
        TTL_S,
    )


async def _taken_over(player_id: str, room_name: str) -> bool:
    redis = await db.get_redis()
    room = await redis.get(f"player_room:{player_id}")
    if isinstance(room, bytes):
        room = room.decode()
    return room is not None and room != room_name


@asynccontextmanager
async def startup(player_id: str, room_name: str):
    """Yield (session_id, predecessor), or (None, None) when a newer dispatch took the player over."""
    try:
        predecessor = await resolve_predecessor(player_id)
    except RuntimeError:
        if await _taken_over(player_id, room_name):
            logger.info("Dispatch for %s in %s was taken over while waiting; abandoning", player_id, room_name)
            yield None, None
            return
        raise
    session_id = uuid4().hex
    redis = await db.get_redis()
    registered = await redis.eval(
        _REGISTER,
        2,
        f"session_outcome:{player_id}",
        f"player_room:{player_id}",
        predecessor.observed or "",
        json.dumps({"session_id": session_id, "state": "live"}),
        TTL_S,
        room_name,
    )
    if registered == -1:
        logger.info("Dispatch for %s in %s was taken over while waiting; abandoning", player_id, room_name)
        yield None, None
        return
    if not registered:
        raise RuntimeError(f"Session outcome owner changed during startup for {player_id}")
    try:
        yield session_id, predecessor
    except BaseException:
        try:
            await complete(player_id, session_id, "failed")
        except Exception:
            logger.exception("Failed to record interrupted startup for player %s session %s", player_id, session_id)
        raise


def watch_close(session, sd) -> None:
    sd.outcome_player_id = sd.primary_player_id

    def closed(_event):
        if sd.session_end_task is None:
            if sd.background is None:
                sd.session_end_task = asyncio.create_task(complete(sd.primary_player_id, sd.session_id, "failed"))
            else:
                from session_end import ensure_session_end

                ensure_session_end(sd)

    session.on("close", closed)
