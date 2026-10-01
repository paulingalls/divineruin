"""Fail-loud unit coverage for the enemy applies_condition load-boundary guard (sprint-030
story-001). Encounter templates have no strict loader today (unlike spells.json /
archetype_abilities.json), so this guard is the only thing standing between a typo'd
applies_condition and a silent no-op at combat start. Pure — calls the validator directly
against an in-memory enemies list, no DB.
"""

import json
from pathlib import Path

import pytest

from combat_init import validate_enemy_action_shapes, validate_enemy_resistance_tags

FIXTURE_PATH = Path(__file__).resolve().parents[4] / "packages" / "shared" / "fixtures" / "enemy_action_shapes.json"
ACTION_SHAPES = json.loads(FIXTURE_PATH.read_text())


class TestValidateEnemyActionConditions:
    def test_unknown_condition_raises(self):
        enemies = [
            {
                "id": "bad_enemy",
                "action_pool": [
                    {"name": "Bad Howl", "applies_condition": "not_a_condition"},
                ],
            }
        ]
        with pytest.raises(ValueError, match="not_a_condition"):
            validate_enemy_action_shapes(enemies)

    def test_known_hostile_condition_with_save_and_dc_does_not_raise(self):
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [
                    {"name": "Hollow Shriek", "applies_condition": "frightened", "save": "wisdom", "dc": 12},
                ],
            }
        ]
        validate_enemy_action_shapes(enemies)  # no raise

    def test_missing_save_raises_at_load(self):
        # The resolver hard-reads action["save"]; a missing save must fail loud HERE (combat start),
        # not as a mid-fight KeyError deep in the phase loop.
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [{"name": "Hollow Shriek", "applies_condition": "frightened", "dc": 12}],
            }
        ]
        with pytest.raises(ValueError, match="save"):
            validate_enemy_action_shapes(enemies)

    def test_missing_or_nonint_dc_raises_at_load(self):
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [{"name": "Hollow Shriek", "applies_condition": "frightened", "save": "wisdom"}],
            }
        ]
        with pytest.raises(ValueError, match="dc"):
            validate_enemy_action_shapes(enemies)

    def test_invalid_save_attribute_raises_at_load(self):
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [{"name": "Hollow Shriek", "applies_condition": "frightened", "save": "luck", "dc": 12}],
            }
        ]
        with pytest.raises(ValueError, match="save"):
            validate_enemy_action_shapes(enemies)

    def test_abbreviated_save_key_is_accepted(self):
        # The resolver expands "wis" -> "wisdom" (roll_participant_save), so the load-gate must
        # accept the same abbreviated form — else content the engine could run fails loud at start.
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [{"name": "Hollow Shriek", "applies_condition": "frightened", "save": "wis", "dc": 12}],
            }
        ]
        validate_enemy_action_shapes(enemies)  # no raise

    @pytest.mark.parametrize("fixture_name", ["valid_combined_bite", "valid_half_on_success", "corruption_wave"])
    def test_supported_damage_and_save_shapes_are_accepted(self, fixture_name):
        enemies = [{"id": "fixture_enemy", "action_pool": [ACTION_SHAPES[fixture_name]]}]
        validate_enemy_action_shapes(enemies)

    def test_half_on_success_without_save_is_refused(self):
        enemies = [{"id": "fixture_enemy", "action_pool": [ACTION_SHAPES["invalid_half_without_save"]]}]
        with pytest.raises(ValueError, match="save"):
            validate_enemy_action_shapes(enemies)

    def test_half_on_success_without_damage_is_refused(self):
        # half_on_success halves action["damage"]; a "0"-damage row would resolve as a save that
        # deals nothing, so the load gate refuses it. The row carries a valid save/dc, so only the
        # damage check can raise here.
        enemies = [{"id": "fixture_enemy", "action_pool": [ACTION_SHAPES["invalid_half_without_damage"]]}]
        with pytest.raises(ValueError, match="non-zero"):
            validate_enemy_action_shapes(enemies)

    def test_zero_damage_condition_action_does_not_raise(self):
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [
                    {
                        "name": "Hollow Shriek",
                        "applies_condition": "frightened",
                        "save": "wisdom",
                        "dc": 12,
                        "damage": "0",
                    }
                ],
            }
        ]
        validate_enemy_action_shapes(enemies)  # no raise

    def test_action_with_no_applies_condition_does_not_raise(self):
        enemies = [
            {
                "id": "bandit_1",
                "action_pool": [
                    {"name": "Short Sword", "damage": "1d6+2"},
                ],
            }
        ]
        validate_enemy_action_shapes(enemies)  # no raise


