"""M4.8 story-005: Inspire ability producer + ability-targeting infra.

Mirrors story-004's Bless SPELL producer, but Inspire (bard_inspire/diplomat_inspire) is an
ABILITY, not a spell — and abilities had no target or condition-apply path. This story adds:

- A) catalog schema: Ability.applies_condition, parsed + fail-loud validated against the
     condition catalog (mirror spells.py).
- B) out-of-combat producer: request_ability_activation gains target_id and applies+persists
     the ability's condition to the target's players.data SSOT (caster/player target), or
     narrates-only for a non-player target.
- C) in-combat producer: a NEW non-spell ability-condition path (mirroring de_escalate) applies
     the condition to the target CombatParticipant on the working state.

The producer contract is the one recorded in story-004 (decision applies-condition-producer-contract):
condition_applied surfaces only when the condition actually landed (conditions.has_condition).
"""

import pytest

from abilities import parse_ability_row

# A bard_inspire-shaped catalog row carrying the new structured producer field.
_INSPIRE_ROW = {
    "id": "bard_inspire",
    "archetype_id": "bard",
    "name": "Inspire",
    "ability_type": "core",
    "level_requirement": 1,
    "cost": {"stamina": 0, "focus": 2, "scaling": None},
    "effect": "Grant an ally a die to add to any roll.",
    "narration_cue": "A few ringing words, and an ally stands ready to shine.",
}


# --- Group A: ability schema (pure parse) ---


def test_parse_carries_applies_condition():
    a = parse_ability_row("bard_inspire", {**_INSPIRE_ROW, "applies_condition": "inspired"})
    assert a.applies_condition == "inspired"


def test_parse_without_applies_condition_defaults_none():
    # Existing abilities (no producer field) parse with applies_condition None — no condition produced.
    a = parse_ability_row("warrior_devastating_strike", {**_INSPIRE_ROW, "id": "warrior_devastating_strike"})
    assert a.applies_condition is None


def test_parse_unknown_applies_condition_fails_loud():
    # Strict-loader convention: a typo'd / unknown condition type fails at parse, naming the row.
    with pytest.raises(ValueError, match="applies_condition"):
        parse_ability_row("bard_inspire", {**_INSPIRE_ROW, "applies_condition": "not_a_condition"})
