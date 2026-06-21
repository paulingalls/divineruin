"""Pure loot & currency overlay for the 5-role encounter system (M4.7, story-002).

A base creature's loot table plus its assigned encounter role yields the actual drops: a
throwaway Minion sheds half its loot and no coin, while a Boss drops everything it carries plus a
guaranteed currency bonus. This module is the deterministic source for *what a role does to a loot
table and a currency roll* — two pure functions that read only their arguments and a seeded RNG,
never touching IO/DB. combat_end wires them on victory; the role/category/tier all ride the
defeated enemy's CombatParticipant.

Numbers come from docs/game_mechanics/game_mechanics_encounter_roles.md — the Loot Modifier Table
(L130-136), the Currency Drop Rules (L142-159), and decisions D78 (sell < craft) / D79 (Minions
drop no currency). The role enum is the shared SSOT in encounter_roles; the loot/currency
modifiers live here because they are this story's concern, not the stat-block overlay's.

Honest scope notes:
- The Boss "bonus item from a context loot pool" (L161) is authored per-encounter location/quest
  content, not a creature-table drop — out of scope here. derive_role_loot scales the creature's
  own table; the context-pool item is a future content concern.
- Named currency is "set per creature" (bespoke) in the spec; with no per-creature authored
  currency yet, Named resolves to the category base (identity), same as Standard. When bespoke
  Named currency content lands it overrides at the content layer, not here.
"""

import math
import random

from dice import roll
from encounter_roles import EncounterRole

# Enemy creature categories (content/encounter_templates.json `category`). The currency-bearing
# ones roll coin per the Currency Drop Rules; the rest carry none ("animals don't carry coin").
_CURRENCY_CATEGORIES = frozenset({"humanoid", "hollow_rend", "undead"})
_NO_CURRENCY_CATEGORIES = frozenset({"beast", "hollow_drift", "construct", "named"})
_VALID_CATEGORIES = _CURRENCY_CATEGORIES | _NO_CURRENCY_CATEGORIES

_VALID_ROLES = frozenset(r.value for r in EncounterRole)

# Boss guaranteed currency bonus by encounter tier (silver), L152-159. Added on top of 2x base.
_BOSS_CURRENCY_BONUS = {1: 5, 2: 15, 3: 40, 4: 100}


def tier_for_level(level: int) -> int:
    """Map an enemy level to an encounter tier (1-4) for currency scaling.

    Pinned here as the single source: 1-2 -> T1, 3-5 -> T2, 6-9 -> T3, 10+ -> T4."""
    if level <= 2:
        return 1
    if level <= 5:
        return 2
    if level <= 9:
        return 3
    return 4


def _validate_category(category: str) -> None:
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"Unknown creature category {category!r}; valid categories are {sorted(_VALID_CATEGORIES)}")


def _validate_role(role: str) -> None:
    if role not in _VALID_ROLES:
        raise ValueError(f"Unknown encounter role {role!r}; valid roles are {sorted(_VALID_ROLES)}")


def _base_currency(category: str, tier: int, rng: random.Random) -> int:
    """The category's pre-role base currency roll in silver (Currency Drop Rules, L142-150).

    Humanoids always carry coin; Hollow-Rend+ (15%) and Undead (25%) sometimes do; beasts,
    drifts, constructs and named carry none. The chance gate is rolled first, then the dice, so
    the RNG consumption is deterministic for a given seed."""
    if category == "humanoid":
        return tier * roll("1d6", rng=rng).total
    if category == "hollow_rend":
        if rng.random() < 0.15:
            return tier * roll("2d6", rng=rng).total
        return 0
    if category == "undead":
        if rng.random() < 0.25:
            return tier * roll("1d4", rng=rng).total
        return 0
    return 0


def calculate_currency_drop(category: str, tier: int, role: str, rng: random.Random) -> int:
    """Silver dropped by one defeated enemy: the category base roll modified by encounter role.

    Minions drop nothing (D79). No-currency categories drop nothing regardless of role (a beast
    Boss still carries no coin). Otherwise: Standard/Named = base, Elite = ceil(1.5x base), Boss =
    2x base + the guaranteed tier bonus (so a Boss always yields its bonus even when the base roll
    or its chance gate came up empty). Pure: all randomness flows through ``rng``."""
    _validate_category(category)
    _validate_role(role)

    if role == EncounterRole.MINION:
        return 0  # D79: Minions drop no currency.
    if category not in _CURRENCY_CATEGORIES:
        return 0  # Beasts, drifts, constructs, named: no coin (boss bonus included).

    base = _base_currency(category, tier, rng)
    if role == EncounterRole.ELITE:
        return math.ceil(base * 1.5)
    if role == EncounterRole.BOSS:
        return base * 2 + _BOSS_CURRENCY_BONUS[tier]
    return base  # Standard, Named.


def _role_drop_chance(chance: float, role: str) -> float:
    """Apply the role drop-chance modifier (Loot Modifier Table, L130-136).

    Minion x0.5 (floor 5%), Elite +25% (cap 100%), Boss guaranteed (100%),
    Standard/Named as written."""
    if role == EncounterRole.MINION:
        return max(0.05, chance * 0.5)
    if role == EncounterRole.ELITE:
        return min(1.0, chance + 0.25)
    if role == EncounterRole.BOSS:
        return 1.0
    return chance  # Standard, Named.


def _role_quantity(quantity: int, role: str) -> int:
    """Apply the role quantity modifier (Loot Modifier Table, L130-136).

    Minion -1 per entry (floor 1), Elite +1 per entry, Boss +50% (round up),
    Standard/Named as written."""
    if role == EncounterRole.MINION:
        return max(1, quantity - 1)
    if role == EncounterRole.ELITE:
        return quantity + 1
    if role == EncounterRole.BOSS:
        return math.ceil(quantity * 1.5)
    return quantity  # Standard, Named.


def derive_role_loot(loot_table: dict, role: str, rng: random.Random) -> list[dict]:
    """Roll a defeated enemy's actual drops from its loot table, scaled by encounter role.

    Each table entry {item_id, chance, quantity} has its drop chance and quantity modified per the
    role (Minion sheds loot, Boss guarantees it), then the (modified) chance is rolled once. Hits
    become {item_id, quantity} dicts in the returned list — order preserved, misses omitted. Pure:
    every roll flows through ``rng``, no mutation of the input table."""
    _validate_role(role)
    drops: list[dict] = []
    for entry in loot_table.get("drops", []):
        chance = _role_drop_chance(entry["chance"], role)
        if rng.random() < chance:
            drops.append({"item_id": entry["item_id"], "quantity": _role_quantity(entry["quantity"], role)})
    return drops
