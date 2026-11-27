"""Autouse fixtures for the async-worker test suite."""

from unittest.mock import AsyncMock, patch

import pytest
from worker_suite._samples import _WEAPON_QUALITY


@pytest.fixture(autouse=True)
def _stub_crafting_worker_db():
    """Keep the real crafting resolver in worker lifecycle tests that run without a database."""
    with (
        patch("crafting_resolution.get_recipe", new_callable=AsyncMock, return_value={"category": "weapon"}),
        patch("crafting_resolution.get_quality_outcomes", new_callable=AsyncMock, return_value=_WEAPON_QUALITY),
        patch(
            "crafting_resolution.get_item",
            new_callable=AsyncMock,
            return_value={"type": "weapon", "rarity": "common", "value_base": 13},
        ),
        patch(
            "crafting_resolution.get_economy_pricing", new_callable=AsyncMock, return_value={"crafted_sale_rate": 0.8}
        ),
        patch("async_worker.db_mutations.increment_crafting_skill_counter", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture(autouse=True)
def _errand_affinity_for_worker(stub_companion_errand_affinity_io):
    """Apply the narrow companion rank/affinity stub (root conftest) to every worker test.

    async_worker._resolve_one_outcome calls cached_effective_rank + apply_errand_affinity on the
    companion-errand path; these hit the DB. The stub is opt-in (no longer global autouse,
    story-007) so this dir-scoped wrapper re-applies it for the whole worker suite rather than
    duplicating the patch block."""
    yield
