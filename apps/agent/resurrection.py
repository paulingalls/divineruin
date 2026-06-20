"""M4.4 resurrection (story-003) — core return-from-death loop.

Death always returns the character (spec §Mortaen's Domain); the cost escalates with the permanent
death count (story-001's death_cost). This module turns a DeathCost into concrete persistence deltas
(apply_death_cost), resolves the nearest safe anchor (resolve_resurrection_anchor, 4-tier), and
orchestrates the whole death->cost->anchor->revive flow (trigger_character_death). Pure helpers stay
free of IO; persistence lives in db_mutations_resurrection. Hollowed-death + Temporary Hollowed are
story-007.
"""

from creation_classes import CLASSES
from death_cost import DeathCost

# Canonical attribute order — also the deterministic tie-break for lowest/highest selectors.
_ATTR_ORDER = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")


def lowest_attribute(attributes: dict) -> str:
    """The attribute with the lowest score; ties break by canonical order (min keeps first seen)."""
    present = [a for a in _ATTR_ORDER if a in attributes]
    if not present:
        raise ValueError("attributes dict has no recognized attribute keys")
    return min(present, key=lambda a: attributes[a])


def highest_attribute(attributes: dict) -> str:
    """The attribute with the highest score; ties break by canonical order (max keeps first seen)."""
    present = [a for a in _ATTR_ORDER if a in attributes]
    if not present:
        raise ValueError("attributes dict has no recognized attribute keys")
    return max(present, key=lambda a: attributes[a])


def _primary_attribute(player: dict) -> str:
    """The character's class primary attribute (creation_classes), or the highest score as a
    defensible fallback when the class is missing/unknown — resurrection must not crash on it."""
    cls = CLASSES.get(player.get("class", ""))
    if cls is not None:
        return cls.primary_attribute
    return highest_attribute(player["attributes"])


def apply_death_cost(player: dict, cost: DeathCost) -> dict:
    """Resolve a DeathCost's selectors against the character into concrete persistence deltas.

    Returns {attribute, attribute_delta, maxhp_override_delta}: the attribute to penalize (or None),
    the signed attribute change, and the signed maxHP-override change (negative, accumulates). The DB
    layer (db_mutations_resurrection) applies these; keeping the resolution pure makes it unit-testable.
    """
    attrs = player["attributes"]
    target = cost.attribute_target
    if target == "none":
        attribute = None
    elif target == "lowest":
        attribute = lowest_attribute(attrs)
    elif target == "primary":
        attribute = _primary_attribute(player)
    elif target == "highest":
        attribute = highest_attribute(attrs)
    else:
        raise ValueError(f"unknown attribute_target: {target!r}")

    return {
        "attribute": attribute,
        "attribute_delta": -cost.attribute_penalty if attribute is not None else 0,
        "maxhp_override_delta": -cost.maxhp_penalty_total,
    }
