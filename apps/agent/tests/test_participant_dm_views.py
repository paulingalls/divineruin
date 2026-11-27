import json
from copy import deepcopy
from dataclasses import asdict, fields, replace
from pathlib import Path

import pytest

import combat_support
from combat_participant import CombatParticipant
from conditions import apply_condition
from creature_combat import translate_creature
from wild_shape import WildShapeState


def _projected_field_cases() -> dict[str, tuple[CombatParticipant, object]]:
    catalog_path = Path(__file__).resolve().parents[3] / "content/creatures.json"
    catalog = {row["id"]: row for row in json.loads(catalog_path.read_text())}
    wolf = translate_creature(catalog["grey_wolf"], encounter_id="fight", enemy_id="wolf", role="standard")
    choir_enemy = translate_creature(catalog["hollow_choir"], encounter_id="fight", enemy_id="choir", role="boss")
    bite = wolf["action_pool"][0]
    hero = CombatParticipant(id="p1", name="Hero", type="player", initiative=10, hp_current=10, hp_max=20, ac=12)
    fallen = replace(hero, is_fallen=True, hp_current=0)
    armed = replace(hero, action_pool=[bite])
    choir = replace(hero, type="enemy", creature_id="hollow_choir", action_pool=choir_enemy["action_pool"])
    charged = replace(
        hero,
        action_pool=[bite | {"recharge": {"kind": "encounter", "uses": 1}}],
        action_ledger={"bite": {"remaining": 1, "round": 1}},
    )
    wolf_form = WildShapeState(
        form_id="grey_wolf",
        name=wolf["name"],
        hp_current=1,
        hp_max=wolf["hp"],
        original_ac=hero.ac,
        original_action_pool=hero.action_pool,
        original_deferred_effects=hero.deferred_effects,
    )
    return {
        "id": (hero, "p2"),
        "name": (hero, "Ally"),
        "type": (hero, "companion"),
        "initiative": (hero, 11),
        "ac": (hero, 13),
        "yielded": (hero, True),
        "is_fallen": (hero, True),
        "hp_current": (hero, 1),
        "hp_max": (hero, 40),
        "conditions": (hero, apply_condition([], "stunned", duration=1, source="Stunning Blow")),
        "creature_id": (hero, "grey_wolf"),
        "catalog_narration": (hero, wolf["catalog_narration"]),
        "catalog_audio": (hero, wolf["catalog_audio"]),
        "deferred_effects": (hero, wolf["deferred_effects"]),
        "action_pool": (hero, [bite]),
        "multiattack_sequence": (armed, {"name": "Double Bite", "attacks": ["Bite", "Bite"]}),
        "choir_reaction": (choir, choir_enemy["choir_reaction"]),
        "is_dead": (fallen, True),
        "death_save_failures": (fallen, 3),
        "temp_hp": (hero, 5),
        "choir_suppression": (choir, {"active": True, "expires_round": 3}),
        "choir_silence_exposed": (choir, True),
        "still_dormant": (armed, True),
        "wild_shape": (hero, wolf_form),
        "action_ledger": (charged, {"bite": {"remaining": 0, "round": 1}}),
    }


PROJECTED_CASES = _projected_field_cases()


def test_participant_fields_have_one_dm_view_classification() -> None:
    actual = {field.name for field in fields(CombatParticipant)}
    projected = combat_support.PARTICIPANT_SUMMARY_PROJECTED_FIELDS
    internal = combat_support.PARTICIPANT_SUMMARY_INTERNAL_FIELDS

    unclassified = actual - projected - internal.keys()
    overlap = projected & internal.keys()
    unknown = (projected | internal.keys()) - actual
    unexplained = {name for name, reason in internal.items() if not isinstance(reason, str) or not reason.strip()}
    missing_cases = projected - PROJECTED_CASES.keys()
    extra_cases = PROJECTED_CASES.keys() - projected

    assert not unclassified, f"Unclassified participant fields: {sorted(unclassified)}"
    assert not overlap, f"Participant fields classified twice: {sorted(overlap)}"
    assert not unknown, f"Unknown participant fields in declarations: {sorted(unknown)}"
    assert not unexplained, f"Internal participant fields without reasons: {sorted(unexplained)}"
    assert not missing_cases, f"Projected participant fields without cases: {sorted(missing_cases)}"
    assert not extra_cases, f"Cases for undeclared projections: {sorted(extra_cases)}"


@pytest.mark.parametrize("field_name", PROJECTED_CASES)
def test_projected_field_changes_participant_summary(field_name: str) -> None:
    base, value = PROJECTED_CASES[field_name]
    before = deepcopy(base)
    after = deepcopy(before)
    setattr(after, field_name, deepcopy(value))

    before_fields = asdict(before)
    after_fields = asdict(after)
    changed = {name for name in before_fields if before_fields[name] != after_fields[name]}
    assert changed == {field_name}

    before_summary = deepcopy(combat_support._participant_summary(before))
    after_summary = deepcopy(combat_support._participant_summary(after))
    assert before_summary != after_summary, f"{field_name} did not change the DM roster summary"

    if field_name in {"is_dead", "death_save_failures"}:
        assert "is_dead" not in before_summary
        assert after_summary["is_dead"] is True
    if field_name == "temp_hp":
        assert "temp_hp" not in before_summary
        assert after_summary["temp_hp"] == value
