"""Pure-logic tests for the role loot & currency overlay (M4.7, story-002). No DB, no RNG luck:
a FakeRng injects exact dice/chance values so every assertion is deterministic."""

import random

import pytest

from encounter_loot import (
    _BOSS_CURRENCY_BONUS,
    PARTY_REWARD_BONUS,
    calculate_currency_drop,
    derive_role_loot,
    party_reward_multiplier,
    tier_for_level,
)


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


# --- tier derivation ---


@pytest.mark.parametrize(
    "level,tier",
    [(1, 1), (2, 1), (3, 2), (5, 2), (6, 3), (9, 3), (10, 4), (15, 4)],
)
def test_tier_for_level_boundaries(level: int, tier: int) -> None:
    assert tier_for_level(level) == tier


# --- currency: role gates ---


def test_minion_drops_no_currency_d79() -> None:
    # D79: a Minion never drops coin, even a humanoid that would otherwise always carry it.
    assert calculate_currency_drop("humanoid", 4, "minion", FakeRng(die=6)) == 0


@pytest.mark.parametrize("category", ["beast", "hollow_drift", "construct", "named"])
@pytest.mark.parametrize("role", ["standard", "elite", "boss"])
def test_no_currency_categories_drop_nothing(category: str, role: str) -> None:
    # Animals/machines/drifts/named carry no coin regardless of role — a beast Boss included.
    assert calculate_currency_drop(category, 3, role, FakeRng(die=6)) == 0


# --- currency: humanoid (always carries) by role ---


def test_humanoid_standard_is_tier_times_d6() -> None:
    # Standard base = tier x 1d6. die=4, tier=2 -> 8.
    assert calculate_currency_drop("humanoid", 2, "standard", FakeRng(die=4)) == 8


def test_humanoid_elite_is_ceil_1_5x_base() -> None:
    # base = 2 x 5 = 10; elite = ceil(10 x 1.5) = 15.
    assert calculate_currency_drop("humanoid", 2, "elite", FakeRng(die=5)) == 15


def test_humanoid_elite_rounds_up() -> None:
    # base = 1 x 3 = 3; elite = ceil(4.5) = 5.
    assert calculate_currency_drop("humanoid", 1, "elite", FakeRng(die=3)) == 5


def test_humanoid_boss_is_double_base_plus_tier_bonus() -> None:
    # base = 3 x 4 = 12; boss = 12x2 + bonus[T3]=40 -> 64.
    expected = 24 + _BOSS_CURRENCY_BONUS[3]
    assert calculate_currency_drop("humanoid", 3, "boss", FakeRng(die=4)) == expected


# --- currency: chance-gated categories ---


def test_hollow_rend_hits_on_low_chance_roll() -> None:
    # 15% gate: random()=0.10 < 0.15 -> carries; base = tier x 2d6 = 2 x (3+3) = 12.
    assert calculate_currency_drop("hollow_rend", 2, "standard", FakeRng(die=3, chance=0.10)) == 12


def test_hollow_rend_misses_on_high_chance_roll() -> None:
    # random()=0.50 >= 0.15 -> no coin.
    assert calculate_currency_drop("hollow_rend", 2, "standard", FakeRng(die=3, chance=0.50)) == 0


def test_undead_hits_on_low_chance_roll() -> None:
    # 25% gate: random()=0.20 < 0.25 -> carries; base = tier x 1d4 = 3 x 2 = 6.
    assert calculate_currency_drop("undead", 3, "standard", FakeRng(die=2, chance=0.20)) == 6


def test_undead_misses_on_high_chance_roll() -> None:
    assert calculate_currency_drop("undead", 3, "standard", FakeRng(die=2, chance=0.40)) == 0


def test_boss_still_drops_guaranteed_bonus_when_base_roll_empty() -> None:
    # A hollow_rend Boss that fails its 15% gate (base 0) still drops the guaranteed tier bonus:
    # 0x2 + bonus[T4]=100.
    got = calculate_currency_drop("hollow_rend", 4, "boss", FakeRng(die=6, chance=0.99))
    assert got == _BOSS_CURRENCY_BONUS[4]


