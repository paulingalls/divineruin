"""Numeric patron clauses at the check, activation and combat boundaries."""

import pytest
from _unbound_path_fixtures import world as world
from patron_engine_scenarios import ENGINE_SCENARIOS

from _gods_content import engine_implementations


@pytest.mark.parametrize(
    "implementation_id,args",
    [
        pytest.param(key, args, id=f"{key}-{i}")
        for key in sorted(set(engine_implementations()) | set(ENGINE_SCENARIOS))
        for i, args in enumerate(ENGINE_SCENARIOS.get(key, (None, None, [()]))[2])
    ],
)
async def test_registered_engine_implementation(world, implementation_id, args):
    registry = engine_implementations()
    assert registry
    assert set(registry) == set(ENGINE_SCENARIOS), "Every engine ID needs a production scenario"
    target, scenario, _ = ENGINE_SCENARIOS[implementation_id]
    assert registry[implementation_id] == target
    await scenario(world, *args)
