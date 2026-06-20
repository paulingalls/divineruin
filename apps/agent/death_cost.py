"""M4.4 death cost engine (story-001) — pure tier mapping.

Death always returns the character; the only question is the cost, which escalates
with a permanent 1-based death count that never resets (see
docs/game_mechanics/game_mechanics_combat.md §The Cost Engine). This module is the
deterministic mechanical headline of that table: tier + the attribute/maxHP penalty.

It is intentionally free of character and DB coupling. ``attribute_target`` names
*which* attribute the penalty hits as a selector ("lowest"/"primary"/"highest"); the
concrete attribute is chosen at resurrection apply-time (story-003), which has the
character's real attributes. The weighted/DM-influenced alternate costs from the spec
(memory-vs-trinket, Mortaen's Debt, item loss) are also an apply-time concern.
Persistence of the resulting cost ledger lives in db_mutations_death.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DeathCost:
    """The mechanical cost of one death, keyed off the character's running death count."""

    tier: str  # "gentle" | "moderate" | "severe" | "devastating"
    death_count: int  # 1-based: this death's number
    attribute_penalty: int  # 0 | 1 | 2 — points off an attribute
    attribute_target: str  # "none" | "lowest" | "primary" | "highest"
    maxhp_penalty_per_level: int  # 0 | 1 — the death-7+ retroactive fraying
    maxhp_penalty_total: int  # maxhp_penalty_per_level * level


def determine_death_cost(death_count: int, level: int) -> DeathCost:
    """Return the cost tier + penalties for a death at ``death_count`` (1-based) and ``level``.

    Tiers by death count: 1=gentle, 2=moderate, 3-4=severe, 5+=devastating. From death 7,
    a retroactive -1 maxHP per level is added on top of the devastating tier. Fails loud on a
    non-positive count or level — a death is always the 1st or later, a character is always level 1+.
    """
    if death_count < 1:
        raise ValueError(f"death_count must be >= 1 (1-based), got {death_count}")
    if level < 1:
        raise ValueError(f"level must be >= 1, got {level}")

    if death_count == 1:
        tier, attribute_penalty, attribute_target = "gentle", 0, "none"
    elif death_count == 2:
        tier, attribute_penalty, attribute_target = "moderate", 1, "lowest"
    elif death_count <= 4:
        tier, attribute_penalty, attribute_target = "severe", 1, "primary"
    else:
        tier, attribute_penalty, attribute_target = "devastating", 2, "highest"

    maxhp_penalty_per_level = 1 if death_count >= 7 else 0

    return DeathCost(
        tier=tier,
        death_count=death_count,
        attribute_penalty=attribute_penalty,
        attribute_target=attribute_target,
        maxhp_penalty_per_level=maxhp_penalty_per_level,
        maxhp_penalty_total=maxhp_penalty_per_level * level,
    )
