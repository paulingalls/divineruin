import importlib
import json
import random
import sys
from pathlib import Path

import pytest

from encounter_loot import (
    _BOSS_CURRENCY_BONUS,
    PARTY_REWARD_BONUS,
    calculate_currency_drop,
    derive_role_loot,
    party_reward_multiplier,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
validate_loot_table = importlib.import_module("seed_content").validate_loot_table


class FakeRng(random.Random):
    """A random.Random whose randint() returns a fixed per-die value and random() a fixed float.

    dice.roll consumes randint(1, sides); the currency/loot chance gates consume random(). Both
    are pinned so the role math is exercised without real randomness. Subclasses Random so it
    type-checks as the rng parameter the production functions expect."""

    def __init__(self, die: int = 3, chance: float = 0.0):
        super().__init__()
        self._die = die
        self._chance = chance

    def randint(self, a: int, b: int) -> int:
        return self._die

    def random(self) -> float:
        return self._chance


def test_minion_drops_no_currency_d79() -> None:
    assert calculate_currency_drop("humanoid", 4, "minion", FakeRng(die=6)) == 0


@pytest.mark.parametrize("category", ["beast", "hollow_drift", "construct", "named"])
@pytest.mark.parametrize("role", ["standard", "elite", "boss"])
def test_no_currency_categories_drop_nothing(category: str, role: str) -> None:
    assert calculate_currency_drop(category, 3, role, FakeRng(die=6)) == 0


def test_humanoid_standard_is_tier_times_d6() -> None:
    assert calculate_currency_drop("humanoid", 2, "standard", FakeRng(die=4)) == 8


def test_humanoid_elite_is_ceil_1_5x_base() -> None:
    assert calculate_currency_drop("humanoid", 2, "elite", FakeRng(die=5)) == 15


def test_humanoid_elite_rounds_up() -> None:
    assert calculate_currency_drop("humanoid", 1, "elite", FakeRng(die=3)) == 5


def test_humanoid_boss_is_double_base_plus_tier_bonus() -> None:
    expected = 24 + _BOSS_CURRENCY_BONUS[3]
    assert calculate_currency_drop("humanoid", 3, "boss", FakeRng(die=4)) == expected


def test_hollow_rend_hits_on_low_chance_roll() -> None:
    assert calculate_currency_drop("hollow_rend", 2, "standard", FakeRng(die=3, chance=0.10)) == 12


def test_hollow_rend_misses_on_high_chance_roll() -> None:
    assert calculate_currency_drop("hollow_rend", 2, "standard", FakeRng(die=3, chance=0.50)) == 0


def test_undead_hits_on_low_chance_roll() -> None:
    assert calculate_currency_drop("undead", 3, "standard", FakeRng(die=2, chance=0.20)) == 6


def test_undead_misses_on_high_chance_roll() -> None:
    assert calculate_currency_drop("undead", 3, "standard", FakeRng(die=2, chance=0.40)) == 0


def test_boss_still_drops_guaranteed_bonus_when_base_roll_empty() -> None:
    got = calculate_currency_drop("hollow_rend", 4, "boss", FakeRng(die=6, chance=0.99))
    assert got == _BOSS_CURRENCY_BONUS[4]


def test_unknown_category_raises() -> None:
    with pytest.raises(ValueError, match="Unknown creature category"):
        calculate_currency_drop("dragon", 1, "standard", FakeRng())


def test_unknown_role_raises_for_currency() -> None:
    with pytest.raises(ValueError, match="Unknown encounter role"):
        calculate_currency_drop("humanoid", 1, "champion", FakeRng())


def _table() -> dict:
    return {
        "id": "t",
        "drops": [
            {"item_id": "hide", "chance": 0.5, "quantity": 2},
            {"item_id": "bone", "chance": 0.2, "quantity": 1},
        ],
    }


def test_standard_loot_drops_entries_whose_chance_passes() -> None:
    drops = derive_role_loot(_table(), "standard", FakeRng(chance=0.0))
    assert drops == [{"item_id": "hide", "quantity": 2}, {"item_id": "bone", "quantity": 1}]


def test_standard_loot_omits_entries_whose_chance_fails() -> None:
    assert derive_role_loot(_table(), "standard", FakeRng(chance=0.6)) == []


def test_minion_loot_halves_chance_and_drops_quantity() -> None:
    drops = derive_role_loot(_table(), "minion", FakeRng(chance=0.05))
    assert drops == [{"item_id": "hide", "quantity": 1}, {"item_id": "bone", "quantity": 1}]


def test_minion_loot_chance_has_5pct_floor() -> None:
    table = {"drops": [{"item_id": "x", "chance": 0.08, "quantity": 1}]}
    assert derive_role_loot(table, "minion", FakeRng(chance=0.045)) == [{"item_id": "x", "quantity": 1}]


def test_elite_loot_adds_chance_and_quantity() -> None:
    drops = derive_role_loot(_table(), "elite", FakeRng(chance=0.5))
    assert drops == [{"item_id": "hide", "quantity": 3}]


def test_elite_loot_chance_caps_at_one() -> None:
    table = {"drops": [{"item_id": "x", "chance": 0.9, "quantity": 1}]}
    assert derive_role_loot(table, "elite", FakeRng(chance=0.99)) == [{"item_id": "x", "quantity": 2}]


def test_boss_loot_is_guaranteed_and_boosts_quantity() -> None:
    drops = derive_role_loot(_table(), "boss", FakeRng(chance=0.99))
    assert drops == [{"item_id": "hide", "quantity": 3}, {"item_id": "bone", "quantity": 2}]


def test_named_loot_is_identity() -> None:
    drops = derive_role_loot(_table(), "named", FakeRng(chance=0.0))
    assert drops == [{"item_id": "hide", "quantity": 2}, {"item_id": "bone", "quantity": 1}]


def test_empty_loot_table_yields_no_drops() -> None:
    assert derive_role_loot({"drops": []}, "boss", FakeRng(chance=0.0)) == []
    assert derive_role_loot({}, "standard", FakeRng(chance=0.0)) == []


def test_derive_role_loot_unknown_role_raises() -> None:
    with pytest.raises(ValueError, match="Unknown encounter role"):
        derive_role_loot(_table(), "champion", FakeRng())


def test_derive_role_loot_does_not_mutate_input() -> None:
    table = _table()
    derive_role_loot(table, "boss", FakeRng(chance=0.0))
    assert table["drops"][0] == {"item_id": "hide", "chance": 0.5, "quantity": 2}


@pytest.mark.parametrize(
    "die,role,expected",
    [
        (1, "minion", 1),
        (4, "minion", 3),
        (1, "standard", 1),
        (4, "standard", 4),
        (1, "elite", 2),
        (4, "elite", 5),
        (1, "boss", 2),
        (3, "boss", 5),
        (4, "boss", 6),
    ],
)
def test_dice_quantity_rolls_before_role_modifier(die: int, role: str, expected: int) -> None:
    table = {"drops": [{"item_id": "residue", "chance": 1.0, "quantity": "1d4"}]}
    assert derive_role_loot(table, role, FakeRng(die=die)) == [{"item_id": "residue", "quantity": expected}]


def test_missed_dice_drop_does_not_roll_quantity() -> None:
    rng = random.Random(20)
    before = rng.getstate()
    table = {"drops": [{"item_id": "residue", "chance": 0.0, "quantity": "1d4"}]}
    assert derive_role_loot(table, "standard", rng) == []
    rng.setstate(before)
    rng.random()
    expected_next = rng.random()
    rng.setstate(before)
    derive_role_loot(table, "standard", rng)
    assert rng.random() == expected_next


def assert_rollable_tables(tables: list[dict]) -> None:
    assert tables
    for table in tables:
        assert table["drops"], table["id"]
        assert validate_loot_table(table) == []
        drops = derive_role_loot(table, "standard", random.Random(122))
        assert all(type(drop["quantity"]) is int and drop["quantity"] > 0 for drop in drops)


def test_real_loot_tables_accept_positive_integer_or_dice_quantities() -> None:
    path = Path(__file__).resolve().parents[4] / "content" / "loot_tables.json"
    assert_rollable_tables(json.loads(path.read_text()))


def test_legacy_loot_table_keeps_seeded_rng_sequence() -> None:
    rng = random.Random(122)
    path = Path(__file__).resolve().parents[4] / "content" / "loot_tables.json"
    tables = {table["id"]: table for table in json.loads(path.read_text())}
    drops = derive_role_loot(tables["loot_hollow_rend"], "standard", rng)
    assert drops == [{"item_id": "rend_shard", "quantity": 1}]
    assert rng.random() == 0.3022981875355706


def test_hollowed_knight_seeded_roll() -> None:
    path = Path(__file__).resolve().parents[4] / "content" / "loot_tables.json"
    tables = {table["id"]: table for table in json.loads(path.read_text())}
    assert derive_role_loot(tables["loot_hollowed_knight"], "standard", random.Random(4)) == [
        {"item_id": "wrack_core", "quantity": 1},
        {"item_id": "hollow_ward_armor", "quantity": 1},
    ]


def test_requirements_remain_data_during_loot_roll() -> None:
    table = {
        "drops": [
            {
                "item_id": "residue",
                "chance": 1.0,
                "quantity": 1,
                "requires": [{"skill": "crafting", "tier": "expert"}],
            }
        ]
    }
    assert derive_role_loot(table, "standard", FakeRng()) == [{"item_id": "residue", "quantity": 1}]


def test_party_reward_bonus_constant() -> None:
    # The per-extra-member reward bonus is a single tunable constant (customer decision:
    # BONUS=0.5 -> a 2-PC party earns 1.5x the base). Shared by currency AND combat XP
    # (decision 91967897c88c), so grouping never pays differently for coin than progression.
    assert PARTY_REWARD_BONUS == 0.5


@pytest.mark.parametrize(
    "party_size,multiplier",
    [(1, 1.0), (2, 1.5), (3, 2.0), (4, 2.5)],
)
def test_party_reward_multiplier(party_size: int, multiplier: float) -> None:
    assert party_reward_multiplier(party_size) == multiplier


def test_party_reward_multiplier_rejects_empty_party() -> None:
    # A party must have at least one member; a zero/negative size is a caller error, not a
    # silent 0.5x nerf.
    with pytest.raises(ValueError, match="party_size"):
        party_reward_multiplier(0)


def test_hollow_wrack_currency_contract():
    class Fixed(random.Random):
        def __init__(self, chance):
            self.chance = chance

        def random(self):
            return self.chance

        def randint(self, low, high):
            return 3

    for chance, standard, boss in ((0.149, 18, 76), (0.15, 0, 40)):
        assert calculate_currency_drop("hollow_wrack", 3, "standard", Fixed(chance)) == standard
        assert calculate_currency_drop("hollow_wrack", 3, "boss", Fixed(chance)) == boss
        assert calculate_currency_drop("hollow_wrack", 3, "minion", Fixed(chance)) == 0
    with pytest.raises(ValueError, match="Unknown creature category"):
        calculate_currency_drop("hollow_bogus", 3, "standard", Fixed(0))
