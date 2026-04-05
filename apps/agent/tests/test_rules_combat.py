"""Tests for combat resolution: initiative, death saves, HP thresholds, combat XP."""

import random

import pytest

from combat_resolution import (
    calculate_combat_xp,
    hp_threshold_status,
    resolve_death_save,
    roll_initiative,
)

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
