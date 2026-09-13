"""One mapping case per `declare_phase` variant, plus the vocabulary tie to the engine.

`to_engine_declarations` is the only thing between the LLM's sum-typed argument and
`combat_phase.advance_combat_phase`, whose participant-keyed dict shape the reshape left
untouched — so these cases are what say the reshape preserved behaviour. Each mapped dict
is fed through `declarations.resolve_declaration`, the engine's own classifier, rather
than only compared to a literal: a variant that satisfies the schema but not the engine
would otherwise pass here and ValueError on the DM's first call.
"""

import ast
import json
import typing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _damage_resolver, _make_combat_state
from livekit.agents.llm import ToolContext
from sample_fixtures import make_context

import combat_turn
from combat_packet import _resolve_one_packet
from combat_phase import ResolutionPacket, advance_combat_phase
from combat_support import _participant_roster
from declaration_payloads import (
    DECL_VARIANTS,
    AbilityDecl,
    AttackDecl,
    DefendDecl,
    InteractDecl,
    ManeuverDecl,
    RetreatDecl,
    to_engine_declarations,
)
from declarations import DeclarationType, resolve_declaration


def _calls(source: Path, function_name: str) -> bool:
    tree = ast.parse(source.read_text())
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == function_name
        for node in ast.walk(tree)
    )


def test_production_and_m29_use_the_shared_action_roster():
    tests_dir = Path(__file__).resolve().parents[1]
    combat_init = tests_dir.parent / "combat_init.py"
    acceptance = tests_dir / "acceptance" / "test_m29_combat_reactions.py"

    assert _calls(combat_init, "_participant_roster")
    assert _calls(acceptance, "_participant_roster")
    acceptance_tree = ast.parse(acceptance.read_text())
    assert not any(
        isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Subscript)
            and isinstance(target.slice, ast.Constant)
            and target.slice.value == "actions"
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
        for node in ast.walk(acceptance_tree)
    )

    state = _make_combat_state()
    companion, enemy = state.participants
    companion.type = "companion"
    companion.action_pool = [{"name": "Longsword"}]
    assert [p["actions"] for p in _participant_roster([companion, enemy])] == [["Longsword"], ["Scimitar"]]


@pytest.mark.asyncio
async def test_catalog_condition_action_is_invocable_from_the_produced_name():
    catalog_path = Path(__file__).resolve().parents[4] / "content" / "encounter_templates.json"
    catalog = json.loads(catalog_path.read_text())
    inventory = [
        (encounter["id"], enemy["id"], action["name"], action["applies_condition"])
        for encounter in catalog
        for enemy in encounter["enemies"]
        for action in enemy["action_pool"]
        if action.get("applies_condition")
    ]
    assert inventory == [("hollow_patrol_greyvale", "hollow_rend_1", "Hollow Shriek", "frightened")]

    encounter = next(item for item in catalog if item["id"] == inventory[0][0])
    action = next(item for item in encounter["enemies"][0]["action_pool"] if item.get("applies_condition"))
    state = _make_combat_state()
    enemy = state.get_participant("goblin_scout_1")
    assert enemy is not None
    enemy.action_pool = [action]
    produced_name = _participant_roster(state.participants)[1]["actions"][0]
    mapped = to_engine_declarations(
        [AttackDecl(kind="attack", actor_id=enemy.id, action=produced_name, target_id="player_1", rider="")]
    )
    packet = ResolutionPacket(enemy.id, resolve_declaration(mapped[enemy.id]), enemy.initiative)

    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=1)):
        summary = await _resolve_one_packet(
            make_context().userdata,
            state,
            packet,
            mutations=MagicMock(update_player_hp=AsyncMock()),
            queries=MagicMock(get_player_inventory=AsyncMock(return_value=[])),
            resolver=_damage_resolver(0),
            concentration_break_mod=MagicMock(break_concentration_on_damage=AsyncMock(return_value=None)),
        )

    assert summary["condition_inflicted"] == "frightened"
    player = state.get_participant("player_1")
    assert player is not None
    assert any(condition["type"] == "frightened" for condition in player.conditions)


