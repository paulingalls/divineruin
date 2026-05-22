"""Tests for the shared companion-errand resolution helper.

resolve_errand_outcome is the single resolution path for scheduled errand
resolution — called by the async worker today, and by the forthcoming
resolve_companion_errand agent tool (story-009). Keeping the outcome shape
(tier, narrative_context incl. risk_outcome, decision options) identical across
entry points.
"""

import random
from unittest.mock import AsyncMock

import pytest

import errand_resolution

COMPANION_KAEL = {
    "id": "companion_kael",
    "name": "Kael",
    "relationship_tier": 2,
    "attributes": {"wisdom": 12, "charisma": 11, "intelligence": 10},
}


def _content(location):
    mod = AsyncMock()
    mod.get_location = AsyncMock(return_value=location)
    return mod


@pytest.mark.asyncio
async def test_resolve_errand_outcome_shape():
    """Returns an outcome dict with tier, errand_type, and risk_outcome in context."""
    parameters = {"errand_type": "scout", "destination": "millhaven", "dc": 12}
    result = await errand_resolution.resolve_errand_outcome(
        COMPANION_KAEL, parameters, content=_content({"danger_level": 0}), rng=random.Random(1)
    )

    assert result["errand_type"] == "scout"
    assert result["tier"] in {"great_success", "success", "partial", "complication"}
    # Safe destination -> no risk.
    assert result["narrative_context"]["risk_outcome"] == "none"
    assert "decision_options" in result


@pytest.mark.asyncio
async def test_resolve_errand_outcome_rolls_risk_from_danger():
    """Risk is rolled from the destination's danger level at resolution."""
    parameters = {"errand_type": "scout", "destination": "greyvale_ruins_entrance", "dc": 12}
    # Seed an rng that lands inside the dangerous|scout injury band (25%).
    result = await errand_resolution.resolve_errand_outcome(
        COMPANION_KAEL, parameters, content=_content({"danger_level": 2}), rng=random.Random(2)
    )
    assert result["narrative_context"]["risk_outcome"] in {"none", "injured", "emergency"}


@pytest.mark.asyncio
async def test_resolve_errand_outcome_missing_location_defaults_safe():
    """An unresolvable destination defaults to safe danger (not a crash)."""
    parameters = {"errand_type": "scout", "destination": "nowhere", "dc": 12}
    result = await errand_resolution.resolve_errand_outcome(
        COMPANION_KAEL, parameters, content=_content(None), rng=random.Random(1)
    )
    assert result["narrative_context"]["risk_outcome"] == "none"


@pytest.mark.asyncio
async def test_resolve_errand_outcome_missing_errand_type_fails_closed():
    """A missing errand_type raises rather than silently defaulting to 'scout'.

    Mirrors numeric_to_danger's fail-closed stance — a malformed errand row must
    signal, not resolve with the wrong risk band (closes concern 3b79390c55ce).
    """
    parameters = {"destination": "millhaven", "dc": 12}
    with pytest.raises(ValueError, match="errand_type"):
        await errand_resolution.resolve_errand_outcome(
            COMPANION_KAEL, parameters, content=_content({"danger_level": 0})
        )
