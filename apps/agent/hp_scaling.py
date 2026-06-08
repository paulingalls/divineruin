"""HP scaling — archetype-based HP formula. Zero IO, zero async.

HP base/growth per archetype now live in the chassis SSOT (content/archetypes.json,
loaded via archetypes.get_archetype_chassis) — this module owns only the math.
"""

from archetypes import get_archetype_chassis


def calculate_hp(level: int, base_hp: int, growth: int, con_mod: int) -> int:
    """Calculate HP for a given level, base HP, growth rate, and CON modifier.

    Level 1: base_hp + con_mod
    Level 2+: base_hp + con_mod + (level - 1) * (growth + (con_mod + 1) // 2)

    CON contributes at half rate per level (round half up) so CON +1 gives
    +1/level instead of the dead zone that floor division produces.
    Always returns at least 1.
    """
    if level == 1:
        return max(1, base_hp + con_mod)
    return max(1, base_hp + con_mod + (level - 1) * (growth + (con_mod + 1) // 2))


def calculate_max_hp(archetype: str, level: int, con_mod: int) -> int:
    """Look up the archetype chassis and calculate max HP."""
    chassis = get_archetype_chassis(archetype)
    return calculate_hp(level, chassis.hp_base, chassis.hp_growth, con_mod)
