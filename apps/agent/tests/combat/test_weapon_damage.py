"""Contract tests for weapon damage math + the Heavy weapon catalog (story-003).

Pins resolve_attack's damage formula: damage = weapon die + attribute modifier,
using the same governing/finesse/ranged/else-STR attribute selection as the
attack roll, with the modifier added ONCE even on a crit and NO proficiency on
damage (proficiency applies only to the attack roll — spec
game_mechanics_combat.md:208 vs the Weapon Damage table at 222-228).

Also pins the 1d12 Heavy weapons (greataxe, halberd) in the catalog and the
Warrior starting loadout (greataxe, shield dropped — two-handed).
"""

import random

import pytest
from test_content_validation import _load_json
from test_rules_core import SAMPLE_PLAYER

from check_resolution import resolve_attack
from creation_classes import CLASSES
from dice import roll as dice_roll
from rules_engine import attribute_modifier

_STR_MOD = attribute_modifier(SAMPLE_PLAYER["attributes"]["strength"])  # STR 14 -> +2


def _str_weapon(notation: str) -> dict:
    """A weapon with no finesse/ranged/governing override, so STR governs (Heavy)."""
    return {"name": notation, "damage": notation, "damage_type": "slashing", "properties": []}


def _expected_die_total(seed: int, notation: str, *, crit: bool = False) -> int:
    """Replay the RNG resolve_attack consumes so we can predict the damage dice.

    resolve_attack draws the d20 first (dice.roll('d20')) then the damage die
    (dice.roll(notation)); on a crit it draws the damage die a second time. Each
    dice.roll() pulls one randint per die from the shared rng, so replaying the
    same seed in the same order reproduces the exact rolls.
    """
    rng = random.Random(seed)
    rng.randint(1, 20)  # the attack d20
    total = dice_roll(notation, rng=rng).total
    if crit:
        total += dice_roll(notation, rng=rng).total
    return total


class TestDamageMathContract:
    @pytest.mark.parametrize("notation", ["1d4", "1d6", "1d8", "1d12"])
    def test_damage_adds_attribute_modifier_once(self, notation: str) -> None:
        weapon = _str_weapon(notation)
        for seed in range(2000):
            if not 1 < random.Random(seed).randint(1, 20) < 20:
                continue  # skip nat-1 (auto-miss) and nat-20 (crit)
            result = resolve_attack(SAMPLE_PLAYER, weapon, 2, 100, rng=random.Random(seed))
            if not result.hit or result.critical_success:
                continue
            assert result.damage == _expected_die_total(seed, notation) + _STR_MOD
            return
        pytest.fail(f"no normal-hit seed found for {notation}")

    def test_crit_doubles_dice_with_modifier_added_once(self) -> None:
        notation = "1d12"
        weapon = _str_weapon(notation)
        for seed in range(2000):
            if random.Random(seed).randint(1, 20) != 20:
                continue
            result = resolve_attack(SAMPLE_PLAYER, weapon, 2, 100, rng=random.Random(seed))
            assert result.critical_success is True
            assert result.damage == _expected_die_total(seed, notation, crit=True) + _STR_MOD
            return
        pytest.fail("no nat-20 seed found")

    def test_damage_uses_governing_attribute_not_strength(self) -> None:
        # An explicit governing attribute overrides STR for damage, just as it
        # does for the attack roll — proves the attribute selection reaches damage.
        attacker = {"level": 1, "attributes": {"strength": 10, "dexterity": 18}}
        weapon = {
            "name": "Rapier",
            "damage": "1d6",
            "damage_type": "piercing",
            "governing_attribute": "dexterity",
            "properties": [],
        }
        dex_mod = attribute_modifier(18)  # +4
        assert dex_mod != attribute_modifier(10)  # guard: STR(+0) would differ
        for seed in range(2000):
            if not 1 < random.Random(seed).randint(1, 20) < 20:
                continue
            result = resolve_attack(attacker, weapon, 2, 100, rng=random.Random(seed))
            if not result.hit or result.critical_success:
                continue
            assert result.damage == _expected_die_total(seed, "1d6") + dex_mod
            return
        pytest.fail("no normal-hit seed found for governing-attribute case")


class TestHeavyWeaponCatalog:
    @pytest.mark.parametrize("weapon_id", ["greataxe_basic", "halberd_basic"])
    def test_heavy_weapon_is_1d12_str_governed(self, weapon_id: str) -> None:
        by_id = {item["id"]: item for item in _load_json("items.json")}
        assert weapon_id in by_id, f"{weapon_id} missing from items.json"
        weapon = by_id[weapon_id]
        assert weapon["type"] == "weapon"
        assert weapon["damage_dice"] == "1d12"
        assert "heavy" in weapon["properties"]
        # STR governs: no finesse, not ranged, no non-STR override.
        assert "finesse" not in weapon["properties"]
        assert weapon.get("ranged", False) is False
        assert weapon.get("governing_attribute", "strength") == "strength"


class TestWarriorHeavyLoadout:
    def test_warrior_starts_with_greataxe_and_no_shield(self) -> None:
        warrior = CLASSES["warrior"]
        main_hand = warrior.starting_equipment["main_hand"]
        assert main_hand["name"] == "Greataxe"
        assert main_hand["damage"] == "1d12"
        assert "finesse" not in main_hand.get("properties", [])  # STR governs
        assert warrior.starting_equipment["shield"] is None  # two-handed
