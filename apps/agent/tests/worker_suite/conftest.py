"""Autouse fixtures for the async-worker test suite."""

from unittest.mock import AsyncMock, patch

import pytest
from worker_suite._samples import _WEAPON_QUALITY


@pytest.fixture(autouse=True)
def _stub_crafting_worker_db():
    """Stub the worker's crafting DB boundary so these tests run without a database.

    get_recipe/get_quality_outcomes feed the real resolver (gates/bands stay real);
    increment_crafting_skill_counter (story-006) is the failure-band hidden-counter
    write — stubbed so a random-roll Failure here doesn't hit the real pool. The
    counter behavior itself is covered by test_crafting_skill_counter.py.
    """
    with (
        patch("crafting_resolution.get_recipe", new_callable=AsyncMock, return_value={"category": "weapon"}),
        patch("crafting_resolution.get_quality_outcomes", new_callable=AsyncMock, return_value=_WEAPON_QUALITY),
        patch("async_worker.db_mutations.increment_crafting_skill_counter", new_callable=AsyncMock),
    ):
        yield
