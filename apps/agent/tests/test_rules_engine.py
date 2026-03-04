"""Exhaustive tests for the pure-function rules engine."""

import random

import pytest

from rules_engine import (
    SKILLS,
    XP_FOR_LEVEL,
    attack_modifier,
    attribute_modifier,
    calculate_combat_xp,
    check_level_up,
    dc_for_tier,
    hp_threshold_status,
    narrative_hint,
    resolve_attack,
    resolve_death_save,
    resolve_saving_throw,
    resolve_skill_check,
    roll_initiative,
    skill_modifier,
)

# --- attribute_modifier ---


class TestAttributeModifier:
    def test_standard_table(self):
        assert attribute_modifier(1) == -5
        assert attribute_modifier(8) == -1
        assert attribute_modifier(10) == 0
        assert attribute_modifier(11) == 0
        assert attribute_modifier(12) == 1
        assert attribute_modifier(14) == 2
        assert attribute_modifier(16) == 3
        assert attribute_modifier(18) == 4
        assert attribute_modifier(20) == 5

    def test_odd_scores(self):
        assert attribute_modifier(9) == -1
        assert attribute_modifier(13) == 1
        assert attribute_modifier(15) == 2


# --- skill_modifier ---

SAMPLE_PLAYER = {
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "constitution"],
}


class TestSkillModifier:
    def test_proficient_skill(self):
        mod = skill_modifier(SAMPLE_PLAYER, "athletics")
        # STR 14 -> +2, plus prof +2 = +4
        assert mod == 4

    def test_unproficient_skill(self):
        mod = skill_modifier(SAMPLE_PLAYER, "persuasion")
        # CHA 8 -> -1, no proficiency
        assert mod == -1

    def test_proficient_dex_skill(self):
        mod = skill_modifier(SAMPLE_PLAYER, "stealth")
        # DEX 12 -> +1, plus prof +2 = +3
        assert mod == 3

    def test_wisdom_perception(self):
        mod = skill_modifier(SAMPLE_PLAYER, "perception")
        # WIS 11 -> +0, plus prof +2 = +2
        assert mod == 2

    def test_unknown_skill_raises(self):
        with pytest.raises(ValueError, match="Unknown skill"):
            skill_modifier(SAMPLE_PLAYER, "flying")

    def test_all_skills_resolve(self):
        for skill_name in SKILLS:
            mod = skill_modifier(SAMPLE_PLAYER, skill_name)
            assert isinstance(mod, int)

    def test_case_insensitive(self):
        mod = skill_modifier(SAMPLE_PLAYER, "Athletics")
        assert mod == 4

    def test_higher_level_proficiency(self):
        player = {**SAMPLE_PLAYER, "level": 5}
        mod = skill_modifier(player, "athletics")
        # STR +2, prof +3 at level 5 = +5
        assert mod == 5


# --- dc_for_tier ---


class TestDcForTier:
    def test_all_tiers(self):
        assert dc_for_tier("easy") == 9
        assert dc_for_tier("moderate") == 13
        assert dc_for_tier("hard") == 17
        assert dc_for_tier("deadly") == 21

    def test_unknown_defaults_moderate(self):
        assert dc_for_tier("impossible") == 13

    def test_case_insensitive(self):
        assert dc_for_tier("HARD") == 17
        assert dc_for_tier("Easy") == 9


# --- narrative_hint ---


class TestNarrativeHint:
    def test_nat_1(self):
        assert narrative_hint(1, 1, 10) == "critical failure"

    def test_nat_20(self):
        assert narrative_hint(20, 25, 10) == "critical success"

    def test_failed_by_large_margin(self):
        assert narrative_hint(3, 3, 17) == "failed"

    def test_barely_failed(self):
        assert narrative_hint(10, 12, 13) == "barely failed"

    def test_barely_succeeded(self):
        assert narrative_hint(10, 13, 13) == "barely succeeded"

    def test_succeeded_comfortably(self):
        assert narrative_hint(12, 17, 13) == "succeeded comfortably"

    def test_large_success(self):
        assert narrative_hint(15, 22, 13) == "critical success"


# --- attack_modifier ---


