"""Runtime walls through persisted encounters and the combat tools."""

import json
from copy import deepcopy
from typing import Any
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die, _resolve_round
from acceptance._spatial_helpers import persisted, pos
from acceptance._spatial_helpers import spatial_entry as spatial_entry
from acceptance._structure_helpers import _move, _refuses, _reload, _save_and_reload, _strike

import combat_spatial
from combat_state import CombatState
from combat_structures import add_wall
from combat_turn import declare_phase, resolve_phase
from declaration_payloads import DefendDecl, InteractDecl, ManeuverDecl
from query_tools import query_info

WALL = "stone_wall"
NAME = "Stone Wall"
START = pos(10, -5)
END = pos(10, 5, 4)


@pytest.fixture
def mock_combat_agent_factory() -> None:
    return None


async def _move_and_resolve(ctx: Any, actor_id: str, destination: dict) -> None:
    await declare_phase(ctx, [_move(actor_id, destination)])
    result = await _resolve_round(ctx)
    assert any(p.get("destination") == destination and p["actor_id"] == actor_id for p in result["packets"])
    assert (await persisted(ctx.userdata.combat_state.combat_id))["spatial"]["positions"][actor_id] == destination


@pytest.mark.parametrize(
    ("origin", "destination", "blocked"),
    [
        pytest.param(pos(), pos(20), True, id="crossing"),
        pytest.param(pos(0, 5), pos(20, 5), True, id="wall-endpoint"),
        pytest.param(pos(10), pos(20), True, id="path-start"),
        pytest.param(pos(), pos(10), True, id="path-end"),
        pytest.param(pos(0, -5), pos(20, -5), True, id="other-wall-endpoint"),
        pytest.param(pos(0, 6), pos(20, 6), False, id="past-endpoint"),
        pytest.param(pos(0, -6), pos(20, -6), False, id="before-endpoint"),
        pytest.param(pos(), pos(9), False, id="short-of-wall"),
        pytest.param(pos(11), pos(20), False, id="away-from-wall"),
        pytest.param(pos(0, z=20), pos(20, z=20), True, id="top-face"),
        pytest.param(pos(0, z=20.01), pos(20, z=20.01), False, id="above"),
        pytest.param(pos(0, z=-0.01), pos(20, z=-0.01), False, id="below"),
        pytest.param(pos(8, z=-1), pos(12, z=21), True, id="sloped-crossing"),
        pytest.param(pos(9, z=-3), pos(15, z=3), False, id="sloped-intersection-below"),
        pytest.param(pos(15, -8), pos(15, 8), False, id="parallel-disjoint"),
        pytest.param(pos(10, -12), pos(10, -6), False, id="collinear-disjoint"),
        pytest.param(pos(10, 6), pos(10, 12), False, id="collinear-moving-away"),
        pytest.param(pos(10, -12), pos(10, -5), True, id="collinear-endpoint"),
        pytest.param(pos(10, -12), pos(10, 8), True, id="collinear-overlap"),
        pytest.param(pos(10, 8), pos(10, -12), True, id="collinear-reversed"),
        pytest.param(pos(10, -8, -8), pos(10, 8, 3), True, id="collinear-height-near-end"),
        pytest.param(pos(10, -8, 3), pos(10, 8, -8), True, id="collinear-height-near-start"),
        pytest.param(pos(10, -8, 21), pos(10, 8, 23), False, id="collinear-above"),
        pytest.param(pos(10, -8, 28), pos(10, 8, 17), True, id="collinear-height-near-top"),
        pytest.param(pos(10, z=-2), pos(10, z=22), True, id="vertical-through"),
        pytest.param(pos(10, 6, -2), pos(10, 6, 22), False, id="vertical-outside-segment"),
        pytest.param(pos(10, -6, -2), pos(10, -6, 22), False, id="vertical-before-segment"),
        pytest.param(pos(11, z=-2), pos(11, z=22), False, id="vertical-off-line"),
    ],
)
async def test_wall_movement(spatial_entry: Any, origin: dict, destination: dict, blocked: bool) -> None:
    ctx, _ = await spatial_entry()
    state = ctx.userdata.combat_state
    actor_id = ctx.userdata.player_id
    combat_spatial.place(state, actor_id, origin)
    add_wall(state, WALL, NAME, START, END)
    await _save_and_reload(ctx)
    if blocked:
        await _refuses(ctx, _move(actor_id, destination), r"Stone Wall \(stone_wall\)")
    else:
        await _move_and_resolve(ctx, actor_id, destination)


async def test_enemy_walks_around_wall(spatial_entry: Any) -> None:
    ctx, _ = await spatial_entry()
    state = ctx.userdata.combat_state
    actor_id = "mawling_1"
    combat_spatial.place(state, actor_id, pos())
    add_wall(state, "far_wall", "Outlying Wall", pos(10, 30), pos(10, 40))
    add_wall(state, WALL, NAME, END, START)
    await _save_and_reload(ctx)
    await _refuses(ctx, _move(actor_id, pos(20)), r"Stone Wall \(stone_wall\)")
    for destination in (pos(8, 6), pos(12, 6), pos(20)):
        await _move_and_resolve(ctx, actor_id, destination)


