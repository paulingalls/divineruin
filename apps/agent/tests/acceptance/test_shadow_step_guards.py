"""Shadow Step refusals at declaration and after the battlefield changes."""

import pytest
from acceptance._enemy_opportunity_helpers import attack, declare, resolve_allies
from acceptance._shadow_step_helpers import DESTINATION, step
from acceptance._shadow_step_helpers import shadow_fight as shadow_fight
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_architect_reaction import forced_rolls
from acceptance.test_opportunity_strike import participant
from acceptance.test_self_buff_electives import receipt
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import architect_entomb
import combat_spatial
import combat_structures
from combat_state import CombatState
from declarations import resolve_declaration


def cover_wall(state: CombatState, start: dict, end: dict) -> str:
    assert state.architect_encounter is not None
    wall = state.architect_encounter["structure_ids"][0]
    combat_structures.move_wall(state, wall, start, end)
    return wall


def trap(state: CombatState, rogue: str) -> None:
    record = state.architect_encounter
    assert record is not None
    record["floors"]["test_floor"] = {"min": pos(-2, -2), "max": pos(2, 2)}
    record["pits"][rogue] = "test_floor"


@pytest.mark.parametrize(
    "case,reason",
    [
        ("open", "cover"),
        ("outside_wall", "cover"),
        ("outside_chamber", "cover"),
        ("outside_smoke", "cover"),
        ("silence", "cover"),
        ("untyped_zone", "cover"),
        ("too_far", "speed"),
        ("terrain", "speed"),
        ("blocked", "blocked by Architect"),
        ("pit", "Climb out of the pit"),
    ],
)
async def test_refused_declarations_leave_the_snapshot_unchanged(
    shadow_fight: MawlingHarness, case: str, reason: str
) -> None:
    walk = shadow_fight
    rogue, ally = walk.players
    state = await walk.reload()
    spatial = combat_spatial.require_spatial(state)
    destination = DESTINATION
    if case == "outside_wall":
        cover_wall(state, pos(25, 5.01), pos(45, 5.01))
    elif case == "outside_chamber":
        combat_spatial.place(state, ally, pos(25, 5.01))
        architect_entomb.land(state, participant(state, "architect"), participant(state, ally), {"save_success": False})
    elif case == "outside_smoke":
        combat_spatial.place(state, ally, pos(25, 10.01))
        combat_spatial.add_smoke(state, ally)
    elif case == "silence":
        spatial["zones"]["silence"] = {"kind": "silence", "center_id": ally, "radius_ft": 10}
    elif case == "untyped_zone":
        spatial["zones"]["untyped_zone"] = {"center_id": ally, "radius_ft": 10}
    elif case in ("too_far", "terrain", "blocked", "pit"):
        if case == "too_far":
            destination = pos(31)
        cover_wall(state, pos(destination["x"] - 5, 4), pos(destination["x"] + 15, 4))
        if case == "terrain":
            spatial["movement_areas"]["rough"] = {
                "kind": "difficult_terrain",
                "shape": "rectangle",
                "min": pos(5, -2),
                "max": pos(20, 2),
                "excluded_actor_ids": [],
            }
        if case == "blocked":
            assert state.architect_encounter is not None
            combat_structures.move_wall(state, state.architect_encounter["structure_ids"][1], pos(12, -5), pos(12, 5))
        if case == "pit":
            trap(state, rogue)
    await walk.persist()

    before = await walk.snapshot()
    refusal = await walk.command("declare_phase", {"declarations": [step(rogue, destination)]}, error=True)
    assert reason in refusal, refusal
    assert await walk.snapshot() == before


def test_unrelated_engine_ability_refuses_destination() -> None:
    with pytest.raises(ValueError, match="destination"):
        resolve_declaration({"type": "ability", "action": "rogue_vanish", "destination": DESTINATION})


@pytest.mark.parametrize(
    "change,reason", [("destroyed", "cover"), ("raised", "blocked by Architect"), ("pit", "Climb out of the pit")]
)
async def test_queued_step_rechecks_the_battlefield(shadow_fight: MawlingHarness, change: str, reason: str) -> None:
    walk = shadow_fight
    rogue, ally = walk.players
    state = await walk.reload()
    wall = cover_wall(state, pos(20, 4), pos(40, 4))
    supporter = participant(state, ally)
    supporter.initiative = participant(state, rogue).initiative + 10
    state.initiative_order.remove(ally)
    state.initiative_order.insert(0, ally)
    if change == "destroyed":
        combat_spatial.place(state, ally, pos(25, 8))
        participant(state, wall).hp_current = 1
        support = [attack(ally, wall, "Longsword")]
    elif change == "raised":
        combat_spatial.place(state, ally, pos(12, -25))
        combat_spatial.place(state, "architect", pos(12, 25))
        supporter.action_pool = [
            {"name": "Shortbow", "damage": "1d6", "damage_type": "piercing", "properties": ["ranged", "shortbow"]}
        ]
        support = [attack(ally, "architect", "Shortbow")]
    else:
        support = []
    await walk.persist()

    await declare(walk, step(rogue, DESTINATION), *support)
    if change == "pit":
        trap(await walk.reload(), rogue)
        await walk.persist()
    before_combat, before_players = await walk.snapshot()
    with forced_rolls():
        packets = await resolve_allies(walk)

    refused = receipt(packets, rogue)
    assert refused["resolved"] is False and refused["declaration_type"] == "ability"
    assert reason in refused["reason"]
    after_combat, after_players = await walk.snapshot()
    assert after_combat["spatial"]["positions"][rogue] == before_combat["spatial"]["positions"][rogue]
    before, after = before_players[0], after_players[0]
    assert before is not None and after is not None
    for field in ("stamina", "focus", "flags"):
        assert after[field] == before[field]
    if change in ("destroyed", "raised"):
        earlier = receipt(packets, ally)
        assert earlier["hit"] and packets.index(earlier) < packets.index(refused)
    if change == "destroyed":
        assert wall not in after_combat["spatial"]["structures"]
    if change == "raised":
        assert set(after_combat["spatial"]["structures"]) - set(before_combat["spatial"]["structures"])
    if change == "pit":
        assert after_combat["architect_encounter"]["pits"][rogue] == "test_floor"
