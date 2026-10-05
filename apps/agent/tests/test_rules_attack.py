import random

import pytest
from test_rules_core import SAMPLE_PLAYER

from check_resolution_attack import attack_modifier, resolve_attack


class TestResolveAttack:
    WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}

    def test_hit(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 20, rng=rng)
        assert result.hit is True
        assert result.damage > 0
        assert result.target_hp_remaining == 20 - result.damage

    def test_miss(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 18, 20, rng=rng)
        assert result.hit is False
        assert result.damage == 0
        assert result.target_hp_remaining == 20

    def test_role_attack_mod_raises_to_hit(self):
        seed = 0
        base = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 18, 20, rng=random.Random(seed))
        boosted = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 18, 20, rng=random.Random(seed), attack_mod=5)
        assert base.hit is False
        assert boosted.hit is True

    def test_role_damage_mult_scales_damage(self):
        # M4.7 story-001: damage_mult scales the final rolled total (int-truncated). hp=50 so no kill
        # interferes; same seed keeps the dice identical across the three runs.
        seed = 0
        base = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 50, rng=random.Random(seed))
        halved = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 50, rng=random.Random(seed), damage_mult=0.75)
        boosted = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 50, rng=random.Random(seed), damage_mult=1.5)
        assert base.damage > 0
        assert halved.damage == int(base.damage * 0.75)
        assert boosted.damage == int(base.damage * 1.5)

    def test_role_modifiers_default_to_identity(self):
        seed = 0
        bare = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 50, rng=random.Random(seed))
        identity = resolve_attack(
            SAMPLE_PLAYER, self.WEAPON, 12, 50, rng=random.Random(seed), attack_mod=0, damage_mult=1.0
        )
        assert bare.hit == identity.hit
        assert bare.damage == identity.damage

    def test_critical_hit_doubles_damage(self):
        seed = 5
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 20, 50, rng=rng)
        assert result.critical_success is True
        assert result.hit is True
        assert result.damage >= 2  # minimum 1+1

    def test_target_killed_at_zero_hp(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 1, rng=rng)
        if result.hit:
            assert result.target_hp_remaining == 0
            assert result.target_killed is True
            return
        pytest.fail("Could not find seed for kill")

    def test_hp_floors_at_zero(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 3, rng=rng)
        if result.hit:
            assert result.target_hp_remaining >= 0
            return
        pytest.fail("Could not find seed for hit")

    def test_nat_1_always_misses(self):
        seed = 31
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 5, 20, rng=rng)
        assert result.hit is False
        assert result.roll == 1

    def test_nat_20_dramatic(self):
        seed = 5
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 50, 100, rng=rng)
        assert result.dramatic is True
        assert result.context == "natural_20"

    def test_nat_1_dramatic(self):
        seed = 31
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 5, 20, rng=rng)
        assert result.dramatic is True
        assert result.context == "natural_1"

    def test_killing_blow_dramatic(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 1, rng=rng)
        if result.hit:
            assert result.target_killed is True
            assert result.dramatic is True
            assert result.context == "killing_blow"
            return
        pytest.fail("Could not find non-crit hit seed")

    def test_routine_hit_not_dramatic(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 100, rng=rng)
        if result.hit:
            assert result.target_killed is False
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
            result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 8, 5, rng=rng)
            assert (result.context == "killing_blow") == result.target_killed
            if result.hit and result.target_killed:
                checked_kill = True
            elif result.hit:
                checked_survive = True
        assert checked_kill, "no killing-blow seed exercised the invariant"
        assert checked_survive, "no surviving-hit seed exercised the invariant"

    def test_returns_attack_result(self):
        from check_resolution_attack import AttackResult

        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 20, rng=random.Random(42))
        assert isinstance(result, AttackResult)

    def test_nat_20_sets_critical_success_flags(self):
        seed = 5
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 50, 20, rng=rng)
        assert result.roll == 20
        assert result.hit is True
        assert result.critical_success is True
        assert result.critical_failure is False

    def test_nat_1_sets_critical_failure_flags(self):
        seed = 31
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 5, 20, rng=rng)
        assert result.roll == 1
        assert result.hit is False
        assert result.critical_failure is True
        assert result.critical_success is False

    def test_normal_roll_no_critical_flags(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 20, rng=rng)
        assert result.critical_success is False
        assert result.critical_failure is False

    def test_miss_not_dramatic(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 18, 1, rng=rng)
        assert result.hit is False
        assert result.dramatic is False
        assert result.context == ""

    def test_overkill_is_damage_beyond_target_hp(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 1, rng=rng)
        if result.hit:
            assert result.overkill == result.damage - 1
            assert result.target_hp_remaining == 0  # floor still applies to HP
            return
        pytest.fail("Could not find seed for hit")

    def test_overkill_zero_when_damage_below_target_hp(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 100, rng=rng)
        if result.hit:
            assert result.overkill == 0
            return
        pytest.fail("Could not find seed for hit")

    def test_overkill_zero_on_miss(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 18, 1, rng=rng)
        assert result.hit is False
        assert result.overkill == 0


