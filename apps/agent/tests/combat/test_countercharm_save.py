"""Countercharm changes a matching hostile save, and only that save."""

import json
import random
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest
from combat._helpers import _activate, _ctx_at_resolution, _resolve_deps
from combat._reaction_helpers import _drain, _guarded_ally_state, _pause_at, _reaction_packet

import reaction_windows
from combat_prompts import COMBAT_PROMPT
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


async def _resolve_condition(*, answer: bool, enemy_id="hollow_rend_1", name="Hollow Shriek"):
    ctx = _ctx_at_resolution(state=_condition_state(enemy_id, name))
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


_CLASSIFICATION = {
    "bard_dissonant_whisper": "reachable",
    "mage_shield_spell": "reachable",
    "skirmisher_sidestep": "reachable",
    "whisper_thought_shield": "reachable",
    "bard_countercharm": "reachable",
    "cleric_shield_of_faith": "reachable",
    "diplomat_countercharm": "reachable",
    "marshal_interceding_order": "reachable",
    "oracle_shield_of_faith": "reachable",
    "paladin_shield_of_faith": "reachable",
    "druid_bark_skin": "reachable",
    "guardian_retaliating_shield": "reachable",
    "rogue_uncanny_dodge": "reachable",
    "warden_bark_skin": "reachable",
    "warrior_brace_for_impact": "reachable",
    "guardian_intercept": "reachable",
    "skirmisher_riposte": "reachable",
    "whisper_implant_doubt": "reachable",
    "diplomat_objection": "inapplicable",
    "spy_plausible_deniability": "inapplicable",
    "marshal_countermand": "inapplicable",
    "rogue_slippery": "reachable",
    "spy_slippery": "reachable",
    "warrior_opportunity_strike": "unproducible",
    "mage_counterspell": "unproducible",
}
_WINDOW_CENSUS = {
    "on_ally_targeted": 6,
    "on_hit": 5,
    "on_targeted": 4,
    "on_enemy_action": 4,
    "on_condition_imposed": 2,
    "on_ally_hit": 1,
    "on_enemy_miss": 1,
    "on_enemy_move": 1,
    "on_spell_cast": 1,
}


def test_condition_and_reaction_inventory_is_unchanged():
    condition_actions = sorted(
        (enemy["id"], action["name"], action.get("applies_condition"))
        for encounter in _ENCOUNTERS
        for enemy in encounter["enemies"]
        for action in enemy["action_pool"]
        if action.get("applies_condition")
    )
    grapple_carriers = sorted(
        (enemy["id"], action["name"])
        for encounter in _ENCOUNTERS
        for enemy in encounter["enemies"]
        for action in enemy["action_pool"]
        if "grapple" in action.get("properties", [])
    )

    assert condition_actions == [
        ("cult_leader", "Hold Person", "paralyzed"),
        ("hollow_rend_1", "Hollow Shriek", "frightened"),
    ]
    assert Counter(row["window"] for row in _REACTIONS) == _WINDOW_CENSUS
    assert {row["id"] for row in _REACTIONS if row["window"] == "on_condition_imposed"} == {
        "rogue_slippery",
        "spy_slippery",
    }
    assert grapple_carriers == [("mawling_1", "Seizing Grab"), ("mawling_2", "Seizing Grab")]
    assert set(_CLASSIFICATION) == {row["id"] for row in _REACTIONS}
    assert Counter(_CLASSIFICATION.values()) == {"reachable": 20, "inapplicable": 3, "unproducible": 2}
    produced = {
        trigger
        for encounter in _ENCOUNTERS
        for enemy in encounter["enemies"]
        for action in enemy["action_pool"]
        for trigger in (
            *reaction_windows.pre_roll_triggers(action),
            *reaction_windows.post_roll_triggers(action, hit=True),
            *reaction_windows.post_roll_triggers(action, hit=False),
        )
    }
    by_id = {row["id"]: row for row in _REACTIONS}
    for ability_id, classification in _CLASSIFICATION.items():
        if classification == "unproducible":
            assert by_id[ability_id]["window"] not in produced
        else:
            assert by_id[ability_id]["window"] in produced


def test_combat_prompt_names_the_save_advantage_effect():
    assert '"save_advantage"' in COMBAT_PROMPT
