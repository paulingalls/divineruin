import pytest

from conditions import (
    CONDITION_CATALOG,
    BonusDie,
    ConditionEffects,
    ConditionSpec,
    apply_condition,
    get_condition_effects,
    hollowed_stage,
    remove_condition,
    tick_conditions,
)

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


def test_catalog_has_all_21_spec_conditions():
    assert set(ALL_CONDITIONS) <= set(CONDITION_CATALOG)
    assert len(ALL_CONDITIONS) == 21
    assert "temporary_hollowed" in CONDITION_CATALOG
    assert len(CONDITION_CATALOG) == 23


@pytest.mark.parametrize("condition_type", ALL_CONDITIONS)
def test_every_catalog_entry_is_a_condition_spec(condition_type):
    spec = CONDITION_CATALOG[condition_type]
    assert isinstance(spec, ConditionSpec)
    assert spec.clearance, f"{condition_type} missing clearance"


def test_exhausted_is_stackable_with_cap_5():
    spec = CONDITION_CATALOG["exhausted"]
    assert spec.stackable is True
    assert spec.default_max_stacks == 5


def test_consumed_conditions_persist_field_is_false_by_default():
    for c in ("blessed", "inspired", "shaken"):
        assert CONDITION_CATALOG[c].persists_across_encounters is False


def test_cross_encounter_conditions_persist():
    for c in ("wounded", "exhausted", "hollowed"):
        assert CONDITION_CATALOG[c].persists_across_encounters is True


def test_no_condition_is_both_a_persistent_and_a_bonus_die_buff():
    # combat_end._end_combat_db reconciles the player's conditions back to players.data as
    # merge(existing_non_buff, acquired) + surviving_buffs, where `acquired` is the
    # persists_across_encounters set and `surviving_buffs` is the bonus_die set. That is only
    # correct while the two sets are DISJOINT — a spec with BOTH fields would be written back
    # twice (once via each path). Pin the invariant so a future catalog entry that breaks it
    # fails here instead of silently double-counting at combat end (close-review d1bd83f32076).
    both = [
        c for c, spec in CONDITION_CATALOG.items() if spec.bonus_die is not None and spec.persists_across_encounters
    ]
    assert both == [], f"conditions set both bonus_die and persists_across_encounters: {both}"


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


def test_tick_decrements_integer_durations():
    conds = apply_condition([], "shielded", duration=2)
    survivors, events = tick_conditions(conds)
    assert survivors[0]["duration"] == 1
    assert events == []


def test_tick_leaves_until_cleared_conditions_alone():
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


def test_hollowed_stage_zero_when_absent():
    assert hollowed_stage([]) == 0
    assert hollowed_stage([{"type": "exhausted", "stacks": 2}]) == 0


def test_hollowed_stage_reads_the_stage():
    assert hollowed_stage(apply_condition([], "hollowed")) == 1
    stage2 = apply_condition(apply_condition([], "hollowed"), "hollowed")
    assert hollowed_stage(stage2) == 2


def test_hollowed_stage_tolerates_json_null():
    assert hollowed_stage(None) == 0


def test_temporary_hollowed_spec_carries_rider_and_immunities():
    spec = CONDITION_CATALOG["temporary_hollowed"]
    assert spec.bonus_damage_dice == "1d6"
    assert spec.bonus_damage_type == "necrotic"
    assert set(spec.immunities) == {"charmed", "frightened", "poisoned"}
    assert spec.persists_across_encounters is False


def test_effects_surfaces_temporary_hollowed_rider_and_immunities():
    conds = apply_condition([], "temporary_hollowed")
    effects = get_condition_effects(conds)
    assert effects.bonus_damage_dice == "1d6"
    assert effects.bonus_damage_type == "necrotic"
    assert effects.immunities == frozenset({"charmed", "frightened", "poisoned"})


def test_effects_no_rider_or_immunities_by_default():
    effects = get_condition_effects([])
    assert effects.bonus_damage_dice is None
    assert effects.bonus_damage_type is None
    assert effects.immunities == frozenset()


def test_apply_condition_is_noop_for_an_immune_type():
    base = apply_condition([], "temporary_hollowed")
    for immune in ("charmed", "frightened", "poisoned"):
        out = apply_condition(base, immune)
        assert all(c["type"] != immune for c in out)


def test_apply_condition_allows_non_immune_type_on_immune_carrier():
    base = apply_condition([], "temporary_hollowed")
    out = apply_condition(base, "stunned")
    assert any(c["type"] == "stunned" for c in out)


def test_apply_condition_immunity_gate_does_not_mutate_input():
    base = apply_condition([], "temporary_hollowed")
    before = [dict(c) for c in base]
    apply_condition(base, "charmed")
    assert base == before


def test_charmed_applies_normally_without_an_immune_carrier():
    out = apply_condition([], "charmed")
    assert any(c["type"] == "charmed" for c in out)


def test_blessed_spec_carries_bonus_die_not_advantage():
    spec = CONDITION_CATALOG["blessed"]
    assert spec.bonus_die == "1d4"
    assert spec.bonus_die_scopes == ("attack", "save")
    assert spec.advantage_scopes == ()


def test_inspired_spec_carries_any_roll_bonus_die():
    spec = CONDITION_CATALOG["inspired"]
    assert spec.bonus_die == "1d4"
    assert set(spec.bonus_die_scopes) == {"attack", "save", "check"}
    assert "bonus_d4_creative_social" not in spec.restrictions


def test_effects_surfaces_blessed_bonus_die():
    effects = get_condition_effects(apply_condition([], "blessed"))
    assert effects.bonus_dice == (BonusDie(source="blessed", dice="1d4", scopes=frozenset({"attack", "save"})),)


def test_effects_surfaces_inspired_bonus_die():
    effects = get_condition_effects(apply_condition([], "inspired"))
    assert effects.bonus_dice == (
        BonusDie(source="inspired", dice="1d4", scopes=frozenset({"attack", "save", "check"})),
    )


def test_effects_surfaces_both_beneficial_dice_concurrently():
    conds = apply_condition(apply_condition([], "blessed"), "inspired")
    effects = get_condition_effects(conds)
    assert {bd.source for bd in effects.bonus_dice} == {"blessed", "inspired"}
    assert len(effects.bonus_dice) == 2


def test_effects_no_bonus_die_for_non_beneficial_condition():
    effects = get_condition_effects(apply_condition([], "poisoned"))
    assert effects.bonus_dice == ()


def test_iron_resolve_metadata():
    spec = CONDITION_CATALOG.get("iron_resolve")
    assert spec is not None
    assert spec.check_modifier == 2
    assert spec.clearance == "end_of_next_turn"
    assert not spec.persists_across_encounters
    assert spec.bonus_die is None
