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


_STARTER_ZONE_FALLBACK = "accord_market_square"


def resolve_resurrection_anchor(
    death_location: str,
    locations: dict[str, dict],
    player: dict,
    *,
    combat_cleared: bool,
) -> str:
    """Pick the resurrection anchor by the spec's 4-tier hierarchy (§Resurrection Location).

    1. Cleared battlefield: the death site, if combat is over AND the area is no longer hostile
       (danger_level <= 1).
    2. Nearest allied camp/settlement: a same-region location with a settlement_tier. No map
       coordinates exist, so "nearest" = same region, preferring safer (lower danger_level) then a
       stable id sort.
    3. Last-rested settlement: player.last_rested_settlement_id. NOTE forward-seam — no rest tool
       writes this yet (apply_long_rest has no production caller), so tier 3 is dormant at runtime
       and the resolver falls through to tier 4 until a rest caller ships.
    4. Starter zone: a location tagged "starting_area" (fallback accord_market_square).
    """
    death = locations.get(death_location, {})
    if combat_cleared and death.get("danger_level", 99) <= 1:
        return death_location

    region = death.get("region")
    settlements = [
        loc_id for loc_id, loc in locations.items() if loc.get("settlement_tier") and loc.get("region") == region
    ]
    if settlements:
        return min(settlements, key=lambda i: (locations[i].get("danger_level", 99), i))

    last_rested = player.get("last_rested_settlement_id")
    if last_rested and last_rested in locations:
        return last_rested

    starter = next((i for i, loc in locations.items() if "starting_area" in loc.get("tags", [])), None)
    return starter or _STARTER_ZONE_FALLBACK


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
