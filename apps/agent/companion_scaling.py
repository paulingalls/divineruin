"""Companion stat scaling — pure level-scaling math (Phase 6 / M6.4, story-002).

Mirrors the archetypes.py (catalog) / hp_scaling.py (math) split: companion_profiles.py owns
the DB-loaded catalog; this module owns the pure function that scales a companion's combat
line to the player's level. Zero IO, zero async.

scale_companion_stats_to_player_level takes the player's already-computed max HP (from
hp_scaling.calculate_max_hp) so it stays a pure function of content + level — no coupling to
the player's archetype/CON. The combat layer (story-004) computes player_max_hp and passes it.
"""

import math
import re
from dataclasses import dataclass

from companion_profiles import Companion

# A dice term ("1d8", "2d6") or a flat int ("3"). Narrative damage strings also carry
# attribute/prof tokens (STR/DEX/INT/prof) that the combat resolver supplies itself from the
# attacker's attributes — those are dropped before dice_roll ever sees the notation.
_DICE_TERM = re.compile(r"^\d*d?\d+$")

# Maps a hit-expression attribute abbreviation to the full attribute key the resolver indexes
# (player_data["attributes"]). The hit field is the SSOT for a companion attack's governing stat.
_HIT_ATTR = {
    "STR": "strength",
    "DEX": "dexterity",
    "CON": "constitution",
    "INT": "intelligence",
    "WIS": "wisdom",
    "CHA": "charisma",
}


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


def companion_attacks_to_action_pool(profile: Companion) -> list[dict]:
    """Translate a companion's NARRATIVE attacks into the MECHANICAL action dicts combat consumes.

    content/companions.json stores attacks human-readably (damage "1d8+STR", hit "STR+prof",
    type "melee"/"ranged"). The deterministic resolver (check_resolution.resolve_attack) instead
    expects plain dice notation and supplies the attribute/proficiency bonus itself from the
    attacker's attributes. This builds the {name, damage, damage_type, properties,
    governing_attribute[, ranged]} dicts the resolver + combat_turn.py consume.

    Attacks ONLY — actives/reactions/passives are non-damaging narrative abilities with no
    mechanical resolver; the DM narrates those from the profile. `governing_attribute` (derived
    from the attack's hit field, e.g. "INT+prof" -> "intelligence") drives the resolver's hit
    stat per-attack (story-008), so Lira's INT bolt and Tam's DEX finesse melee resolve correctly.
    `ranged: True` is still emitted for ranged attacks (range/reach narration) but no longer
    determines the hit stat.
    """
    pool: list[dict] = []
    for attack in profile.attacks:
        ctx = f"{profile.id}.{attack.name}"
        action: dict = {
            "name": attack.name,
            "damage": _strip_to_dice_notation(attack.damage, ctx),
            "damage_type": attack.damage_type,
            "properties": [],
            "governing_attribute": _hit_to_governing_attribute(attack.hit, ctx),
        }
        if attack.type == "ranged":
            action["ranged"] = True
        pool.append(action)
    return pool


def _strip_to_dice_notation(damage: str, ctx: str) -> str:
    """Keep only the dice/flat-int terms of a narrative damage string, dropping attribute/prof
    tokens ("1d8+STR" -> "1d8", "1d6+2+DEX" -> "1d6+2"). Fail loud if nothing survives — dice_roll
    cannot parse an empty or attribute-only expression."""
    kept = []
    for term in damage.split("+"):
        term = term.strip()
        if _DICE_TERM.match(term):
            kept.append(term)
    if not kept:
        raise ValueError(f"{ctx} damage {damage!r} has no dice/int term after stripping modifiers")
    return "+".join(kept)


def _hit_to_governing_attribute(hit: str, ctx: str) -> str:
    """Extract the governing attribute from a narrative hit expression ("INT+prof" ->
    "intelligence", "DEX+prof" -> "dexterity"). Fail loud (consistent with _strip_to_dice_notation)
    if no recognized attribute token is present — the resolver needs a real attribute to index."""
    for term in hit.replace("+", " ").split():
        full = _HIT_ATTR.get(term.strip().upper())
        if full:
            return full
    raise ValueError(f"{ctx} hit {hit!r} has no recognized attribute token")
