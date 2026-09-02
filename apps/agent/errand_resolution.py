"""Shared companion-errand resolution — the single outcome path for both entry points,
the async worker and the resolve_companion_errand agent tool, so they produce an
identical outcome shape. companion_errand_data is the shared WHO: both callers derive
the companion from the player's archetype here rather than reading it off the player row.

Wraps the pure async_rules.resolve_companion_errand, then rolls the injury risk
from the destination's danger level (ADR 0006: risk rolls once, at resolution).
Keeping this in one place means every caller produces an identical outcome
shape (tier, narrative_context incl. risk_outcome, decision_options).
"""

from __future__ import annotations

import random
from dataclasses import asdict

import db_content_queries
import errand_risk
from async_rules import resolve_companion_errand
from companion_profiles import get_companion_profile, select_companion_for_archetype


def companion_errand_data(player: dict) -> dict:
    """Build the companion input for an errand from the player's archetype.

    Nothing has ever written a "companion" key into players.data, so both entry points
    used to hand this resolver an empty dict: every player's errand narrated as Kael
    with the resolver's default attributes, and the affinity nudge was dropped because
    the id it keys on was absent. The companion is the archetype's complement — the same
    selection rule session start hydrates — so the errand, the prompt and the
    companion_relationships row can never name three different companions.
    Raises rather than defaulting to Kael (constraint 4).

    Base attributes, unscaled: the errand check reads one attribute modifier, and
    scale_companion_stats_to_player_level exists to derive HP/AC from the player's own
    max HP, which this path has no reason to compute.
    """
    archetype_id = player.get("class")
    if not archetype_id:
        raise ValueError("cannot select an errand companion: player row has no class")
    profile = get_companion_profile(select_companion_for_archetype(archetype_id))
    return {"id": profile.id, "name": profile.name, "attributes": dict(profile.base_attributes)}


async def resolve_errand_outcome(
    companion_data: dict,
    parameters: dict,
    *,
    content=db_content_queries,
    risk=errand_risk,
    rng: random.Random | None = None,
) -> dict:
    """Resolve a companion errand into the worker/tool outcome dict.

    Fails closed on a missing errand_type (raises) rather than defaulting —
    a malformed errand must signal, not resolve with the wrong risk band.
    """
    errand_type = parameters.get("errand_type")
    if not errand_type:
        raise ValueError("companion errand parameters missing required 'errand_type'")

    outcome_dict = asdict(resolve_companion_errand(companion_data, parameters, rng))

    location = await content.get_location(parameters.get("destination", ""))
    danger = risk.numeric_to_danger(location.get("danger_level") if location else None)
    risk_outcome = risk.roll_errand_risk(errand_type, danger, companion_data.get("id", ""), rng=rng)
    outcome_dict.setdefault("narrative_context", {})["risk_outcome"] = risk_outcome

    return outcome_dict
