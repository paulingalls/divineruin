"""Encounter stance resolver (Phase 6 / M6.2, story-005).

A pure, deterministic mechanic (golden rule: rules engine = pure functions, no LLM): an
encounter template may carry a `stance_gate` making it allied or hostile based on the
player's reputation with a faction. The Ashmark Patrol (content/encounter_templates.json)
uses it — allied when the player's Thornwatch reputation is at or above `friendly`, hostile
below.

No runtime caller wires this into combat yet: encounter spawning would need a
get_player_faction_reputation query that isn't shipped. This module ships the deterministic
mechanic + its contract; the combat_init integration is future work.
"""


def resolve_encounter_stance(stance_gate: dict, reputation_value: int, reputation_tiers: dict) -> str:
    """Return an encounter's stance ("allied" | "hostile") from a faction reputation.

    `stance_gate` is the encounter's gate ({"faction": ..., "allied_at_or_above": <tier>}),
    `reputation_value` the player's reputation with that faction, and `reputation_tiers` the
    faction's tier ladder (from content/factions.json). Allied iff `reputation_value` is at
    or above the threshold of the gate's `allied_at_or_above` tier; hostile otherwise. The
    threshold is read from `reputation_tiers` so there is no duplicated magic number. Fails
    loud on a malformed gate or a tier the faction doesn't define.
    """
    if "allied_at_or_above" not in stance_gate:
        raise ValueError("stance_gate missing 'allied_at_or_above'")
    tier = stance_gate["allied_at_or_above"]
    if tier not in reputation_tiers:
        raise ValueError(f"stance_gate allied_at_or_above {tier!r} not in reputation_tiers")
    if "threshold" not in reputation_tiers[tier]:
        raise ValueError(f"reputation_tiers[{tier!r}] missing 'threshold'")
    threshold = reputation_tiers[tier]["threshold"]
    return "allied" if reputation_value >= threshold else "hostile"