class TestValidateEnemyResistanceTags:
    """M15 story-002: enemy resistance_tags are Tier-3 de-escalation content with no strict loader,
    so this load-boundary guard fails loud on a tag outside social_resolution.RESISTANCE_TAGS
    (mirroring npcs.py) — an unknown tag would otherwise silently no-op the argument DC swing."""

    def test_known_tags_do_not_raise(self):
        enemies = [{"id": "mawling_1", "resistance_tags": ["pragmatic", "suspicious"]}]
        validate_enemy_resistance_tags(enemies)  # no raise

    def test_missing_field_does_not_raise(self):
        # resistance_tags is optional — an enemy without it is un-de-escalatable, not an error.
        validate_enemy_resistance_tags([{"id": "goblin", "action_pool": []}])  # no raise

    def test_unknown_tag_raises(self):
        enemies = [{"id": "mawling_1", "resistance_tags": ["pragmatic", "grumpy"]}]
        with pytest.raises(ValueError, match="grumpy"):
            validate_enemy_resistance_tags(enemies)

    def test_non_list_tags_raises(self):
        enemies = [{"id": "mawling_1", "resistance_tags": "pragmatic"}]
        with pytest.raises(ValueError, match="resistance_tags"):
            validate_enemy_resistance_tags(enemies)


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", [None, "dc", "resistance_tags"])
async def test_combat_entry_calls_public_shape_and_resistance_guards(monkeypatch, defect):
    import copy
    from unittest.mock import Mock

    from livekit.agents.llm import ToolError
    from sample_fixtures import make_context

    import combat_init
    import combat_init_validation
    import creature_schema
    from tests.combat.test_start_combat import SAMPLE_ENCOUNTER, _make_start_combat_mocks

    assert creature_schema.validate_enemy_action_shapes is combat_init_validation.validate_enemy_action_shapes
    assert creature_schema.validate_enemy_resistance_tags is combat_init_validation.validate_enemy_resistance_tags
    shapes = Mock(wraps=combat_init_validation.validate_enemy_action_shapes)
    resistance = Mock(wraps=combat_init_validation.validate_enemy_resistance_tags)
    monkeypatch.setattr(combat_init, "validate_enemy_action_shapes", shapes)
    monkeypatch.setattr(combat_init, "validate_enemy_resistance_tags", resistance)
    mutations, queries, content = _make_start_combat_mocks()
    encounter = copy.deepcopy(SAMPLE_ENCOUNTER)
    enemy = encounter["enemies"][0]
    enemy["action_pool"][0].update(applies_condition="blinded", save="dexterity", dc=12)
    enemy["resistance_tags"] = ["pragmatic"]
    if defect == "dc":
        enemy["action_pool"][0]["dc"] = "12"
    elif defect == "resistance_tags":
        enemy["resistance_tags"] = ["unknown"]
    content.get_encounter_template.return_value = encounter
    if defect:
        with pytest.raises(ToolError, match=defect):
            await combat_init._start_combat_impl(
                make_context(), "fixture", "Fixture", mutations=mutations, queries=queries, content=content
            )
        mutations.save_combat_state.assert_not_called()
    else:
        await combat_init._start_combat_impl(
            make_context(), "fixture", "Fixture", mutations=mutations, queries=queries, content=content
        )
        resistance.assert_called_once_with(encounter["enemies"])
        mutations.save_combat_state.assert_called_once()
    shapes.assert_called_once_with(encounter["enemies"])


CONTRACT_CORPUS = json.loads((FIXTURE_PATH.parent / "creature_blocks.json").read_text())


@pytest.mark.parametrize(
    "case",
    [r for r in CONTRACT_CORPUS["valid"] if r["name"].startswith(("recharge_", "advantage_", "active_"))],
    ids=lambda r: r["name"],
)
def test_structured_recharge_action_advantage_active_contract(case):
    from encounter_actions import validate_encounter_actions

    block = case["block"]
    actions = block["actives"] or block["attacks"]
    enemy = {"id": "fixture", "action_pool": actions}
    validate_enemy_action_shapes([enemy])
    validate_encounter_actions([enemy])


@pytest.mark.parametrize(
    "case",
    [
        r
        for r in CONTRACT_CORPUS["invalid"]
        if r["name"].startswith(("recharge_", "advantage_", "active_healing_", "active_prepare_attack_", "mark_"))
        or (r["name"].startswith("active_attack_") and "_type_" in r["name"])
    ],
    ids=lambda r: r["name"],
)
def test_structured_recharge_action_advantage_active_contract_rejection(case):
    from encounter_actions import validate_encounter_actions

    block = case["block"]
    actions = block["actives"] or block["attacks"]
    enemy = {"id": "fixture", "action_pool": actions}
    field = case.get("field", "")
    with pytest.raises(ValueError, match=field):
        validate_enemy_action_shapes([enemy])
        validate_encounter_actions([enemy])


@pytest.mark.parametrize("expression", ["1d8", "2d6+0", "3d4+2"])
def test_active_contract_healing_uses_real_dice(expression):
    import random

    import dice
    from encounter_actions import validate_encounter_actions

    validate_encounter_actions(
        [
            {
                "id": "captain",
                "action_pool": [
                    {"kind": "healing", "target_group": "allied_bandits", "healing": expression},
                ],
            }
        ]
    )
    assert dice.roll(expression, rng=random.Random(0)).total > 0
