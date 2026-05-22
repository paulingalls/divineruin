"""Shared companion-errand resolution — the single outcome path for scheduled
resolution. Currently called by the async worker; the forthcoming
resolve_companion_errand agent tool (story-009) will route through it too so
both entry points produce an identical outcome shape.

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