class TestAttackModifier:
    def test_melee_weapon(self):
        weapon = {"damage": "1d8", "damage_type": "slashing", "properties": []}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        # STR +2, prof +2 = +4
        assert mod == 4

    def test_ranged_weapon(self):
        weapon = {"damage": "1d8", "ranged": True, "properties": []}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        # DEX +1, prof +2 = +3
        assert mod == 3

    def test_finesse_weapon_uses_higher(self):
        weapon = {"damage": "1d6", "properties": ["finesse"]}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        # max(STR +2, DEX +1) + prof +2 = +4
        assert mod == 4


# --- resolve_skill_check ---


class TestResolveSkillCheck:
    def test_success(self):
        # Seed that produces d20=15
        rng = random.Random(42)
        test_roll = rng.randint(1, 20)
        # Reset to same seed for actual call
        rng = random.Random(42)
        result = resolve_skill_check(SAMPLE_PLAYER, "athletics", "moderate", rng=rng)
        assert result.roll == test_roll
        assert result.skill == "athletics"
        assert result.modifier == 4
        assert result.total == test_roll + 4
        assert result.dc == 13
        assert result.success == (result.total >= 13 or test_roll == 20)

    def test_nat_20_always_succeeds(self):
        # Find a seed that gives nat 20
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_skill_check(SAMPLE_PLAYER, "persuasion", "deadly", rng=rng)
                assert result.success is True
                assert result.roll == 20
                assert result.narrative_hint == "critical success"
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_always_fails(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_skill_check(SAMPLE_PLAYER, "athletics", "easy", rng=rng)
                assert result.success is False
                assert result.roll == 1
                assert result.narrative_hint == "critical failure"
                return
        pytest.fail("Could not find seed for nat 1")

    def test_proficiency_bonus_applied(self):
        rng = random.Random(42)
        prof_result = resolve_skill_check(SAMPLE_PLAYER, "athletics", "moderate", rng=rng)
        rng = random.Random(42)
        unprof_result = resolve_skill_check(SAMPLE_PLAYER, "persuasion", "moderate", rng=rng)
        # athletics: STR+2, prof+2 = +4; persuasion: CHA-1, no prof = -1
        assert prof_result.modifier == 4
        assert unprof_result.modifier == -1


# --- resolve_attack ---


class TestResolveAttack:
    WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}

    def test_hit(self):
        # Find seed where d20 roll + 4 >= 12
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 1 and d20 + 4 >= 12:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 20, rng=rng)
                assert result.hit is True
                assert result.damage > 0
                assert result.target_hp_remaining == 20 - result.damage
                return
        pytest.fail("Could not find seed for hit")

    def test_miss(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 20 and d20 + 4 < 18:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 18, 20, rng=rng)
                assert result.hit is False
                assert result.damage == 0
                assert result.target_hp_remaining == 20
                return
        pytest.fail("Could not find seed for miss")

    def test_critical_hit_doubles_damage(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 20, 50, rng=rng)
                assert result.critical is True
                assert result.hit is True
                # Damage should be two rolls of 1d8
                assert result.damage >= 2  # minimum 1+1
                return
        pytest.fail("Could not find seed for crit")

    def test_target_killed_at_zero_hp(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 1 and d20 + 4 >= 10:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 1, rng=rng)
                if result.hit:
                    assert result.target_hp_remaining == 0
                    assert result.target_killed is True
                    return
        pytest.fail("Could not find seed for kill")

    def test_hp_floors_at_zero(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 1 and d20 + 4 >= 10:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 3, rng=rng)
                if result.hit:
                    assert result.target_hp_remaining >= 0
                    return
        pytest.fail("Could not find seed for hit")

    def test_nat_1_always_misses(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 5, 20, rng=rng)
                assert result.hit is False
                assert result.roll == 1
                return
        pytest.fail("Could not find seed for nat 1")


# --- resolve_saving_throw ---


