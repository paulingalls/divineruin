"""Pure Hollow aura composition and individually warded death generation."""

import combat_spatial
import veil_ward


def amount(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label}: expected nonnegative integer")
    return value


def location_bonus(level):
    amount(level, "location corruption")
    if level not in (0, 1, 2, 3):
        raise ValueError("unsupported location corruption")
    return (0, 1, 2, 2)[level]


def apply_corruption_aura(generated, focus_cost, location, caster_position, auras):
    amount(generated, "generation")
    amount(focus_cost, "Focus cost")
    bonus = location_bonus(location)
    inside = False
    for center, radius in auras:
        amount(radius, "corruption aura")
        inside |= combat_spatial.inside(caster_position, center, radius)
    return generated + max(bonus, int(inside)) if focus_cost > 0 else generated


def resolve_resonance_on_death(value, ward_active):
    amount(value, "death Resonance")
    return veil_ward.halve_generation(value) if ward_active else value
