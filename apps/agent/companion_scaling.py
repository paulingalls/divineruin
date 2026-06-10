"""Companion stat scaling — pure level-scaling math (Phase 6 / M6.4, story-002).

Mirrors the archetypes.py (catalog) / hp_scaling.py (math) split: companion_profiles.py owns
the DB-loaded catalog; this module owns the pure function that scales a companion's combat
line to the player's level. Zero IO, zero async.

scale_companion_stats_to_player_level takes the player's already-computed max HP (from
hp_scaling.calculate_max_hp) so it stays a pure function of content + level — no coupling to
the player's archetype/CON. The combat layer (story-004) computes player_max_hp and passes it.
"""

import math
from dataclasses import dataclass

from companion_profiles import Companion


@dataclass(frozen=True)
class ScaledCompanionStats:
    level: int
    hp: int
    ac: int
    attributes: dict[str, int]


def scale_companion_stats_to_player_level(
    profile: Companion, player_max_hp: int, player_level: int
) -> ScaledCompanionStats:
    """Scale a companion's combat stats to the player's level (spec L645-664).

    HP = floor(player_max_hp * hp_factor) — the companion tracks a fraction of the player's
    survivability (0.75 for Kael/Lira/Tam, 0.50 for the fragile Sable). AC is the highest
    ac_threshold whose min_level <= player_level. Attributes are the base line plus every
    attribute_scaling bump whose level <= player_level.
    """
    rules = profile.scaling_rules
    hp = math.floor(player_max_hp * rules.hp_factor)
    # Select the threshold for the player's level band (highest min_level <= player_level),
    # not the largest ac value — AC need not be monotonic in min_level (a future companion
    # could step AC *down*), and a data typo must not silently pick the wrong band.
    eligible = [t for t in rules.ac_thresholds if t.min_level <= player_level]
    ac = max(eligible, key=lambda t: t.min_level, default=rules.ac_thresholds[0]).ac
    attributes = dict(profile.base_attributes)
    for step in rules.attribute_scaling:
        if step.level <= player_level:
            attributes[step.attribute] += step.amount
    return ScaledCompanionStats(level=player_level, hp=hp, ac=ac, attributes=attributes)
