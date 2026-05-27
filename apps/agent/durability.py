"""Durability + repair rules engine (story-001, M5.4) — pure, no IO.

Durability is a deterministic mechanic (CLAUDE.md golden rule #3): the LLM decides
*when* an item takes a hit and *how* to narrate a break; this module calculates the
result. The 4 durability tiers, their max-hits, the repair-skill-tier coupling, and
the rarity-keyed repair pricing are a small closed table, so they live as code
constants (same call as the workspace-vocab SSOT decision) rather than DB-loaded
content. No accessor, no DB.

An `item_state` is a subset of the JSONB inventory item dict:
`{"type": str, "durability_tier": str, "current_hits": int}`. `durability_tier` is
catalog/template data; `current_hits` is per-instance player state stored on the
inventory item (decision durability-current-hits-storage — no new table). Every
function reads and returns plain dicts/ints and never mutates its input in place.

Spec sources: docs/game_mechanics/game_mechanics_crafting.md §Durability System
(519-540), §Repair Pricing (542-549). Conflicts resolved this story (decisions):
- durability-repair-pricing-axis: repair cost keys on item RARITY, not durability.
- durability-repair-skill-tier: fragile->untrained ... masterwork->master.
- durability-broken-penalties: weapon -2 attack / armor|shield -2 AC / tool unusable.

Consumers (later stories): combat hit emission (story-003) calls
apply_durability_damage with is_hollow_zone derived from session corruption state;
the repair flow (story-004) calls calculate_repair_cost, repair_skill_tier, and
max_hits.
"""

from rules_engine import SkillTier

# Durability tier -> hits an item absorbs before breaking (spec Durability Tiers).
DURABILITY_MAX_HITS = {"fragile": 3, "standard": 10, "reinforced": 25, "masterwork": 50}

# Durability tier -> the Crafting skill tier required to repair it (spec). Values
# are the canonical rules_engine.SkillTier vocabulary (SSOT), not free strings.
DURABILITY_REPAIR_SKILL: dict[str, SkillTier] = {
    "fragile": "untrained",
    "standard": "trained",
    "reinforced": "expert",
    "masterwork": "master",
}

# Item rarity -> repair cost in silver pieces (spec Repair Pricing, rarity axis).
# Legendary is "200+ sp or quest"; the interim flat rate is 200.
REPAIR_COST_SP = {"common": 2, "uncommon": 10, "rare": 50, "legendary": 200}

# Broken-state penalty by item type. Non-equippable types (consumables, materials)
# carry no penalty — they don't degrade in combat and have no "broken" effect.
_BROKEN_PENALTY = {
    "weapon": {"attack": -2},
    "armor": {"ac": -2},
    "shield": {"ac": -2},
    "tool": {"unusable": True},
}


def max_hits(durability_tier: str) -> int:
    """Return the max hit points for a durability tier; fail loud on unknown."""
    try:
        return DURABILITY_MAX_HITS[durability_tier]
    except KeyError:
        raise ValueError(f"unknown durability_tier {durability_tier!r}") from None


def repair_skill_tier(durability_tier: str) -> SkillTier:
    """Return the Crafting skill tier required to repair a durability tier."""
    try:
        return DURABILITY_REPAIR_SKILL[durability_tier]
    except KeyError:
        raise ValueError(f"unknown durability_tier {durability_tier!r}") from None


def calculate_repair_cost(rarity: str) -> int:
    """Return the repair cost in sp for an item rarity (spec rarity axis)."""
    try:
        return REPAIR_COST_SP[rarity]
    except KeyError:
        raise ValueError(f"unknown rarity {rarity!r}") from None


def apply_durability_damage(item_state: dict, hits: int, *, is_hollow_zone: bool) -> dict:
    """Return a copy of item_state with current_hits reduced by the hits taken.

    Hollow corruption zones double the loss (spec: "The Hollow corrodes faster").
    current_hits floors at 0 (broken). Fails loud on an unknown durability_tier or
    negative hits. Never mutates the caller's dict.
    """
    if hits < 0:
        raise ValueError(f"hits must be non-negative, got {hits}")
    if item_state["durability_tier"] not in DURABILITY_MAX_HITS:
        raise ValueError(f"unknown durability_tier {item_state['durability_tier']!r}")

    loss = hits * (2 if is_hollow_zone else 1)
    updated = dict(item_state)
    updated["current_hits"] = max(0, item_state["current_hits"] - loss)
    return updated


def check_item_condition(item_state: dict) -> dict:
    """Report whether an item is broken (0 hits) and its broken-state penalty.

    Returns {"broken": bool, "penalty": {...}}. At 0 hits the penalty is keyed on
    the item type (weapon -2 attack, armor/shield -2 AC, tool unusable); other types
    and any non-broken item carry an empty penalty.
    """
    broken = item_state["current_hits"] <= 0
    penalty = _BROKEN_PENALTY.get(item_state["type"], {}) if broken else {}
    return {"broken": broken, "penalty": penalty}
