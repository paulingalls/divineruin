"""HP scaling — archetype-based HP formula. Zero IO, zero async."""

from dataclasses import dataclass
from typing import Literal

HPCategory = Literal["martial", "primal_divine", "arcane_shadow"]


@dataclass(frozen=True)
class HPConfig:
    base: int
    growth: int
    category: HPCategory


ARCHETYPE_HP_CONFIG: dict[str, HPConfig] = {
    # Martial (12 base, 5 growth)
    "warrior": HPConfig(12, 5, "martial"),
    "guardian": HPConfig(12, 5, "martial"),
    "skirmisher": HPConfig(12, 5, "martial"),
    # Primal / Divine / Marshal (10 base, 4 growth)
    "druid": HPConfig(10, 4, "primal_divine"),
    "beastcaller": HPConfig(10, 4, "primal_divine"),
    "warden": HPConfig(10, 4, "primal_divine"),
    "cleric": HPConfig(10, 4, "primal_divine"),
    "paladin": HPConfig(10, 4, "primal_divine"),
    "oracle": HPConfig(10, 4, "primal_divine"),
    "marshal": HPConfig(10, 4, "primal_divine"),
    # Arcane / Shadow / Support (8 base, 3 growth)
    "mage": HPConfig(8, 3, "arcane_shadow"),
    "artificer": HPConfig(8, 3, "arcane_shadow"),
    "seeker": HPConfig(8, 3, "arcane_shadow"),
    "rogue": HPConfig(8, 3, "arcane_shadow"),
    "spy": HPConfig(8, 3, "arcane_shadow"),
    "whisper": HPConfig(8, 3, "arcane_shadow"),
    "bard": HPConfig(8, 3, "arcane_shadow"),
    "diplomat": HPConfig(8, 3, "arcane_shadow"),
}


def calculate_hp(level: int, base_hp: int, growth: int, con_mod: int) -> int:
    """Calculate HP for a given level, base HP, growth rate, and CON modifier.

    Level 1: base_hp + con_mod
    Level 2+: base_hp + con_mod + (level - 1) * (growth + con_mod // 2)
    Always returns at least 1.
    """
    if level == 1:
        return max(1, base_hp + con_mod)
    return max(1, base_hp + con_mod + (level - 1) * (growth + con_mod // 2))


def calculate_max_hp(archetype: str, level: int, con_mod: int) -> int:
    """Look up archetype config and calculate max HP."""
    if archetype not in ARCHETYPE_HP_CONFIG:
        raise ValueError(f"Unknown archetype: {archetype!r}")
    cfg = ARCHETYPE_HP_CONFIG[archetype]
    return calculate_hp(level, cfg.base, cfg.growth, con_mod)
