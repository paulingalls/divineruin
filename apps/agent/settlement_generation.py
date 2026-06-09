"""Settlement NPC generation — pure rules engine (Phase 6 / M6.2, story-003).

Turns a settlement (tier + personality) into a concrete NPC population. Two pure
functions, no LLM, no DB:
  - generate_settlement_npcs(tier, personality, *, rng) -> {role_id: count}: how many of
    each role a settlement has, sampling each role's [min, max] range (after personality
    frequency modifiers) inclusively.
  - instantiate_npc_from_template(role, tier, personality, overrides) -> stat-block dict:
    create_npc_from_archetype(role, overrides) with tier+personality modifiers layered on
    (disposition shift, price multiplier, inventory richness).

Reads the catalogs via settlement_templates.get_settlement_tier / get_settlement_personality
and role_archetypes.create_npc_from_archetype / DISPOSITIONS. keldaran_hold has no tier row
(it is City-scale per the spec); generate normalizes it to city here, while
get_settlement_tier itself keeps its fail-loud contract for unknown sizes.
"""

import random

from role_archetypes import DISPOSITIONS, create_npc_from_archetype
from settlement_templates import get_settlement_personality, get_settlement_tier

# keldaran_hold is City-scale (spec lists Keldaran holds as City examples). Normalize to
# city role_counts at the generation layer; get_settlement_tier stays fail-loud elsewhere.
_TIER_ALIASES = {"keldaran_hold": "city"}


def _effective_ranges(tier: str, personality: str) -> dict[str, dict[str, int]]:
    """Tier role_counts with the personality's role_frequency_modifiers folded in.

    A +N modifier raises both the min and max of a role's range by N (min floored at 0). A
    positive modifier for a role ABSENT from the tier INTRODUCES it as {min: 0, max: N}, so
    e.g. a Corrupt hamlet can hide a fence / black-market dealer (0-1). A negative modifier
    for an absent role is a no-op. Raises ValueError for an unknown tier or personality.
    """
    tier_row = get_settlement_tier(_TIER_ALIASES.get(tier, tier))
    freq_mods = get_settlement_personality(personality)["role_frequency_modifiers"]
    ranges: dict[str, dict[str, int]] = {}
    for role_id, rng in tier_row["role_counts"].items():
        delta = freq_mods.get(role_id, 0)
        ranges[role_id] = {"min": max(0, rng["min"] + delta), "max": max(0, rng["max"] + delta)}
    for role_id, delta in freq_mods.items():
        if role_id not in ranges and delta > 0:
            ranges[role_id] = {"min": 0, "max": delta}
    return ranges


def generate_settlement_npcs(tier: str, personality: str, *, rng: random.Random | None = None) -> dict[str, int]:
    """Return a concrete {role_id: count} population for one settlement.

    Normalizes keldaran_hold->city, folds the personality's frequency modifiers into each
    tier range (see _effective_ranges), then samples each range inclusively. `rng` defaults
    to a fresh random.Random() (settlements vary in prod); tests inject a seeded Random for
    determinism. Raises ValueError for an unknown tier or personality.
    """
    rng = rng or random.Random()
    ranges = _effective_ranges(tier, personality)
    return {role_id: rng.randint(r["min"], r["max"]) for role_id, r in ranges.items()}


def _shift_disposition(base: str, delta: int) -> str:
    """Move `base` along the DISPOSITIONS ladder by `delta`, clamped to its ends.

    A positive delta is friendlier, negative more hostile; the result never falls off the
    5-tier ladder (so it stays a valid disposition). Raises ValueError if `base` isn't a
    canonical disposition.
    """
    idx = DISPOSITIONS.index(base)
    return DISPOSITIONS[max(0, min(len(DISPOSITIONS) - 1, idx + delta))]


def instantiate_npc_from_template(role: str, tier: str, personality: str, overrides: dict | None = None) -> dict:
    """Build one settlement NPC: create_npc_from_archetype(role, overrides) with the
    settlement's personality modifiers filling in any field the caller did not pin.

    Overrides WIN: each personality modifier applies only when its target key is NOT in
    `overrides`, so an explicit caller value is final (e.g. a named NPC forced hostile in any
    settlement). The three modifier targets are:
      - default_disposition — shifted along DISPOSITIONS by the personality's per-role
        disposition_modifier, clamped to the ladder ends.
      - price_modifier — multiplied by the personality's price_modifier (both are ratios
        around 1.0).
      - inventory_richness — set from the personality's inventory_modifier. This is a NEW
        scalar field distinct from the archetype's `inventory_pool` (a pool-id string), and
        is a forward-wired Phase-9 economy field with no live reader yet.

    `tier` carries no per-NPC stat modifier in the M6.2 data model — settlement tier only
    drives role COUNTS (generate_settlement_npcs) — so it is used here solely to fail loud
    (with keldaran_hold->city normalization) on a bogus tier, anchoring the NPC to a real
    settlement size. Raises ValueError for an unknown role, tier, or personality.
    """
    overrides = overrides or {}
    get_settlement_tier(_TIER_ALIASES.get(tier, tier))  # fail-loud tier guard
    pers = get_settlement_personality(personality)
    npc = create_npc_from_archetype(role, overrides)
    if "default_disposition" not in overrides:
        disp_delta = pers["disposition_modifiers"].get(role, 0)
        npc["default_disposition"] = _shift_disposition(npc["default_disposition"], disp_delta)
    elif npc["default_disposition"] not in DISPOSITIONS:
        # Overrides win, but a disposition must still be on the canonical ladder — an
        # override skips _shift_disposition's validation, so guard it here (fail loud).
        raise ValueError(f"override default_disposition {npc['default_disposition']!r} not in {DISPOSITIONS}")
    if "price_modifier" not in overrides:
        npc["price_modifier"] = npc["price_modifier"] * pers["price_modifier"]
    if "inventory_richness" not in overrides:
        npc["inventory_richness"] = pers["inventory_modifier"]
    return npc