# --- currency: validation (fail-loud) ---


def test_unknown_category_raises() -> None:
    with pytest.raises(ValueError, match="Unknown creature category"):
        calculate_currency_drop("dragon", 1, "standard", FakeRng())


def test_unknown_role_raises_for_currency() -> None:
    with pytest.raises(ValueError, match="Unknown encounter role"):
        calculate_currency_drop("humanoid", 1, "champion", FakeRng())


# --- loot: role scaling ---


def _table() -> dict:
    return {
        "id": "t",
        "drops": [
            {"item_id": "hide", "chance": 0.5, "quantity": 2},
            {"item_id": "bone", "chance": 0.2, "quantity": 1},
        ],
    }


def test_standard_loot_drops_entries_whose_chance_passes() -> None:
    # chance=0.0 always passes (< any chance>0); quantities unchanged for Standard.
    drops = derive_role_loot(_table(), "standard", FakeRng(chance=0.0))
    assert drops == [{"item_id": "hide", "quantity": 2}, {"item_id": "bone", "quantity": 1}]


def test_standard_loot_omits_entries_whose_chance_fails() -> None:
    # chance=0.6 fails the 0.5 entry and the 0.2 entry -> nothing drops.
    assert derive_role_loot(_table(), "standard", FakeRng(chance=0.6)) == []


def test_minion_loot_halves_chance_and_drops_quantity() -> None:
    # Minion: hide chance 0.5x0.5=0.25, qty 2-1=1; bone chance 0.2x0.5=0.1, qty 1-1 floored to 1.
    # random()=0.05 passes both modified chances.
    drops = derive_role_loot(_table(), "minion", FakeRng(chance=0.05))
    assert drops == [{"item_id": "hide", "quantity": 1}, {"item_id": "bone", "quantity": 1}]


def test_minion_loot_chance_has_5pct_floor() -> None:
    # An entry at chance 0.08 -> minion 0.04 -> floored to 0.05. random()=0.045 < 0.05 -> drops.
    table = {"drops": [{"item_id": "x", "chance": 0.08, "quantity": 1}]}
    assert derive_role_loot(table, "minion", FakeRng(chance=0.045)) == [{"item_id": "x", "quantity": 1}]


def test_elite_loot_adds_chance_and_quantity() -> None:
    # Elite: hide chance 0.5+0.25=0.75 qty 3; bone 0.2+0.25=0.45 qty 2. random()=0.5 passes hide,
    # fails bone.
    drops = derive_role_loot(_table(), "elite", FakeRng(chance=0.5))
    assert drops == [{"item_id": "hide", "quantity": 3}]


def test_elite_loot_chance_caps_at_one() -> None:
    table = {"drops": [{"item_id": "x", "chance": 0.9, "quantity": 1}]}
    # 0.9+0.25=1.15 capped to 1.0; random()=0.99 < 1.0 -> drops, qty 1+1=2.
    assert derive_role_loot(table, "elite", FakeRng(chance=0.99)) == [{"item_id": "x", "quantity": 2}]


def test_boss_loot_is_guaranteed_and_boosts_quantity() -> None:
    # Boss: all chances become 1.0 (guaranteed even at random()=0.99); qty ceil(x1.5):
    # hide ceil(3)=3, bone ceil(1.5)=2.
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


# --- party reward multiplier (M18 story-003): reward grouping without N x farming ---


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
    # multiplier(N) = 1 + BONUS*(N-1). Solo (N=1) is exactly 1.0 so a single-member party's
    # reward stays byte-identical to the pre-M18 single-roll behavior.
    assert party_reward_multiplier(party_size) == multiplier


def test_party_reward_multiplier_solo_is_exactly_one() -> None:
    # Guard the byte-identical-solo invariant explicitly: no float drift at N=1.
    assert party_reward_multiplier(1) == 1.0


def test_party_reward_multiplier_rejects_empty_party() -> None:
    # A party must have at least one member; a zero/negative size is a caller error, not a
    # silent 0.5x nerf.
    with pytest.raises(ValueError, match="party_size"):
        party_reward_multiplier(0)
