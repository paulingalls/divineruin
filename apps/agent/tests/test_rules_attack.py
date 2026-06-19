"""Tests for resolve_attack: attack roll, crit, damage, kill, HP floor, nat-1.

Extracted from test_rules_resolution.py (file-size touch-split, concern
d80d59f0e896) to bring that file back under the 500-line cap.
"""

import random

import pytest
from test_rules_core import SAMPLE_PLAYER

from check_resolution import resolve_attack


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
                assert result.critical_success is True
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

    # --- Dramatic fields (story-002) ---

    def test_nat_20_dramatic(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 50, 100, rng=rng)
                assert result.dramatic is True
                assert result.context == "natural_20"
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_dramatic(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 5, 20, rng=rng)
                assert result.dramatic is True
                assert result.context == "natural_1"
                return
        pytest.fail("Could not find seed for nat 1")

    def test_killing_blow_dramatic(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if 2 <= rng.randint(1, 20) <= 19:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 1, rng=rng)
                if result.hit:
                    assert result.target_killed is True
                    assert result.dramatic is True
                    assert result.context == "killing_blow"
                    return
        pytest.fail("Could not find non-crit hit seed")

    def test_routine_hit_not_dramatic(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if 2 <= rng.randint(1, 20) <= 19:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 100, rng=rng)
                if result.hit:
                    assert result.dramatic is False
                    assert result.context == ""
                    return
        pytest.fail("Could not find non-crit hit seed")

    def test_killing_blow_label_matches_target_killed_invariant(self):
        # INVARIANT: for any non-crit resolved attack, the dramatic killing_blow
        # label and the mechanical target_killed flag never disagree. The crit
        # path is excluded because natural_20/natural_1 outrank killing_blow in
        # the catalog, so the label is "natural_*" even on a crit kill.
        checked_kill = False
        checked_survive = False
        for seed in range(2000):
            rng = random.Random(seed)
            if not (2 <= rng.randint(1, 20) <= 19):
                continue
            rng = random.Random(seed)
            # Small target HP so both kill and non-kill outcomes occur across seeds.
            result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 8, 5, rng=rng)
            assert (result.context == "killing_blow") == result.target_killed
            if result.hit and result.target_killed:
                checked_kill = True
            elif result.hit:
                checked_survive = True
        assert checked_kill, "no killing-blow seed exercised the invariant"
        assert checked_survive, "no surviving-hit seed exercised the invariant"
