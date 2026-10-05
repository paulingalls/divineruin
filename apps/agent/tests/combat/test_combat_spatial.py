import json
from copy import deepcopy

import pytest

from combat_spatial import distance, inside, point, position, validate_scene, validate_spatial
from session_data import CombatParticipant, CombatState


def pos(x: float = 0, y: float = 0, z: float = 0):
    return {"x": x, "y": y, "z": z}


def test_radius_boundary():
    assert inside(pos(30), pos(), 30)
    assert not inside(pos(30.00001), pos(), 30)
    assert inside(pos(), pos(), 0)
    assert distance(pos(3, 4, 12), pos()) == 13


@pytest.mark.parametrize("bad", [True, "1", None, float("nan"), float("inf"), -float("inf")])
def test_invalid_geometry_refuses(bad):
    with pytest.raises(ValueError):
        point(pos(bad))
    with pytest.raises(ValueError):
        inside(pos(), pos(), bad)
    with pytest.raises(ValueError):
        validate_spatial({"positions": {"a": pos()}, "locations": {}, "zones": {}, "speeds": {"a": bad}}, ["a"])


def test_invalid_geometry_negative_and_overflow():
    with pytest.raises(ValueError):
        inside(pos(), pos(), -1)
    with pytest.raises(ValueError):
        distance(pos(1e308), pos(-1e308))


def test_unknown_position_refuses():
    with pytest.raises(ValueError):
        position({"positions": {}, "locations": {}}, "missing")
    with pytest.raises(ValueError):
        validate_scene({"enemies": [{"id": "a", "creature_id": "bandit", "role": "standard"}]})


def spatial_state(speed=30):
    state = CombatState(
        "spatial",
        [
            CombatParticipant(id="a", name="A", type="player", initiative=20, hp_current=10, hp_max=10, ac=10),
            CombatParticipant(id="b", name="B", type="enemy", initiative=10, hp_current=10, hp_max=10, ac=10),
        ],
        ["a", "b"],
    )
    state.spatial = {
        "positions": {"a": pos(), "b": pos(40)},
        "speeds": {"a": speed, "b": 20},
        "locations": {"core": pos(30)},
        "zones": {"silence": {"center_id": "a", "radius_ft": 10}},
    }
    return state


def move(actor="a", x=30):
    return {"type": "maneuver", "action": "move", "target_id": actor, "destination": pos(x)}


def test_spatial_roundtrip():
    state = spatial_state()
    saved = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert saved.spatial == state.spatial
    assert saved.spatial is not None and state.spatial is not None
    saved.spatial["positions"]["a"]["x"] = 5
    assert state.spatial["positions"]["a"]["x"] == 0
    invalid = state.to_dict()
    del invalid["spatial"]["positions"]["b"]
    with pytest.raises(ValueError):
        CombatState.from_dict(invalid)


def test_legacy_nonspatial_roundtrip():
    from combat_spatial import facts

    state = spatial_state().to_dict()
    del state["spatial"]
    restored = CombatState.from_dict(state)
    assert restored.spatial is None
    with pytest.raises(ValueError):
        facts(restored, "a")


def test_move_schema_reaches_engine():
    from livekit.agents.llm import ToolContext

    from combat_turn import declare_phase
    from declaration_payloads import AttackDecl, Destination, MoveDecl, to_engine_declarations

    schema = ToolContext([declare_phase]).parse_function_tools("openai", strict=True)
    assert "move" in json.dumps(schema)
    assert "destination" in json.dumps(schema)
    payload = MoveDecl(kind="move", actor_id="a", destination=Destination(x=30, y=0, z=0))
    assert to_engine_declarations([payload]) == {"a": move()}
    with pytest.raises(ValueError, match="more than once"):
        to_engine_declarations(
            [payload, AttackDecl(kind="attack", actor_id="a", action="Sword", target_id="b", rider="")]
        )


