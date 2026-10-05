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
    parameters = {"errand_type": "scout", "destination": "millhaven", "dc": 12}
    result = await errand_resolution.resolve_errand_outcome(
        COMPANION_KAEL, parameters, content=_content({"danger_level": 0}), rng=random.Random(1)
    )

    assert result["errand_type"] == "scout"
    assert result["tier"] in {"great_success", "success", "partial", "complication"}
    assert result["narrative_context"]["risk_outcome"] == "none"
    assert "decision_options" in result


@pytest.mark.asyncio
async def test_resolve_errand_outcome_rolls_risk_from_danger():
    parameters = {"errand_type": "scout", "destination": "greyvale_ruins_entrance", "dc": 12}
    result = await errand_resolution.resolve_errand_outcome(
        COMPANION_KAEL, parameters, content=_content({"danger_level": 2}), rng=random.Random(2)
    )
    assert result["narrative_context"]["risk_outcome"] in {"none", "injured", "emergency"}


@pytest.mark.asyncio
async def test_resolve_errand_outcome_missing_location_defaults_safe():
    parameters = {"errand_type": "scout", "destination": "nowhere", "dc": 12}
    result = await errand_resolution.resolve_errand_outcome(
        COMPANION_KAEL, parameters, content=_content(None), rng=random.Random(1)
    )
    assert result["narrative_context"]["risk_outcome"] == "none"


@pytest.mark.asyncio
async def test_resolve_errand_outcome_missing_errand_type_fails_closed():
    """A missing errand must not fall back to the wrong scout."""
    parameters = {"destination": "millhaven", "dc": 12}
    with pytest.raises(ValueError, match="errand_type"):
        await errand_resolution.resolve_errand_outcome(
            COMPANION_KAEL, parameters, content=_content({"danger_level": 0})
        )
