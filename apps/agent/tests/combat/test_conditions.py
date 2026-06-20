"""Unit coverage for the pure status-condition module (M4.3, story-001).

Catalog and behavior mirror docs/game_mechanics/game_mechanics_combat.md
§Status Effects (L263-322). The module is pure: every test below constructs
plain inputs and asserts on returned values — no DB, no RNG, no combat state.
"""

import pytest

from conditions import (
    CONDITION_CATALOG,
    ConditionEffects,
    ConditionSpec,
    apply_condition,
    get_condition_effects,
    remove_condition,
    tick_conditions,
)

# The 21 conditions of the spec catalog, by snake_case label.
ALL_CONDITIONS = [
    "wounded",
    "stunned",
    "prone",
    "grappled",
    "restrained",
    "incapacitated",
    "paralyzed",
    "poisoned",
    "blessed",
    "shielded",
    "enraged",
    "exhausted",
    "blinded",
    "frightened",
    "charmed",
    "deafened",
    "shaken",
    "petrified",
    "cursed",
    "inspired",
    "hollowed",
]


# --- Slice 1: catalog completeness ---


def test_catalog_has_all_21_conditions():
    assert set(CONDITION_CATALOG) == set(ALL_CONDITIONS)
    assert len(CONDITION_CATALOG) == 21


@pytest.mark.parametrize("condition_type", ALL_CONDITIONS)
def test_every_catalog_entry_is_a_condition_spec(condition_type):
    spec = CONDITION_CATALOG[condition_type]
    assert isinstance(spec, ConditionSpec)
    # Each entry must declare how it clears (mirrors the doc's "Cleared By" column).
    assert spec.clearance, f"{condition_type} missing clearance"


def test_exhausted_is_stackable_with_cap_5():
    spec = CONDITION_CATALOG["exhausted"]
    assert spec.stackable is True
    assert spec.default_max_stacks == 5


def test_consumed_conditions_persist_field_is_false_by_default():
    # Blessed/Inspired/Shaken are consumed-on-use; they do not survive an encounter.
    for c in ("blessed", "inspired", "shaken"):
        assert CONDITION_CATALOG[c].persists_across_encounters is False


def test_cross_encounter_conditions_persist():
    # Wounded (until long rest), Exhausted (per long rest), Hollowed (Greater Restoration)
    # outlive a single encounter.
    for c in ("wounded", "exhausted", "hollowed"):
        assert CONDITION_CATALOG[c].persists_across_encounters is True


# --- Slice 2: apply_condition ---


def test_apply_adds_a_condition_with_source():
    result = apply_condition([], "stunned", source="war_cry")
    assert result == [{"type": "stunned", "duration": None, "source": "war_cry", "stacks": 1}]


def test_apply_does_not_mutate_the_input_list():
    original: list[dict] = []
    apply_condition(original, "poisoned")
    assert original == []


def test_apply_carries_duration():
    result = apply_condition([], "shielded", duration=3)
    assert result[0]["duration"] == 3


def test_apply_stacks_up_to_default_cap():
    conds: list[dict] = []
    for _ in range(7):  # cap is 5
        conds = apply_condition(conds, "exhausted")
    exhausted = [c for c in conds if c["type"] == "exhausted"]
    assert len(exhausted) == 1  # one instance, not seven
    assert exhausted[0]["stacks"] == 5


def test_apply_honors_max_stacks_override():
    # Iron Constitution caps exhaustion at 3 (story-003 passes the override).
    conds: list[dict] = []
    for _ in range(5):
        conds = apply_condition(conds, "exhausted", max_stacks=3)
    assert conds[0]["stacks"] == 3


def test_apply_nonstackable_refreshes_instead_of_duplicating():
    conds = apply_condition([], "poisoned", duration=2, source="snake")
    conds = apply_condition(conds, "poisoned", duration=5, source="spider")
    poisoned = [c for c in conds if c["type"] == "poisoned"]
    assert len(poisoned) == 1
    assert poisoned[0]["duration"] == 5
    assert poisoned[0]["source"] == "spider"


