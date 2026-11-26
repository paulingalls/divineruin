"""Unmoored Step through the registered combat tools and persisted combat rows."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import defend
from _zhael_unravel_fixtures import activate, favor, patch_player, unravel_fight
from acceptance._capstone_helpers import _d20
from livekit.agents.llm import ToolError
from test_encounter_facts_damage import GOBLIN, OTHER, Fight, dice, fight
from voice_condition_fixtures import participant

import db_mutations
from _gods_content import load_gods
from combat_spatial import require_spatial
from combat_state import CombatState
from combat_structures import THORNWALL, add_wall
from reaction_spend import unspent

STEP = "nythera_tidal_step"
EFFECT = "Once per encounter, one of your moves, up to your normal movement, provokes no opportunity attacks"


def point(x: int, y: int = 0) -> dict:
    return {"x": x, "y": y, "z": 0}


def move(actor: str, x: int, *, opt_in: bool = True) -> dict:
    return {
        "kind": "move",
        "actor_id": actor,
        "destination": point(x),
        "movement_mode": "ground",
        "reshape": [],
        "nythera_step": opt_in,
    }


def spent(state: CombatState) -> list[str]:
    return state.encounter_facts["once_spent"].get(STEP, [])


def arrange(f: Fight) -> CombatState:
    state = f.session.combat_state
    require_spatial(state)["positions"].update({f.hero: point(0), GOBLIN: point(3), OTHER: point(-20)})
    return state


def receipt(packets: list[dict], actor: str, destination: dict) -> None:
    packet = next(p for p in packets if p["actor_id"] == actor)
    assert packet["resolved"] and packet["destination"] == destination
    assert packet["synergy_clause_id"] == STEP and packet["nythera_step_spent"] is True
    assert "Nythera's Unmoored Step" in packet["dm_cue"] and "spent" in packet["dm_cue"]


async def tidal_step(world: SimpleNamespace, archetype: str, provokes: bool) -> None:
    async with fight(world, "nythera", archetype=archetype) as f:
        starting = arrange(f)
        hp = participant(starting, f.hero).hp_current
        endpoint = 20 if provokes else 2
        await f.declare(move(f.hero, endpoint))
        pending = await f.reload()
        assert not spent(pending)
        assert pending.pending_declarations[f.hero]["nythera_step"] is True
        with (
            patch("check_resolution.dice_roll", return_value=_d20(1)) as rolls,
            patch("check_resolution_attack.dice_roll") as damage,
        ):
            result = await f.call("resolve_phase")
        assert result["beat"] == "narration" and result["next"]["waiting_on"] is None
        assert not any(p.get("opportunity_attack") for p in result["packets"])
        rolls.assert_not_called()
        damage.assert_not_called()
        receipt(result["packets"], f.hero, point(endpoint))
        settled = await f.reload()
        assert settled.open_window is None
        assert settled.reactions_available[GOBLIN] == unspent()
        assert participant(settled, f.hero).hp_current == hp
        assert require_spatial(settled)["positions"][f.hero] == point(endpoint)
        assert spent(settled) == [f.hero]


SCENARIOS = {STEP: ("patron_synergy_combat:spend_tidal_step", tidal_step, [("skirmisher", True), ("rogue", False)])}


async def assert_refused(world: SimpleNamespace, f: Fight, declaration: dict, reason: str) -> None:
    async def persisted() -> tuple:
        combat = await db_mutations.load_combat_state(f.combat_id)
        players = await world.pool.fetch(
            "SELECT data FROM players WHERE player_id=ANY($1) ORDER BY player_id", world.ids
        )
        return (combat.to_dict() if combat else None, players)

    before = await persisted()
    session = deepcopy(f.session.combat_state.to_dict())
    with pytest.raises(ToolError, match=reason):
        await f.declare(declaration)
    assert await persisted() == before
    assert f.session.combat_state.to_dict() == session


@pytest.mark.parametrize("already_spent,endpoint", [(False, 20), (True, 20), (False, 2)])
async def test_plain_movement(world: SimpleNamespace, already_spent: bool, endpoint: int) -> None:
    async with fight(world, "nythera", archetype="skirmisher") as f:
        arrange(f)
        if already_spent:
            receipt(await f.round(move(f.hero, 20), faces=(1,)), f.hero, point(20))
            state = arrange(f)
            await db_mutations.save_combat_state(f.combat_id, state.to_dict())
            await assert_refused(world, f, move(f.hero, 20), "Unmoored Step.*already spent")
        await f.declare(move(f.hero, endpoint, opt_in=False))
        with dice(1):
            result = await f.call("resolve_phase")
        provokes = endpoint == 20
        assert any(p.get("opportunity_attack") and p["actor_id"] == GOBLIN for p in result["packets"]) is provokes
        state = await f.reload()
        assert state.reactions_available[GOBLIN]["spent"] is provokes
        assert spent(state) == ([f.hero] if already_spent else [])


@pytest.mark.parametrize(
    "patron,archetype,actor_type,reason",
    [
        ("kaelen", "skirmisher", "player", "Unmoored Step.*requires"),
        ("nythera", "warrior", "player", "Unmoored Step.*requires"),
        ("nythera", "skirmisher", "companion", "Unmoored Step.*has no player row"),
        ("nythera", "rogue", "temporary_hollowed", "Unmoored Step.*requires a player combatant"),
    ],
)
async def test_ineligible_opt_in(
    world: SimpleNamespace, patron: str, archetype: str, actor_type: str, reason: str
) -> None:
    async with fight(world, patron, archetype=archetype) as f:
        state = arrange(f)
        actor = f.hero
        if actor_type == "temporary_hollowed":
            participant(state, actor).type = actor_type
        elif actor_type == "companion":
            actor = "companion_kael"
            spatial = require_spatial(state)
            ally = participant(state, f.ally)
            ally.id, ally.type = actor, "companion"
            state.initiative_order[state.initiative_order.index(f.ally)] = actor
            for key in ("positions", "speeds"):
                spatial[key][actor] = spatial[key].pop(f.ally)
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        await assert_refused(world, f, move(actor, 20), reason)


@pytest.mark.parametrize("late_wall", [False, True])
async def test_refused_move_can_try_again(world: SimpleNamespace, late_wall: bool) -> None:
    async with fight(world, "nythera", archetype="skirmisher") as f:
        state = arrange(f)
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        if late_wall:
            await f.declare(move(f.hero, 20))
            state = await f.reload()
            add_wall(state, "late_thornwall", "Thornwall", point(10, -5), point(10, 5), kind=THORNWALL)
            await db_mutations.save_combat_state(f.combat_id, state.to_dict())
            result = await f.call("resolve_phase")
            packet = next(p for p in result["packets"] if p["actor_id"] == f.hero)
            assert not packet["resolved"] and "Thornwall" in packet["reason"]
            assert "nythera_step_spent" not in packet
            await f.call("resolve_phase")
        else:
            await assert_refused(world, f, move(f.hero, 31), "exceeds speed")
        state = await f.reload()
        assert not spent(state)
        assert require_spatial(state)["positions"][f.hero] == point(0)
        receipt(await f.round(move(f.hero, -10), faces=(1,)), f.hero, point(-10))


async def test_uses_are_per_player(world: SimpleNamespace) -> None:
    async with fight(world, "nythera", archetype="skirmisher") as f:
        await configure(world, "nythera", "rogue", index=1)
        arrange(f)
        receipt(await f.round(move(f.hero, 20), faces=(1,)), f.hero, point(20))
        assert spent(await f.reload()) == [f.hero]
        receipt(await f.round(move(f.ally, -10), faces=(1,)), f.ally, point(-10))
        assert spent(await f.reload()) == [f.hero, f.ally]


async def test_inconsistent_saved_spend_cannot_settle_twice(world: SimpleNamespace) -> None:
    async with fight(world, "nythera", archetype="skirmisher") as f:
        arrange(f)
        await f.declare(move(f.hero, 20))
        inconsistent = await f.reload()
        inconsistent.encounter_facts["once_spent"][STEP] = [f.hero]
        before = deepcopy(inconsistent.to_dict())
        await db_mutations.save_combat_state(f.combat_id, before)
        with pytest.raises(RuntimeError, match=r"Unmoored Step was already spent"):
            await f.call("resolve_phase")
        assert f.session.combat_state.to_dict() == before
        assert (await f.reload()).to_dict() == before


@pytest.mark.parametrize("rewind", [False, True])
async def test_encounter_lifetime(world: SimpleNamespace, rewind: bool) -> None:
    async with unravel_fight(world.pool) as f:
        _, mover = f.ids
        await favor(f, mover, "nythera")
        await patch_player(f, mover, **{"class": "rogue"})
        await f.start()
        old_combat = f.combats[-1]

        def orders() -> list[dict]:
            state = f.session.combat_state
            origin = require_spatial(state)["positions"][mover]
            return [
                {**move(mover, origin["x"] + 1), "destination": {**origin, "x": origin["x"] + 1}},
                *(defend(p.id) for p in state.participants if p.id != mover and not p.is_structure),
            ]

        async def take_step() -> None:
            declaration, *others = orders()
            await f.declare(declaration, *others)
            result = await f.call("resolve_phase")
            receipt(result["packets"], mover, declaration["destination"])
            assert (await f.row())["encounter_facts"]["once_spent"][STEP] == [mover]

        await take_step()
        await f.finish_round(2)
        saved = await f.reload()
        assert saved["encounter_facts"]["once_spent"][STEP] == [mover]
        if rewind:
            with pytest.raises(ToolError, match=r"Unmoored Step.*already spent"):
                await f.declare(*orders())
            assert (await activate(f))["round"] == 1
        else:
            await f.call("end_combat", outcome="fled")
            assert await db_mutations.load_combat_state(old_combat, conn=f.pool) is None
            await f.start()
            assert f.combats[-1] != old_combat
        assert STEP not in (await f.row())["encounter_facts"]["once_spent"]
        await take_step()


def test_actual_catalog_pins_unmoored_step() -> None:
    nythera = next(god for god in load_gods() if god["god_id"] == "nythera")
    for archetype in ("skirmisher", "rogue"):
        assert nythera["layer_4_synergy_matrix"][archetype] == {
            "type": "unexpected",
            "name": "Unmoored Step",
            "clauses": [{"effect": EFFECT, "status": "active", "resolution": "engine", "implementation_id": STEP}],
        }