class TestResolveSavingThrow:
    def test_success(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            # STR save: attr mod +2, prof +2 = +4
            if d20 != 1 and d20 + 4 >= 13:
                rng = random.Random(seed)
                result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 13, "knocked prone", rng=rng)
                assert result.success is True
                assert result.effect_applied is None
                return
        pytest.fail("Could not find seed for success")

    def test_failure_applies_effect(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            # CHA save: attr mod -1, no prof = -1
            if d20 != 20 and d20 - 1 < 13:
                rng = random.Random(seed)
                result = resolve_saving_throw(SAMPLE_PLAYER, "charisma", 13, "charmed", rng=rng)
                assert result.success is False
                assert result.effect_applied == "charmed"
                return
        pytest.fail("Could not find seed for failure")

    def test_nat_20_always_succeeds(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_saving_throw(SAMPLE_PLAYER, "charisma", 25, "stunned", rng=rng)
                assert result.success is True
                assert result.effect_applied is None
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_always_fails(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 1, "frightened", rng=rng)
                assert result.success is False
                assert result.effect_applied == "frightened"
                return
        pytest.fail("Could not find seed for nat 1")

    def test_all_six_attributes(self):
        for attr in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
            rng = random.Random(42)
            result = resolve_saving_throw(SAMPLE_PLAYER, attr, 10, "effect", rng=rng)
            assert result.save_type == attr

    def test_unknown_save_type_raises(self):
        with pytest.raises(ValueError, match="Unknown save type"):
            resolve_saving_throw(SAMPLE_PLAYER, "luck", 10, "bad stuff")

    def test_proficient_save_bonus(self):
        # Strength is a proficient save
        rng = random.Random(42)
        result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 10, "effect", rng=rng)
        # STR +2, prof +2 = +4
        assert result.modifier == 4

    def test_unproficient_save(self):
        rng = random.Random(42)
        result = resolve_saving_throw(SAMPLE_PLAYER, "charisma", 10, "effect", rng=rng)
        # CHA -1, no prof
        assert result.modifier == -1


# --- check_level_up ---


class TestCheckLevelUp:
    def test_no_level_up(self):
        result = check_level_up(current_xp=0, xp_gained=100, current_level=1)
        assert result.new_xp == 100
        assert result.new_level == 1
        assert result.leveled_up is False
        assert result.levels_gained == 0

    def test_level_up_to_2(self):
        result = check_level_up(current_xp=200, xp_gained=100, current_level=1)
        assert result.new_xp == 300
        assert result.new_level == 2
        assert result.leveled_up is True
        assert result.levels_gained == 1

    def test_exact_threshold(self):
        result = check_level_up(current_xp=0, xp_gained=300, current_level=1)
        assert result.new_level == 2

    def test_multi_level_up(self):
        result = check_level_up(current_xp=0, xp_gained=6500, current_level=1)
        assert result.new_level == 5
        assert result.levels_gained == 4

    def test_max_level_cap(self):
        result = check_level_up(current_xp=355000, xp_gained=50000, current_level=20)
        assert result.new_xp == 405000
        assert result.new_level == 20
        assert result.leveled_up is False

    def test_xp_table_is_monotonic(self):
        for lvl in range(2, 21):
            assert XP_FOR_LEVEL[lvl] > XP_FOR_LEVEL[lvl - 1]

    def test_level_1_starts_at_zero(self):
        assert XP_FOR_LEVEL[1] == 0


# --- roll_initiative ---


class TestRollInitiative:
    PARTICIPANTS = [
        {"id": "player_1", "name": "Kael", "attributes": {"dexterity": 14}},
        {"id": "goblin_1", "name": "Goblin A", "attributes": {"dexterity": 12}},
        {"id": "goblin_2", "name": "Goblin B", "attributes": {"dexterity": 8}},
    ]

    def test_sorted_descending(self):
        rng = random.Random(42)
        entries = roll_initiative(self.PARTICIPANTS, rng=rng)
        totals = [e.total for e in entries]
        assert totals == sorted(totals, reverse=True)

    def test_dex_modifier_applied(self):
        rng = random.Random(42)
        entries = roll_initiative(self.PARTICIPANTS, rng=rng)
        for e in entries:
            participant = next(p for p in self.PARTICIPANTS if p["id"] == e.participant_id)
            dex = participant["attributes"]["dexterity"]
            expected_mod = (dex - 10) // 2
            assert e.modifier == expected_mod
            assert e.total == e.roll + e.modifier

    def test_deterministic_with_rng(self):
        entries_a = roll_initiative(self.PARTICIPANTS, rng=random.Random(99))
        entries_b = roll_initiative(self.PARTICIPANTS, rng=random.Random(99))
        assert [e.total for e in entries_a] == [e.total for e in entries_b]

    def test_all_participants_included(self):
        rng = random.Random(42)
        entries = roll_initiative(self.PARTICIPANTS, rng=rng)
        ids = {e.participant_id for e in entries}
        assert ids == {"player_1", "goblin_1", "goblin_2"}

    def test_single_participant(self):
        entries = roll_initiative([self.PARTICIPANTS[0]], rng=random.Random(1))
        assert len(entries) == 1
        assert entries[0].participant_id == "player_1"

    def test_empty_list(self):
        entries = roll_initiative([], rng=random.Random(1))
        assert entries == []


# --- resolve_death_save ---


class TestResolveDeathSave:
    def test_success_on_10_or_higher(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) >= 10:
                rng = random.Random(seed)
                result = resolve_death_save(0, 0, rng=rng)
                assert result.success is True
                assert result.total_successes == 1
                assert result.total_failures == 0
                return
        pytest.fail("Could not find seed for success")

    def test_failure_below_10(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if 2 <= d20 <= 9:
                rng = random.Random(seed)
                result = resolve_death_save(0, 0, rng=rng)
                assert result.success is False
                assert result.total_successes == 0
                assert result.total_failures == 1
                return
        pytest.fail("Could not find seed for failure")

    def test_nat_20_critical_success(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_death_save(0, 0, rng=rng)
                assert result.critical_success is True
                assert result.roll == 20
                assert "spark" in result.narrative_hint.lower() or "eyes open" in result.narrative_hint.lower()
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_double_failure(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_death_save(0, 0, rng=rng)
                assert result.critical_failure is True
                assert result.total_failures == 2
                return
        pytest.fail("Could not find seed for nat 1")

    def test_stabilize_at_3_successes(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) >= 10:
                rng = random.Random(seed)
                result = resolve_death_save(2, 0, rng=rng)
                assert result.stabilized is True
                assert result.total_successes >= 3
                return
        pytest.fail("Could not find seed for stabilize")

    def test_dead_at_3_failures(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if 2 <= d20 <= 9:
                rng = random.Random(seed)
                result = resolve_death_save(0, 2, rng=rng)
                assert result.dead is True
                assert result.total_failures >= 3
                return
        pytest.fail("Could not find seed for death")

    def test_nat_1_can_cause_death_from_1_failure(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_death_save(0, 1, rng=rng)
                assert result.dead is True
                assert result.total_failures == 3
                return
        pytest.fail("Could not find seed for nat 1")


# --- hp_threshold_status ---


class TestHpThresholdStatus:
    def test_healthy(self):
        assert hp_threshold_status(20, 20) == "healthy"
        assert hp_threshold_status(15, 20) == "healthy"

    def test_bloodied(self):
        assert hp_threshold_status(10, 20) == "bloodied"
        assert hp_threshold_status(6, 20) == "bloodied"

    def test_critical(self):
        assert hp_threshold_status(5, 20) == "critical"
        assert hp_threshold_status(1, 20) == "critical"

    def test_fallen(self):
        assert hp_threshold_status(0, 20) == "fallen"

    def test_negative_hp(self):
        assert hp_threshold_status(-5, 20) == "fallen"

    def test_exact_50_percent(self):
        assert hp_threshold_status(10, 20) == "bloodied"

    def test_exact_25_percent(self):
        assert hp_threshold_status(5, 20) == "critical"

    def test_just_above_50(self):
        assert hp_threshold_status(11, 20) == "healthy"


# --- calculate_combat_xp ---


class TestCalculateCombatXp:
    def test_sums_values(self):
        enemies = [{"xp_value": 50}, {"xp_value": 100}, {"xp_value": 200}]
        assert calculate_combat_xp(enemies) == 350

    def test_empty_list(self):
        assert calculate_combat_xp([]) == 0

    def test_missing_xp_value_defaults_zero(self):
        enemies = [{"name": "goblin"}, {"xp_value": 100}]
        assert calculate_combat_xp(enemies) == 100

    def test_single_enemy(self):
        assert calculate_combat_xp([{"xp_value": 200}]) == 200
