"""Enemy commands mark a focus target for the commander's band."""

import json
from copy import deepcopy
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _ac_sensitive_resolver, _ctx_at_resolution, _resolve_deps, _resolve_round
from sample_fixtures import make_context

from combat_init import _start_combat_impl
from combat_marks import attack_bonus, resolve_mark_action
from combat_prompts import COMBAT_PROMPT
from session_data import CombatParticipant, CombatState
from tests.combat.test_start_combat import _THORNWATCH, SAMPLE_PLAYER

_CONTENT = Path(__file__).resolve().parents[4] / "content"
_ENCOUNTERS = json.loads((_CONTENT / "encounter_templates.json").read_text())
_STRIKE = {"name": "Mace", "damage": "1", "damage_type": "bludgeoning", "properties": []}


def _action(enemy_id: str, name: str) -> dict:
    return next(
        dict(action)
        for encounter in _ENCOUNTERS
        for enemy in encounter["enemies"]
        if enemy["id"] == enemy_id
        for action in enemy["action_pool"]
        if action["name"] == name
    )


def _participant(pid: str, *, kind="enemy", initiative=10, actions=None, ac=13):
    return CombatParticipant(
        id=pid,
        name=pid.replace("_", " ").title(),
        type=kind,
        initiative=initiative,
        hp_current=30,
        hp_max=30,
        ac=ac,
        action_pool=actions or [],
        has_reaction_ability=False,
    )


def _mark_state(commands: list[tuple[str, dict]], *, attack_target="player_1") -> CombatState:
    players = [
        _participant("player_1", kind="player", initiative=20, ac=14),
        _participant("player_2", kind="player", initiative=19, ac=14),
    ]
    markers = [
        _participant(marker_id, initiative=16 - index, actions=[action])
        for index, (marker_id, action) in enumerate(commands)
    ]
    striker = _participant("bandmate", initiative=10, actions=[_STRIKE])
    declarations = {
        marker.id: {"type": "attack", "action": marker.action_pool[0]["name"], "target_id": "player_1"}
        for marker in markers
    }
    declarations[striker.id] = {"type": "attack", "action": "Mace", "target_id": attack_target}
    participants = [*players, *markers, striker]
    return CombatState(
        combat_id="combat_mark",
        participants=participants,
        initiative_order=[participant.id for participant in participants],
        beat="resolution",
        pending_declarations=declarations,
    )


async def _run(state: CombatState):
    ctx = _ctx_at_resolution(state=state)
    deps = {**_resolve_deps(), "resolver": _ac_sensitive_resolver(attack_total=13, damage=1)}
    payload = await _resolve_round(ctx, **deps)
    assert not isinstance(payload, tuple)
    strike = next(packet for packet in payload["packets"] if packet["actor_id"] == "bandmate")
    return ctx, deps, strike


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enemy_id", "name"),
    [("ashmark_sergeant", "Rally"), ("cult_fanatic_1", "Bless")],
)
async def test_a_command_makes_a_later_bandmate_hit_the_marked_target(enemy_id, name):
    marked = _mark_state([("marker", _action(enemy_id, name))])
    _, _, marked_strike = await _run(marked)
    _, _, unmarked_strike = await _run(_mark_state([]))

    assert (marked_strike["hit"], marked_strike["attack_total"]) == (True, 15)
    assert (unmarked_strike["hit"], unmarked_strike["attack_total"]) == (False, 13)


@pytest.mark.asyncio
async def test_two_bless_commands_on_one_target_still_add_only_two():
    commands = [
        ("fanatic_1", _action("cult_fanatic_1", "Bless")),
        ("fanatic_2", _action("cult_fanatic_2", "Bless")),
    ]
    _, _, strike = await _run(_mark_state(commands))
    assert (strike["hit"], strike["attack_total"]) == (True, 15)