class TestAttackModifier:
    def test_melee_weapon(self):
        weapon = {"damage": "1d8", "damage_type": "slashing", "properties": []}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        assert mod == 3

    def test_ranged_weapon(self):
        weapon = {"damage": "1d8", "ranged": True, "properties": []}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        assert mod == 2

    def test_ranged_property_uses_dexterity(self):
        weapon = {"damage": "1d8", "properties": ["ranged"]}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        assert mod == 2

    def test_finesse_weapon_uses_higher(self):
        weapon = {"damage": "1d6", "properties": ["finesse"]}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        assert mod == 3

    def test_governing_attribute_uses_that_stat(self):
        weapon = {"damage": "1d6", "governing_attribute": "intelligence"}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        assert mod == 1

    def test_governing_attribute_overrides_ranged(self):
        weapon = {"damage": "1d6", "ranged": True, "governing_attribute": "intelligence"}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        assert mod == 1

    def test_governing_attribute_dexterity_on_melee(self):
        weapon = {"damage": "1d6", "governing_attribute": "dexterity", "properties": []}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        assert mod == 2


class TestNecroticRider:
    """M4.4 story-008: an attacker carrying the temporary_hollowed condition adds a 1d6 necrotic
    rider to each hit. The rider rolls AFTER weapon damage with the same rng, so for a given seed
    the weapon roll is identical with/without the condition — the delta isolates the rider."""

    WEAPON = {"name": "Claw", "damage": "1d6", "damage_type": "slashing", "properties": []}

    def _echo_attacker(self):
        import conditions

        attacker = dict(SAMPLE_PLAYER)
        attacker["conditions"] = conditions.apply_condition([], "temporary_hollowed")
        return attacker

    def _hit_seed(self, target_hp):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 1 and d20 + 4 >= 10:
                return seed
        pytest.fail("Could not find seed for hit")

    def test_no_rider_without_the_condition(self):
        seed = self._hit_seed(50)
        result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 50, rng=random.Random(seed))
        assert result.hit is True
        assert result.bonus_damage == 0
        assert result.bonus_damage_type is None

    def test_rider_adds_1d6_necrotic_to_a_hit(self):
        seed = self._hit_seed(50)
        baseline = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 50, rng=random.Random(seed))
        echo = resolve_attack(self._echo_attacker(), self.WEAPON, 10, 50, rng=random.Random(seed))
        assert echo.hit is True
        assert echo.bonus_damage_type == "necrotic"
        assert 1 <= echo.bonus_damage <= 6
        assert echo.damage == baseline.damage + echo.bonus_damage

    def test_rider_counts_toward_overkill(self):
        seed = self._hit_seed(1)
        baseline = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 1, rng=random.Random(seed))
        echo = resolve_attack(self._echo_attacker(), self.WEAPON, 10, 1, rng=random.Random(seed))
        assert baseline.hit and echo.hit
        assert echo.overkill == baseline.overkill + echo.bonus_damage

    def test_rider_not_rolled_on_a_miss(self):
        seed = 0
        result = resolve_attack(self._echo_attacker(), self.WEAPON, 18, 20, rng=random.Random(seed))
        assert result.hit is False
        assert result.bonus_damage == 0