async def test_direct_placement_passes_through_wall(spatial_entry: Any) -> None:
    ctx, _ = await spatial_entry()
    state = ctx.userdata.combat_state
    actor_id = ctx.userdata.player_id
    assert state.spatial["positions"][actor_id] == pos()
    add_wall(state, WALL, NAME, START, END)
    combat_spatial.place(state, actor_id, pos(20))
    saved = await _save_and_reload(ctx)
    assert saved.spatial is not None
    assert saved.spatial["positions"][actor_id] == pos(20)
    assert saved.spatial["structures"] == {WALL: {"start": START, "end": END}}


async def test_wall_cannot_act_or_be_shoved(spatial_entry: Any) -> None:
    ctx, _ = await spatial_entry()
    add_wall(ctx.userdata.combat_state, WALL, NAME, START, END)
    await _save_and_reload(ctx)
    await _refuses(ctx, InteractDecl(kind="interact", actor_id=WALL, action="rattle"), "cannot act")
    await _refuses(
        ctx, ManeuverDecl(kind="maneuver", actor_id=ctx.userdata.player_id, target_id=WALL), "cannot be maneuvered"
    )


@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ("no_spatial", "requires spatial placement"),
        ("missing_segment", "exactly the live structures"),
        ("unknown_segment", "exactly the live structures"),
        ("duplicate_wall_id", "unique participant ID"),
        ("ordinary_actor_segment", "exactly the live structures"),
        ("destroyed_with_segment", "exactly the live structures"),
        ("moving_wall", "invalid structure speed"),
        ("wrong_ac", "invalid structure stats"),
        ("wrong_max_hp", "invalid structure stats"),
        ("negative_hp", "invalid live structure HP"),
        ("zero_live_hp", "invalid live structure HP"),
        ("above_max_hp", "invalid live structure HP"),
        ("boolean_hp", "invalid live structure HP"),
        ("fallen_but_alive", "invalid destroyed structure"),
        ("dead_but_not_fallen", "invalid destroyed structure"),
        ("destroyed_with_hp", "invalid destroyed structure"),
    ],
)
def test_corrupt_wall_linkage_refuses_load(corruption: str, message: str) -> None:
    from combat_participant import CombatParticipant

    actor = CombatParticipant(id="foe", name="Foe", type="enemy", initiative=10, hp_current=10, hp_max=10, ac=12)
    state = CombatState(
        combat_id="wall_linkage",
        participants=[actor],
        initiative_order=[actor.id],
        spatial={"positions": {actor.id: pos()}, "locations": {}, "zones": {}, "speeds": {actor.id: 30}},
    )
    wall = add_wall(state, WALL, NAME, START, END)
    assert state.spatial is not None
    if corruption == "no_spatial":
        state.spatial = None
    elif corruption in ("missing_segment", "unknown_segment", "ordinary_actor_segment"):
        segment = state.spatial["structures"].pop(WALL)
        replacement = {"unknown_segment": "unknown", "ordinary_actor_segment": actor.id}.get(corruption)
        if replacement:
            state.spatial["structures"][replacement] = segment
    elif corruption == "duplicate_wall_id":
        state.participants.append(deepcopy(wall))
    elif corruption == "moving_wall":
        state.spatial["speeds"][WALL] = 30
    elif corruption == "wrong_ac":
        wall.ac = 18
    elif corruption == "wrong_max_hp":
        wall.hp_max = 31
    elif corruption in ("negative_hp", "zero_live_hp", "above_max_hp", "boolean_hp"):
        wall.hp_current = {"negative_hp": -1, "zero_live_hp": 0, "above_max_hp": 31, "boolean_hp": True}[corruption]
    else:
        wall.is_fallen = corruption != "dead_but_not_fallen"
        wall.is_dead = corruption != "fallen_but_alive"
        wall.hp_current = 5 if corruption == "destroyed_with_hp" else 0
        if corruption != "destroyed_with_segment":
            del state.spatial["structures"][WALL]
    with pytest.raises(ValueError, match=message):
        CombatState.from_dict(state.to_dict())