def test_attack_maps_to_the_engine_attack_shape():
    engine = to_engine_declarations(
        [AttackDecl(kind="attack", actor_id="player_1", action="Longsword", target_id="goblin_1", rider="")]
    )
    assert engine == {"player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_1"}}


def test_mapped_unknown_attack_action_fails_at_the_engine_boundary():
    state = _make_combat_state()
    engine = to_engine_declarations(
        [
            AttackDecl(
                kind="attack",
                actor_id="goblin_scout_1",
                action="Claw",
                target_id="player_1",
                rider="",
            )
        ]
    )

    with pytest.raises(ValueError) as raised:
        advance_combat_phase(state, engine)

    assert all(value in str(raised.value) for value in ("Goblin Scout", "goblin_scout_1", "Claw", "Scimitar"))


@pytest.mark.parametrize(
    "decl",
    [
        AttackDecl(kind="attack", actor_id="goblin_1", action="Scimitar", target_id="player_1", rider=""),
        DefendDecl(kind="defend", actor_id="goblin_1"),
    ],
)
def test_mapped_unknown_actor_fails_at_the_engine_boundary(decl):
    with pytest.raises(ValueError) as raised:
        advance_combat_phase(_make_combat_state(), to_engine_declarations([decl]))

    assert all(value in str(raised.value) for value in ("goblin_1", "player_1", "goblin_scout_1"))


def test_declare_time_action_check_matches_case_insensitively_like_resolution():
    engine = to_engine_declarations(
        [AttackDecl(kind="attack", actor_id="goblin_scout_1", action="sCiMiTaR", target_id="player_1", rider="")]
    )

    next_state, _ = advance_combat_phase(_make_combat_state(), engine)

    assert next_state.pending_declarations == engine


def test_an_attack_rider_rides_through_but_an_empty_one_is_dropped():
    """`rider` is required in the schema (ADR 0008 rule 2 — an optional costs back the
    union slot the sum type bought), so "" is how the DM says "no rider". The mapper
    drops it so the engine dict keeps the shape `resolve_declaration` has always
    received: a `rider` key present means the actor chose one."""
    with_rider = to_engine_declarations(
        [AttackDecl(kind="attack", actor_id="player_1", action="Dagger", target_id="goblin_1", rider="hide")]
    )
    assert with_rider["player_1"]["rider"] == "hide"
    without = to_engine_declarations(
        [AttackDecl(kind="attack", actor_id="player_1", action="Dagger", target_id="goblin_1", rider="")]
    )
    assert "rider" not in without["player_1"]


def test_one_ability_target_becomes_target_id():
    engine = to_engine_declarations(
        [AbilityDecl(kind="ability", actor_id="player_1", action="arcane_bolt", targets=["goblin_1"], argument_type="")]
    )
    assert engine == {"player_1": {"type": "ability", "action": "arcane_bolt", "target_id": "goblin_1"}}


def test_several_ability_targets_become_target_ids():
    """target_id XOR target_ids — spells.normalize_target_list refuses both, so the mapper
    must pick one rather than always setting the singular."""
    engine = to_engine_declarations(
        [
            AbilityDecl(
                kind="ability", actor_id="player_1", action="bless", targets=["ally_1", "ally_2"], argument_type=""
            )
        ]
    )
    assert engine["player_1"] == {"type": "ability", "action": "bless", "target_ids": ["ally_1", "ally_2"]}


def test_no_ability_target_is_a_self_cast():
    engine = to_engine_declarations(
        [AbilityDecl(kind="ability", actor_id="player_1", action="shield_self", targets=[], argument_type="")]
    )
    assert engine["player_1"] == {"type": "ability", "action": "shield_self"}


def test_de_escalate_carries_its_argument_type():
    engine = to_engine_declarations(
        [AbilityDecl(kind="ability", actor_id="player_1", action="de_escalate", targets=[], argument_type="reason")]
    )
    assert engine["player_1"] == {"type": "ability", "action": "de_escalate", "argument_type": "reason"}