def test_move_consumes_one_declaration_and_only_moves_actor():
    from combat_phase import advance_combat_phase
    from combat_spatial_declarations import apply_move

    state = spatial_state()
    before = deepcopy(state.to_dict())
    declared, _ = advance_combat_phase(state, {"a": move()})
    assert list(declared.pending_declarations) == ["a"]
    working, advance = advance_combat_phase(declared)
    packet = advance.packets[0]
    result = apply_move(working, working.get_participant("a"), packet.declaration)
    assert result["moved_ft"] == 30
    assert working.spatial is not None and state.spatial is not None
    assert working.spatial["positions"] == {"a": pos(30), "b": pos(40)}
    assert working.spatial["locations"] == state.spatial["locations"]
    assert state.to_dict() == before


@pytest.mark.parametrize("speed", [0, 20, 30, 35, 40])
def test_move_respects_actual_speed(speed):
    from combat_phase import advance_combat_phase

    state = spatial_state(speed)
    advance_combat_phase(state, {"a": move(x=speed)})
    with pytest.raises(ValueError, match="exceeds speed"):
        advance_combat_phase(state, {"a": move(x=speed + 0.0001)})


@pytest.mark.parametrize("condition", ["stunned", "incapacitated", "paralyzed", "grappled", "restrained", "petrified"])
def test_move_eligibility_refuses(condition):
    from combat_phase import advance_combat_phase
    from combat_spatial_declarations import apply_move
    from declarations import resolve_declaration

    state = spatial_state()
    actor = state.get_participant("a")
    assert actor is not None
    actor.conditions = [{"type": condition, "source": "b", "duration": 2}]
    before = deepcopy(state.to_dict())
    with pytest.raises(ValueError):
        advance_combat_phase(state, {"a": move()})
    assert apply_move(state, state.get_participant("a"), resolve_declaration(move()))["resolved"] is False
    assert state.to_dict() == before


def test_move_fallen_unknown_missing_and_corrupt_refuse():
    from combat_phase import advance_combat_phase

    for change in (
        lambda s: setattr(s.get_participant("a"), "is_fallen", True),
        lambda s: setattr(s, "spatial", None),
        lambda s: s.spatial["positions"].pop("a"),
    ):
        state = spatial_state()
        change(state)
        with pytest.raises(ValueError):
            advance_combat_phase(state, {"a": move()})
    for raw in (move(actor="missing"), {**move(), "destination": pos(float("nan"))}, {**move(), "target_id": "b"}):
        with pytest.raises(ValueError):
            advance_combat_phase(spatial_state(), {"a": raw})


async def test_spatial_ids_and_spoken_distances_are_advertised():
    from livekit.agents.llm import ToolError
    from sample_fixtures import make_context

    from combat_spatial import facts
    from query_tools import _query_info_impl

    ctx = make_context("a")
    ctx.userdata.combat_state = spatial_state()
    result = json.loads(await _query_info_impl(ctx, "combat"))
    assert result == facts(ctx.userdata.combat_state, "a")
    assert result["distances_ft"]["b"] == 40
    assert "b is 40 feet from a" in result["spoken"]
    assert set(result["positions"]) == {"a", "b"}
    assert set(result["locations"]) == {"core"}
    assert list(result["zones"]) == ["silence"]
    assert result["zones"]["silence"]["members"] == ["a"]
    assert ctx.userdata.combat_state.spatial is not None
    ctx.userdata.combat_state.spatial["positions"]["a"] = pos(30)
    refreshed = json.loads(await _query_info_impl(ctx, "combat", "core"))
    assert refreshed["origin_id"] == "core" and refreshed["distances_ft"]["a"] == 0
    assert refreshed["zones"]["silence"]["members"] == ["a", "b"]
    with pytest.raises(ToolError):
        await _query_info_impl(ctx, "combat", "unknown")


