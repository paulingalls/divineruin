import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from _zhael_fate_fixtures import game_tools
from combat._round_checkpoint_helpers import Fight
from livekit.agents.llm import ToolError
from sample_fixtures import FixedRng, make_context, make_mock_room
from test_aelora_gift import _live_party

import dice
from combat_agent import CombatAgent
from session_data import CompanionState

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


async def adopt_opening(fight: Fight) -> None:
    """Count out-of-band player writes made since the wrap as part of the current round's opening."""
    from combat_round_checkpoint import read_party

    state = fight.session.combat_state
    saved = state.round_checkpoints[-1]["players"]
    for pid, image in (await read_party(fight.pool, sorted(saved))).items():
        saved[pid].update(image)
    await fight.write_row(state.to_dict())


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
            key: value
            for key, value in current.get("flags", {}).items()
            if key in {"concealed", "shadow_veil", "encounter_concealment"}
        } == (expected.get("flags", {}))
        assert_inventory(committed, pid, saved["inventory"])
        member = fight.session.member_state(pid)
        assert member.resonance.current == expected["resonance"]["current"]
        assert member.resonance.flickering_bonus == expected["resonance"].get("flickering_bonus", 0)
        assert member.concentration.spell_id == (expected["concentration"] or {}).get("spell_id")
        assert {flag: getattr(member, flag) for flag in saved["session_flags"]} == saved["session_flags"]
        assert history[0]["players"][pid]["session_flags"] == saved["session_flags"]


async def assert_refused(
    fight: Fight, reason: str, actor: str | None = None, *, selectors: Mapping[str, object] | None = None
) -> None:
    before, scratch = await durable(fight), cached(fight)
    state = fight.session.combat_state
    offer = fight.session.fate_offer
    with pytest.raises(ToolError, match=reason):
        await fight.call("activate", id=GIFT, actor=actor, **(selectors or {}))
    assert await durable(fight) == before
    assert fight.session.combat_state is state
    assert fight.session.fate_offer is offer
    assert cached(fight) == scratch


async def adopt_fresh_context(fight, *, same_session: bool = False) -> None:
    actor = fight.ids[0]
    previous = fight.session
    await fight.lifecycle.aclose()
    fight.session = make_context(
        actor, previous.location_id, room=make_mock_room(), party_member_ids=fight.ids
    ).userdata
    if previous.companion is not None:
        fight.session.companion = CompanionState(id=previous.companion.id, name=previous.companion.name)
    if same_session:
        fight.session.session_id = previous.session_id
        fight.session.patron_ability_entries = previous.patron_ability_entries.copy()
    fight.lifecycle = _live_party(fight.session, *fight.ids)
    fight.tools = game_tools(fight.session, agent=CombatAgent())
    await fight.reload()