@pytest.mark.parametrize("second_kind", ["command", "accusation"])
def test_the_first_same_band_marker_owns_the_target(second_kind):
    state = _mark_state([])
    first = _participant("first_marker")
    second = _participant("second_marker")
    state.participants.extend([first, second])
    target = state.get_participant("player_1")
    assert target is not None

    resolve_mark_action(state, first, target, "command")
    resolve_mark_action(state, second, target, second_kind)

    assert (attack_bonus(state, first, target), attack_bonus(state, second, target)) == (0, 2)
    assert state.focus_marks[target.id] == {"source_id": first.id, "kind": "command"}


@pytest.mark.parametrize(
    ("first_type", "second_type"),
    [("enemy", "companion"), ("companion", "enemy")],
)
def test_an_opposing_band_cannot_replace_a_mark(first_type, second_type):
    state = _mark_state([])
    first = _participant("first_marker", kind=first_type)
    second = _participant("second_marker", kind=second_type)
    state.participants.extend([first, second])
    target = state.get_participant("player_1")
    assert target is not None
    resolve_mark_action(state, first, target, "command")

    with pytest.raises(ValueError) as error:
        resolve_mark_action(state, second, target, "accusation")

    assert first.id in str(error.value)
    assert second.id in str(error.value)
    assert state.focus_marks[target.id] == {"source_id": first.id, "kind": "command"}


def test_a_cancelled_mark_does_not_inspect_or_replace_the_owner():
    state = _mark_state([])
    first = _participant("first_marker")
    second = _participant("second_marker", kind="companion")
    state.participants.extend([first, second])
    target = state.get_participant("player_1")
    assert target is not None
    resolve_mark_action(state, first, target, "command")

    resolve_mark_action(state, second, target, "accusation", cancelled=True)
    assert state.focus_marks[target.id] == {"source_id": first.id, "kind": "command"}
    with pytest.raises(ValueError, match="does not create"):
        resolve_mark_action(state, second, target, "attack", cancelled=True)


@pytest.mark.asyncio
async def test_a_mark_does_not_help_an_attack_against_another_target():
    _, _, strike = await _run(_mark_state([("marker", _action("ashmark_sergeant", "Rally"))], attack_target="player_2"))
    assert (strike["hit"], strike["attack_total"]) == (False, 13)


def test_a_mark_does_not_help_the_marker_or_the_opposite_band_or_a_fallen_attacker():
    state = _mark_state([])
    marker = _participant("marker", actions=[_STRIKE])
    state.participants.append(marker)
    target = state.get_participant("player_1")
    bandmate = state.get_participant("bandmate")
    opposite = state.get_participant("player_2")
    assert target is not None and bandmate is not None and opposite is not None
    resolve_mark_action(state, marker, target, "command")

    assert attack_bonus(state, marker, target) == 0
    assert attack_bonus(state, opposite, target) == 0
    bandmate.is_fallen = True
    assert attack_bonus(state, bandmate, target) == 0
    bandmate.is_fallen = False
    bandmate.is_dead = True
    assert attack_bonus(state, bandmate, target) == 0


def test_corrupt_marks_and_non_mark_kinds_fail_loud():
    state = _mark_state([])
    marker = _participant("marker")
    state.participants.append(marker)
    target = state.get_participant("player_1")
    bandmate = state.get_participant("bandmate")
    assert target is not None and bandmate is not None

    with pytest.raises(ValueError, match="does not create"):
        resolve_mark_action(state, marker, target, "attack")
    state.focus_marks[target.id] = cast(dict[str, str], [])
    with pytest.raises(ValueError, match="malformed"):
        attack_bonus(state, bandmate, target)
    state.focus_marks[target.id] = cast(dict[str, str], ["source_id", "kind"])
    with pytest.raises(ValueError, match="malformed"):
        attack_bonus(state, bandmate, target)
    state.focus_marks[target.id] = {"source_id": marker.id, "kind": "command", "extra": "field"}
    with pytest.raises(ValueError, match="malformed"):
        attack_bonus(state, bandmate, target)
    state.focus_marks[target.id] = cast(dict[str, str], {"source_id": 7, "kind": "command"})
    with pytest.raises(ValueError, match="malformed"):
        attack_bonus(state, bandmate, target)
    state.focus_marks[target.id] = {"source_id": "missing", "kind": "command"}
    with pytest.raises(ValueError, match="missing source"):
        attack_bonus(state, bandmate, target)
    state.focus_marks[target.id] = {"source_id": marker.id, "kind": "attack"}
    with pytest.raises(ValueError, match="malformed"):
        attack_bonus(state, bandmate, target)