def test_actual_speed_sources():
    from sample_fixtures import CONTENT_ROOT

    from combat_spatial_entry import build_spatial
    from companion_profiles import get_companion_profile
    from creature_combat import translate_creature

    templates = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
    creatures = json.loads((CONTENT_ROOT / "content/creatures.json").read_text())
    rows = {row["id"]: row for row in creatures}
    template = templates[0]
    enemies = [
        translate_creature(rows[e["creature_id"]], encounter_id=template["id"], enemy_id=e["id"], role=e["role"])
        for e in template["enemies"]
    ]
    for enemy, ref in zip(enemies, template["enemies"], strict=True):
        assert "speed" in enemy
        assert enemy["speed"] == rows[ref["creature_id"]]["speed"]
    stationary = deepcopy(rows["hollow_shadeling"])
    stationary["speed"] = 0
    assert (
        translate_creature(stationary, encounter_id="stationary", enemy_id="stationary", role="standard")["speed"] == 0
    )
    companions = json.loads((CONTENT_ROOT / "content/companions.json").read_text())
    assert len(companions) == 4
    assert {row["speed"] for row in companions} == {30, 35, 40}
    for row in companions:
        profile = get_companion_profile(row["id"])
        result = build_spatial(template, [("a", {"speed": 30})], enemies, (profile.id, profile.speed))
        assert result["speeds"] == {"a": 30, profile.id: row["speed"], **{e["id"]: e["speed"] for e in enemies}}


def test_combat_tools_unchanged():
    from livekit.agents.llm import ToolContext

    from combat_agent import CombatAgent

    agent = CombatAgent()
    assert isinstance(agent.instructions, str) and "move — actor_id" in agent.instructions
    assert 'query_info(kind="combat")' in agent.instructions
    assert set(ToolContext(agent.tools).function_tools) == {
        "query_info",
        "declare_phase",
        "resolve_phase",
        "consume_legendary_action",
        "check",
        "request_death_save",
        "end_combat",
        "activate",
        "get_spell_info",
    }


@pytest.mark.parametrize("value", [True, "1", float("nan"), float("inf")])
def test_move_wire_refuses_invalid_coordinate(value):
    from declaration_payloads import MoveDecl

    with pytest.raises(ValueError):
        MoveDecl.model_validate({"kind": "move", "actor_id": "a", "destination": pos(value)})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["scene_placement"]["actors"].update(unknown=pos()),
        lambda s: s["scene_placement"]["party_start"].pop("z"),
        lambda s: s["scene_placement"]["locations"].update({" ": pos()}),
        lambda s: s["scene_placement"]["locations"].update(a=pos()),
        lambda s: s["scene_placement"]["zones"].update(zone={"center_id": "a", "radius_ft": -1}),
        lambda s: s["scene_placement"]["zones"].update(zone={"center_id": "unknown", "radius_ft": 1}),
        lambda s: s["scene_placement"]["zones"].update(zone={"radius_ft": 1}),
        lambda s: s["enemies"].append({"id": "a", "creature_id": "bandit", "role": "standard"}),
    ],
)
def test_invalid_scene_guards(mutate):
    scene = {
        "enemies": [{"id": "a", "creature_id": "bandit", "role": "standard"}],
        "scene_placement": {
            "party_start": pos(),
            "companion_start": pos(),
            "actors": {"a": pos(20)},
            "locations": {},
            "zones": {},
        },
    }
    mutate(scene)
    with pytest.raises(ValueError):
        validate_scene(scene)


def test_entry_builder_validates_authored_scene():
    from combat_spatial_entry import build_spatial

    scene = {
        "enemies": [{"id": "b", "creature_id": "bandit", "role": "standard"}],
        "scene_placement": {
            "party_start": pos(),
            "companion_start": pos(),
            "actors": {"b": pos(20)},
            "locations": {},
            "zones": {},
            "unrecognized": {},
        },
    }
    with pytest.raises(ValueError):
        build_spatial(scene, [("a", {"speed": 30})], [{"id": "b", "speed": 20}])


async def test_unpositioned_acting_member_can_still_declare():
    from unittest.mock import AsyncMock

    from sample_fixtures import make_context

    from combat_turn import _declare_phase_impl

    ctx = make_context("a", party_member_ids=["late"])
    ctx.userdata.combat_state = spatial_state()
    with ctx.userdata._bind_authenticated_actor("late", 1, lambda *_args: None):
        result = json.loads(await _declare_phase_impl(ctx, {"a": move()}, mutations=AsyncMock()))
    assert result["spatial"]["origin_id"] == "a"