def test_interact_maneuver_defend_and_retreat_map_to_their_engine_shapes():
    engine = to_engine_declarations(
        [
            InteractDecl(kind="interact", actor_id="player_1", action="lever"),
            ManeuverDecl(kind="maneuver", actor_id="companion_kael", target_id="goblin_1"),
            DefendDecl(kind="defend", actor_id="goblin_1"),
            RetreatDecl(kind="retreat", actor_id="goblin_2"),
        ]
    )
    assert engine == {
        "player_1": {"type": "interact", "action": "lever"},
        "companion_kael": {"type": "maneuver", "target_id": "goblin_1"},
        "goblin_1": {"type": "defend"},
        "goblin_2": {"type": "retreat"},
    }


def test_a_repeated_actor_fails_loud():
    """The old dict shape made a second declaration for one actor unrepresentable. A list
    does not — and a last-wins collapse would silently drop a combatant's whole round."""
    with pytest.raises(ValueError, match="declared more than once"):
        to_engine_declarations(
            [
                DefendDecl(kind="defend", actor_id="player_1"),
                AttackDecl(kind="attack", actor_id="player_1", action="Longsword", target_id="goblin_1", rider=""),
            ]
        )


def test_variant_kinds_match_the_engine_declaration_types():
    """The schema and the engine share one vocabulary — a dropped or renamed variant reds
    here rather than becoming an 'unknown declaration type' the DM meets mid-fight."""
    kinds = {typing.get_args(v.model_fields["kind"].annotation)[0] for v in DECL_VARIANTS}
    assert kinds == {t.value for t in DeclarationType}


_ENGINE_CASES = [
    AttackDecl(kind="attack", actor_id="a", action="Longsword", target_id="goblin_1", rider=""),
    AbilityDecl(kind="ability", actor_id="a", action="arcane_bolt", targets=["goblin_1"], argument_type=""),
    InteractDecl(kind="interact", actor_id="a", action="lever"),
    ManeuverDecl(kind="maneuver", actor_id="a", target_id="goblin_1"),
    DefendDecl(kind="defend", actor_id="a"),
    RetreatDecl(kind="retreat", actor_id="a"),
]


@pytest.mark.parametrize("payload", _ENGINE_CASES)
def test_a_fully_specified_variant_satisfies_the_engine_classifier(payload):
    raw = to_engine_declarations([payload])["a"]
    assert resolve_declaration(raw).type.value == raw["type"]


def test_every_variant_has_an_engine_case():
    """All six, with no exception carved out. REACTION was the seventh and was excluded here
    because its classifier reads the ability catalog; story-017 deleted it, so a variant that
    slips past the engine classifier can no longer hide behind that carve-out."""
    assert len(_ENGINE_CASES) == len(DECL_VARIANTS)


def test_declare_phase_offers_no_reaction_kind():
    """AC2, against the EMITTED schema rather than the class list — the DM obeys what the plugin
    compiles, not what this module declares. A reaction is an interrupt now (story-017): a
    `kind: "reaction"` the DM could still send would be a packet that never activates and burns
    the actor's whole phase action."""
    parsed = ToolContext([combat_turn.declare_phase]).parse_function_tools("anthropic", strict=True)
    schema = next(tool["input_schema"] for tool in parsed if tool["name"] == "declare_phase")

    kinds = _kind_consts(schema)
    assert kinds == {t.value for t in DeclarationType}
    assert "reaction" not in kinds
    assert "trigger" not in json.dumps(schema)


def _kind_consts(node) -> set[str]:
    """Every literal the emitted schema will accept for a declaration's `kind` discriminator."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "kind" and isinstance(value, dict):
                found |= set(value.get("enum") or ([value["const"]] if "const" in value else []))
            found |= _kind_consts(value)
    elif isinstance(node, list):
        for item in node:
            found |= _kind_consts(item)
    return found


@pytest.mark.parametrize("variant", DECL_VARIANTS)
def test_no_variant_field_is_optional(variant):
    """ADR 0008 rule 2: an optional inside a variant is one union slot back, and the
    walker in test_strict_tool_budget cannot see WHY the number moved."""
    assert all(f.is_required() for f in variant.model_fields.values()), variant.__name__