@pytest.mark.asyncio
async def test_the_mark_clears_at_wrap_and_does_not_help_next_round():
    ctx, deps, first = await _run(_mark_state([("marker", _action("ashmark_sergeant", "Rally"))]))
    assert first["hit"] is True
    assert ctx.userdata.combat_state.focus_marks == {}

    state = ctx.userdata.combat_state
    state.beat = "resolution"
    state.pending_declarations = {"bandmate": {"type": "attack", "action": "Mace", "target_id": "player_1"}}
    second = await _resolve_round(ctx, **deps)
    assert not isinstance(second, tuple)
    strike = next(packet for packet in second["packets"] if packet["actor_id"] == "bandmate")
    assert (strike["hit"], strike["attack_total"]) == (False, 13)


def test_focus_marks_round_trip_and_legacy_rows_default_empty():
    state = _mark_state([])
    state.focus_marks = {"player_1": {"source_id": "marker", "kind": "command"}}

    assert CombatState.from_dict(state.to_dict()).focus_marks == state.focus_marks
    legacy = state.to_dict()
    del legacy["focus_marks"]
    assert CombatState.from_dict(legacy).focus_marks == {}


def _encounter(encounter_id: str) -> dict:
    return deepcopy(next(encounter for encounter in _ENCOUNTERS if encounter["id"] == encounter_id))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("encounter_id", "expected"),
    [
        ("bandit_ambush", {"bandit_captain": [{"name": "Press the Attack", "kind": "command"}]}),
        (
            "ashmark_patrol",
            {
                "ashmark_sergeant": [
                    {"name": "Rally", "kind": "command"},
                    {"name": "Accusation", "kind": "accusation"},
                ]
            },
        ),
        (
            "cult_cell",
            {
                "cult_fanatic_1": [{"name": "Bless", "kind": "command"}],
                "cult_fanatic_2": [{"name": "Bless", "kind": "command"}],
            },
        ),
        (
            "hollow_corrupted_settlement",
            {"hollowed_knight": [{"name": "Command Lesser", "kind": "command"}]},
        ),
    ],
)
async def test_start_combat_hands_each_command_to_the_dm_as_a_mark_action(
    mock_combat_agent_factory, encounter_id, expected
):
    encounter = _encounter(encounter_id)
    mutations = MagicMock(save_combat_state=AsyncMock())
    queries = MagicMock(
        get_player=AsyncMock(return_value=deepcopy(SAMPLE_PLAYER)),
        get_player_faction_reputation=AsyncMock(return_value=0),
    )
    content = MagicMock(
        get_encounter_template=AsyncMock(return_value=encounter),
        get_faction=AsyncMock(return_value=_THORNWATCH),
    )

    raw = await _start_combat_impl(
        make_context(), encounter_id, encounter["description"], mutations=mutations, queries=queries, content=content
    )
    assert isinstance(raw, tuple)
    roster = {participant["id"]: participant for participant in json.loads(raw[1])["participants"]}

    for enemy in encounter["enemies"]:
        assert roster[enemy["id"]]["actions"] == [action["name"] for action in enemy["action_pool"]]
        assert roster[enemy["id"]]["mark_actions"] == expected.get(enemy["id"], [])
    assert roster["player_1"]["mark_actions"] == []


def test_combat_prompt_explains_command_mark_targets():
    assert "Combatants[].mark_actions" in COMBAT_PROMPT
    assert "kind `command`" in COMBAT_PROMPT
    assert "target_id" in COMBAT_PROMPT and "focus" in COMBAT_PROMPT
