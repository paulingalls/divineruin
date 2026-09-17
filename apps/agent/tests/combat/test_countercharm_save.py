"""Countercharm changes a matching hostile save, and only that save."""

import json
import random
from pathlib import Path
from unittest.mock import patch

import pytest
from combat._helpers import _activate, _ctx_at_resolution, _resolve_deps
from combat._reaction_helpers import _drain, _guarded_ally_state, _pause_at, _reaction_packet

import reaction_windows
from check_resolution_save import resolve_saving_throw
from combat_prompts import COMBAT_PROMPT
from conditions import apply_condition
from dice import roll as roll_dice

_CONTENT = Path(__file__).resolve().parents[4] / "content"
_ENCOUNTERS = json.loads((_CONTENT / "encounter_templates.json").read_text())
_REACTIONS = [
    row
    for row in json.loads((_CONTENT / "archetype_abilities.json").read_text())
    if row.get("ability_type") == "reaction"
]
_COUNTERCHARM = "bard_countercharm"


def _action(enemy_id: str, name: str) -> dict:
    return next(
        dict(action)
        for encounter in _ENCOUNTERS
        for enemy in encounter["enemies"]
        if enemy["id"] == enemy_id
        for action in enemy["action_pool"]
        if action["name"] == name
    )


def _condition_state(enemy_id: str, name: str):
    state = _guarded_ally_state()
    enemy = state.get_participant("goblin_scout_1")
    assert enemy is not None
    enemy.action_pool = [_action(enemy_id, name)]
    state.pending_declarations[enemy.id]["action"] = name
    return state


def _seeded_dice(seed: int):
    seeded_rng = random.Random(seed)

    def roll(notation: str, rng=None):
        return roll_dice(notation, rng=rng or seeded_rng)

    return roll


async def _resolve_condition(*, answer: bool, enemy_id="hollow_rend_1", name="Hollow Shriek", target_conditions=()):
    state = _condition_state(enemy_id, name)
    target = state.get_participant("player_2")
    assert target is not None
    target.conditions = [dict(condition) for condition in target_conditions]
    ctx = _ctx_at_resolution(state=state)
    deps = _resolve_deps()
    packets: list[dict] = []
    with patch("check_resolution.dice_roll", side_effect=_seeded_dice(1)):
        await _pause_at(
            ctx,
            deps,
            actor_id="goblin_scout_1",
            stage=reaction_windows.PRE_ROLL,
            packets=packets,
        )
        if answer:
            await _activate(ctx, _COUNTERCHARM, player_class="bard")
        await _drain(ctx, deps, packets)
    return ctx, packets


@pytest.mark.asyncio
async def test_countercharm_turns_the_failing_hollow_shriek_save_into_a_success():
    ctx, packets = await _resolve_condition(answer=True)

    summary = next(packet for packet in packets if packet.get("condition_resisted") == "frightened")
    assert summary["save_advantage"] is True
    assert _reaction_packet(packets)["mechanical_effect"] == "save_advantage"
    target = ctx.userdata.combat_state.get_participant("player_2")
    assert target is not None and target.conditions == []


@pytest.mark.asyncio
async def test_countercharm_cancelled_by_hollowed_wis_disadvantage_claims_no_advantage():
    hollowed = {"type": "hollowed", "duration": 10, "source": "test", "stacks": 1, "stage": 1}
    _, packets = await _resolve_condition(answer=True, target_conditions=[hollowed])

    summary = next(packet for packet in packets if packet.get("condition_inflicted") == "frightened")
    assert "save_advantage" not in summary
    assert _reaction_packet(packets)["mechanical_effect"] is None


def test_granted_advantage_is_not_applied_to_a_save_that_auto_fails():
    stunned = {"attributes": {"dexterity": 10}, "conditions": apply_condition([], "stunned", source="test")}
    result = resolve_saving_throw(stunned, "dexterity", 10, "prone", advantage=True)

    assert result.success is False and result.advantage_applied is False


@pytest.mark.asyncio
async def test_the_same_first_die_unanswered_inflicts_frightened():
    _, packets = await _resolve_condition(answer=False)

    assert any(packet.get("condition_inflicted") == "frightened" for packet in packets)


@pytest.mark.asyncio
async def test_countercharm_spent_against_a_command_claims_no_effect():
    ctx = _ctx_at_resolution(state=_condition_state("ashmark_sergeant", "Rally"))
    deps = _resolve_deps()
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.PRE_ROLL, packets=packets)
    await _activate(ctx, _COUNTERCHARM, player_class="bard")
    await _drain(ctx, deps, packets)

    assert _reaction_packet(packets)["mechanical_effect"] is None


@pytest.mark.asyncio
async def test_countercharm_spent_against_hold_person_claims_no_effect():
    _, packets = await _resolve_condition(answer=True, enemy_id="cult_leader", name="Hold Person")
    assert _reaction_packet(packets)["mechanical_effect"] is None


def test_condition_action_inventory_stays_explicit():
    # The window census and its totals stay pinned by test_reaction_window_census.py.
    condition_actions = sorted(
        (enemy["id"], action["name"], action.get("applies_condition"))
        for encounter in _ENCOUNTERS
        for enemy in encounter["enemies"]
        for action in enemy["action_pool"]
        if action.get("applies_condition")
    )
    assert condition_actions == [
        ("ashmark_soldier_1", "Shield Bash", "prone"),
        ("ashmark_soldier_2", "Shield Bash", "prone"),
        ("ashmark_soldier_3", "Shield Bash", "prone"),
        ("ashmark_soldier_4", "Shield Bash", "prone"),
        ("cult_leader", "Hold Person", "paralyzed"),
        ("hollow_rend_1", "Hollow Shriek", "frightened"),
    ]
    assert {row["id"] for row in _REACTIONS if row["window"] == "on_condition_imposed"} == {
        "rogue_slippery",
        "spy_slippery",
    }


def test_combat_prompt_names_the_save_advantage_effect():
    assert '"save_advantage"' in COMBAT_PROMPT
