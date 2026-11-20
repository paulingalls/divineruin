from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from _mortaen_threshold_fixtures import ENCOUNTER
from _mortaen_threshold_fixtures import fight as catalog_fight
from _zhael_fate_fixtures import defend, game_tools
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from voice_condition_fixtures import place_actors

import db_mutations
from combat_agent import CombatAgent
from combat_participant import CombatParticipant
from combat_state import CombatState
from dice import DiceResult

GIFT = "thyra_wildmothers_wrath"
OTHER_GIFTS = {"thyra_thornwall": {"spent": True}}


def fighter(pid, kind="enemy", hp=50, **fields):
    return CombatParticipant(
        id=pid, name=pid.title(), type=kind, initiative=10, hp_current=hp, hp_max=50, ac=10, **fields
    )


async def checkpoint(world):
    state = world.ctx.userdata.combat_state
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=world.pool)


async def saved(world):
    state = world.ctx.userdata.combat_state
    data = await db_mutations.load_combat_state(state.combat_id, conn=world.pool)
    assert data is not None
    return data


async def snapshot(world):
    session = world.ctx.userdata
    state = session.combat_state
    rows = await world.pool.fetch("SELECT * FROM players WHERE player_id = ANY($1) ORDER BY player_id", world.ids)
    return {
        "players": rows,
        "live": state.to_dict() if state else None,
        "saved": (await saved(world)).to_dict() if state else None,
        "resonance": [m.resonance.current for m in session.party.members],
        "client_events": published_payloads(session.room),
        "recent_events": list(session.recent_events),
        "bus": tuple(session.event_bus._queue._queue),
    }


def add_foe(state, foe):
    state.participants.append(foe)
    state.initiative_order.append(foe.id)
    state.spatial["positions"][foe.id] = {"x": 5, "y": 0, "z": 0}
    state.spatial["speeds"][foe.id] = 30


@asynccontextmanager
async def fight(world, *foes, terrain="forest", patron="thyra", favor=75, encounter=None, archetype="warrior"):
    session = world.ctx.userdata
    async with catalog_fight(
        world,
        patron=patron,
        favor=favor,
        archetype=archetype,
        hp=50,
        max_hp=50,
        guest_hp=50,
        guest_class="warrior",
        gifts=OTHER_GIFTS,
        encounter_id=encounter or ENCOUNTER,
    ):
        lifecycle = session.multiplayer_owner.lifecycle
        generation = await lifecycle.authorize(world.ids[0])
        assert generation and await lifecycle.authorize(world.ids[1])
        state = session.combat_state
        if encounter is None:
            participants = [*(p for p in state.participants if p.type == "player"), fighter("companion", "companion")]
            state = place_actors(
                CombatState(
                    combat_id=state.combat_id,
                    participants=participants,
                    location_id=session.location_id,
                    initiative_order=[p.id for p in participants],
                )
            )
            session.combat_state = state
        state.terrain = terrain
        for foe in foes:
            add_foe(state, foe)
        await checkpoint(world)
        with session._bind_authenticated_actor(world.ids[0], generation, lifecycle.require_authorized):
            yield game_tools(session, agent=CombatAgent())


def rolls():
    return patch("dice.roll", return_value=DiceResult("3d8", [5, 5, 5], [], 15))


async def refuse(world, call, reason):
    before = await snapshot(world)
    with rolls() as dice, pytest.raises(ToolError, match=reason):
        await call("activate", id=GIFT)
    dice.assert_not_called()
    assert await snapshot(world) == before


async def declare(world, call):
    state = world.ctx.userdata.combat_state
    await call("declare_phase", declarations=[defend(p.id) for p in state.participants])