def test_apply_hollowed_starts_at_stage_1_and_escalates():
    conds = apply_condition([], "hollowed")
    assert conds[0]["stage"] == 1
    conds = apply_condition(conds, "hollowed")
    assert conds[0]["stage"] == 2
    conds = apply_condition(conds, "hollowed")
    conds = apply_condition(conds, "hollowed")
    assert conds[0]["stage"] == 3  # capped at 3
    assert len([c for c in conds if c["type"] == "hollowed"]) == 1


def test_apply_unknown_condition_raises():
    with pytest.raises(ValueError):
        apply_condition([], "confused")


# --- Slice 3: remove_condition ---


def test_remove_drops_named_condition_and_leaves_others():
    conds = apply_condition([], "prone")
    conds = apply_condition(conds, "blinded")
    result = remove_condition(conds, "prone")
    assert [c["type"] for c in result] == ["blinded"]


def test_remove_absent_condition_is_a_noop():
    conds = apply_condition([], "prone")
    assert remove_condition(conds, "stunned") == conds


def test_remove_does_not_mutate_input():
    conds = apply_condition([], "prone")
    remove_condition(conds, "prone")
    assert [c["type"] for c in conds] == ["prone"]


# --- Slice 4: tick_conditions ---


def test_tick_decrements_integer_durations():
    conds = apply_condition([], "shielded", duration=2)
    survivors, events = tick_conditions(conds)
    assert survivors[0]["duration"] == 1
    assert events == []


def test_tick_removes_expired_conditions():
    conds = apply_condition([], "shielded", duration=1)
    survivors, _ = tick_conditions(conds)
    assert survivors == []


def test_tick_leaves_until_cleared_conditions_alone():
    # duration None = until explicitly cleared; tick must not touch it.
    conds = apply_condition([], "poisoned")
    survivors, _ = tick_conditions(conds)
    assert survivors == conds


def test_tick_surfaces_save_event_only_for_save_to_clear_conditions():
    conds = apply_condition([], "frightened", source="wraith")
    conds = apply_condition(conds, "poisoned")  # not a tick-save condition
    _, events = tick_conditions(conds)
    assert events == [{"type": "frightened", "save": "wis", "source": "wraith"}]


def test_tick_does_not_mutate_input():
    conds = apply_condition([], "shielded", duration=2)
    tick_conditions(conds)
    assert conds[0]["duration"] == 2


# --- Slice 5: get_condition_effects ---


def test_effects_empty_for_no_conditions():
    assert get_condition_effects([]) == ConditionEffects()


def test_effects_exhausted_penalty_scales_with_stacks():
    conds: list[dict] = []
    for _ in range(3):
        conds = apply_condition(conds, "exhausted")
    assert get_condition_effects(conds).check_modifier == -3


def test_effects_enraged_modifies_ac_and_damage():
    conds = apply_condition([], "enraged")
    effects = get_condition_effects(conds)
    assert effects.ac_modifier == -2
    assert effects.damage_modifier == 2


def test_effects_unions_disadvantage_scopes_and_restrictions():
    conds = apply_condition([], "poisoned")  # str/dex/con disadvantage
    conds = apply_condition(conds, "stunned")  # skip_phase, auto-fail str/dex
    effects = get_condition_effects(conds)
    assert {"str", "dex", "con"} <= effects.disadvantage_scopes
    assert "skip_phase" in effects.restrictions
    assert {"str", "dex"} <= effects.auto_fail_saves


def test_effects_hollowed_stage_1_disadvantages_wis_only():
    conds = apply_condition([], "hollowed")
    effects = get_condition_effects(conds)
    assert "wis" in effects.disadvantage_scopes
    assert "hallucinations" not in effects.restrictions
    assert "stat_drain" not in effects.restrictions


def test_effects_hollowed_stage_3_adds_stat_drain():
    conds = apply_condition([], "hollowed")
    conds = apply_condition(conds, "hollowed")
    conds = apply_condition(conds, "hollowed")
    effects = get_condition_effects(conds)
    assert "wis" in effects.disadvantage_scopes
    assert "hallucinations" in effects.restrictions
    assert "stat_drain" in effects.restrictions
