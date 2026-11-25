import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from combat._round_checkpoint_helpers import Fight
from sample_fixtures import FixedRng

import dice
from combat_agent import CombatAgent

GIFT = "zhael_unravel_fate"
LOCATION = "greyvale_ruins_inner"


async def patch_player(fight: Fight, pid: str, **fields) -> None:
    await fight.pool.execute("UPDATE players SET data = data || $2::jsonb WHERE player_id=$1", pid, json.dumps(fields))


async def favor(fight: Fight, pid: str, patron: str = "zhael", level: int = 90) -> None:
    await patch_player(fight, pid, divine_favor={"patron": patron, "level": level, "max": 100})


@asynccontextmanager
async def unravel_fight(pool) -> AsyncIterator[Fight]:
    fight = Fight(pool)
    with (
        patch("combat_agent.create_combat_agent", CombatAgent),
        patch("db._cache_get", AsyncMock(return_value=None)),
        patch("db._cache_set", AsyncMock()),
        patch.object(dice, "random", SimpleNamespace(SystemRandom=lambda: FixedRng(1))),
    ):
        try:
            await fight.prepare(LOCATION, mage=True)
            await favor(fight, fight.ids[0])
            yield fight
        finally:
            if fight.lifecycle is not None:
                await fight.lifecycle.aclose()
            await pool.execute("DELETE FROM combat_instances WHERE combat_id=ANY($1::text[])", fight.combats)
            await pool.execute("DELETE FROM players WHERE player_id=ANY($1::text[])", fight.ids)


@pytest.fixture
async def unravel(dev_db_pool) -> AsyncIterator[Fight]:
    async with unravel_fight(dev_db_pool) as fight:
        yield fight


async def opening(fight: Fight, rounds: int = 2) -> dict:
    await fight.start()
    for index in range(rounds):
        await fight.declare()
        await fight.finish_round(index + 2)
    return await fight.row()


async def activate(fight: Fight, actor: str | None = None) -> dict:
    return await fight.call("activate", id=GIFT, actor=actor)


async def durable(fight: Fight, *, conn=None) -> dict:
    conn = conn or fight.pool
    players = await conn.fetch(
        "SELECT player_id, data, inventory_revision, patron_revision FROM players "
        "WHERE player_id=ANY($1::text[]) ORDER BY player_id",
        fight.ids,
    )
    slots = await conn.fetch(
        "SELECT player_id, item_id, tainted, data FROM player_inventory "
        "WHERE player_id=ANY($1::text[]) ORDER BY player_id, item_id, tainted",
        fight.ids,
    )
    combat = await conn.fetchval("SELECT data FROM combat_instances WHERE combat_id=$1", fight.combats[-1])
    return {
        "combat": json.loads(combat) if combat is not None else None,
        "players": {row["player_id"]: dict(row, data=json.loads(row["data"])) for row in players},
        "slots": [dict(row, data=json.loads(row["data"])) for row in slots],
    }


def cached(fight: Fight) -> dict:
    session = fight.session
    return {
        "combat": session.combat_state.to_dict() if session.combat_state is not None else None,
        "members": deepcopy(session.party.members),
        "companion": None if session.companion is None else session.companion.is_conscious,
        "fate": session.fate_offer,
        "room": list(session.room.local_participant.publish_data.await_args_list),
        "bus": session.event_bus.qsize,
    }


async def discovered(fight: Fight, actor: str | None = None) -> dict:
    info = await fight.call("query_info", kind="patron", actor=actor)
    return next(row for row in info["abilities"] if row["id"] == GIFT)


def assert_inventory(durable_state: dict, pid: str, expected: list[dict]) -> None:
    assert [slot for slot in durable_state["slots"] if slot["player_id"] == pid] == [
        {"player_id": pid, **slot} for slot in expected
    ]


def assert_restored(fight: Fight, committed: dict, start: dict, actor: str) -> None:
    from combat_round_checkpoint import RESTORE_KEYS

    image = dict(committed["combat"])
    history = image.pop("round_checkpoints")
    assert image == start["combat"]
    assert len(history) == 1 and history[0]["combat"] == image
    assert fight.session.combat_state.to_dict() == committed["combat"]
    for pid, saved in start["players"].items():
        current = committed["players"][pid]["data"]
        expected = deepcopy(saved["data"])
        if pid == actor:
            expected["patron_gifts"][GIFT] = {"spent": True}
            expected["resonance"]["current"] += 8
        assert {key: current[key] for key in RESTORE_KEYS & current.keys()} == {
            key: expected[key] for key in RESTORE_KEYS & expected.keys()
        }
        assert {
            key: value for key, value in current.get("flags", {}).items() if key in {"concealed", "shadow_veil"}
        } == (expected.get("flags", {}))
        assert_inventory(committed, pid, saved["inventory"])
        member = fight.session.member_state(pid)
        assert member.resonance.current == expected["resonance"]["current"]
        assert member.resonance.flickering_bonus == expected["resonance"].get("flickering_bonus", 0)
        assert member.concentration.spell_id == (expected["concentration"] or {}).get("spell_id")
        assert {flag: getattr(member, flag) for flag in saved["session_flags"]} == saved["session_flags"]
        assert history[0]["players"][pid]["session_flags"] == saved["session_flags"]