async def test_attacks_damage_hold_and_destroy_wall(spatial_entry: Any) -> None:
    ctx, _ = await spatial_entry(members=2)
    state = ctx.userdata.combat_state
    player = ctx.userdata.player_id
    other = next(p.id for p in state.participants if p.is_ally and p.id != player)
    for actor_id in (player, other):
        combat_spatial.place(state, actor_id, pos(5))
        state.get_participant(actor_id).attributes["strength"] = 16
    add_wall(state, WALL, NAME, START, END)
    other_wall = {"start": pos(10, 30), "end": pos(10, 35)}
    add_wall(state, "far_wall", "Far Wall", **other_wall)
    saved = await _save_and_reload(ctx)
    wall = saved.get_participant(WALL)
    assert wall is not None and saved.spatial is not None
    assert (wall.ac, wall.hp_current, wall.hp_max, saved.spatial["speeds"][WALL]) == (19, 30, 30, 0)
    assert saved.spatial["positions"][WALL] == pos(10)
    assert WALL not in saved.initiative_order

    roster = json.loads(await declare_phase(ctx, [DefendDecl(kind="defend", actor_id=player)]))["participants"]
    target = next(p["id"] for p in roster if p["name"] == NAME and p["type"] == "structure" and p["ac"] == 19)
    await _resolve_round(ctx)
    strike = _strike(player, target)
    denied_move = _move(player, pos(20))
    refusal = r"Stone Wall \(stone_wall\)"

    await declare_phase(ctx, [strike])
    with patch("check_resolution.dice_roll", return_value=_d20(14)):
        miss = await _resolve_round(ctx)
    assert any(p.get("target") == NAME and p["damage"] == 0 for p in miss["packets"])
    wall = (await _reload(ctx)).get_participant(target)
    assert wall is not None and wall.hp_current == 30

    await declare_phase(ctx, [strike, DefendDecl(kind="defend", actor_id="mawling_1")])
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
    ):
        pause = json.loads(await resolve_phase(ctx))
    assert any(p.get("target") == NAME and p["damage"] == 10 for p in pause["packets"]), pause["packets"]
    before = ctx.userdata.combat_state
    assert [action["actor_id"] for action in before.held_actions] == ["mawling_1"]
    assert before.spatial["structures"] == {WALL: {"start": START, "end": END}, "far_wall": other_wall}
    assert before.get_participant(target).hp_current == 20
    assert (await _reload(ctx)).to_dict() == before.to_dict()
    resumed = await _resolve_round(ctx)
    assert any(p["actor_id"] == "mawling_1" for p in resumed["packets"])
    await _refuses(ctx, denied_move, refusal)
    await _move_and_resolve(ctx, player, pos(5, 1))
    await _move_and_resolve(ctx, player, pos(5))
    await _refuses(ctx, denied_move, refusal)

    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
    ):
        await declare_phase(ctx, [strike])
        await _resolve_round(ctx)
        wall = (await _reload(ctx)).get_participant(target)
        assert wall is not None and wall.hp_current == 10
        await declare_phase(ctx, [strike, _strike(other, target)])
        destroyed = await _resolve_round(ctx)
    assert any(p.get("target") == NAME and p["damage"] == 10 for p in destroyed["packets"])
    assert any(p.get("reason") == f"{NAME} already fell" for p in destroyed["packets"])
    assert target not in destroyed["death_saves_due"]
    saved = await _reload(ctx)
    wall = saved.get_participant(target)
    assert wall is not None and wall.hp_current == wall.death_save_failures == 0 and wall.is_fallen and wall.is_dead
    assert saved.spatial is not None and saved.spatial["structures"] == {"far_wall": other_wall}
    await _move_and_resolve(ctx, player, pos(20))

    foes = [p for p in saved.participants if p.type == "enemy"]
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
    ):
        for foe in foes:
            await declare_phase(ctx, [_strike(player, foe.id)])
            result = await _resolve_round(ctx)
    assert isinstance(result, tuple)
    victory = json.loads(result[1])
    assert victory["outcome"] == "victory"
    assert victory["xp_total"] == sum(foe.xp_value for foe in foes)
    assert sorted(victory["defeated_enemies"]) == sorted(foe.name for foe in foes)
    assert ctx.userdata.combat_state is None


async def test_combat_facts_show_each_wall_and_its_pairs(spatial_entry) -> None:
    ctx, _ = await spatial_entry()
    state = ctx.userdata.combat_state
    player = ctx.userdata.player_id
    combat_spatial.place(state, player, pos())
    combat_spatial.place(state, "mawling_1", pos(20))
    combat_spatial.place(state, "mawling_2", pos(0, 30))
    add_wall(state, "wall", "Slate Wall", pos(10, -5), pos(10, 5)).hp_current = 1
    add_wall(state, "second", "Second Wall", pos(12, -5), pos(12, 5))
    add_wall(state, "away", "Outlying Wall", pos(50, -5), pos(50, 5))
    await _save_and_reload(ctx)
    facts = json.loads(await query_info(ctx, "combat", "mawling_2"))
    assert facts["walls"] == [
        {"id": "away", "name": "Outlying Wall", "segment": {"start": pos(50, -5), "end": pos(50, 5)}, "separates": []},
        {
            "id": "second",
            "name": "Second Wall",
            "segment": {"start": pos(12, -5), "end": pos(12, 5)},
            "separates": [["mawling_1", player]],
        },
        {
            "id": "wall",
            "name": "Slate Wall",
            "segment": {"start": pos(10, -5), "end": pos(10, 5)},
            "separates": [["mawling_1", player]],
        },
    ]
    assert len([line for line in facts["spoken"] if "Wall" in line]) == 2
    declaration = json.loads(await declare_phase(ctx, [_strike(player, "wall")]))
    assert declaration["spatial"]["walls"] == facts["walls"]
    await _reload(ctx)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        resolved = await _resolve_round(ctx)
    assert resolved["spatial"]["walls"] == facts["walls"][:2]
    assert json.loads(await query_info(ctx, "combat", "mawling_2"))["walls"] == facts["walls"][:2]
