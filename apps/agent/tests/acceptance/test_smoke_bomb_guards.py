"""Smoke Bomb target and persisted zone validation."""

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_iron_stance import ability
from acceptance.test_martial_core_kit import enter
from acceptance.test_smoke_bomb import SMOKE
from acceptance.test_smoke_bomb import smoke_walk as smoke_walk
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

from combat_state import CombatState


@pytest.mark.parametrize("target_kind", ["foreign", "multiple"])
async def test_smoke_rejects_targets_without_spending(smoke_walk: MawlingHarness, target_kind: str) -> None:
    walk = smoke_walk
    await enter(walk)
    rogue, ally = walk.players
    before = await walk.snapshot()
    targets = [ally] if target_kind == "foreign" else [rogue, ally]
    action = ability(rogue, SMOKE, *targets)
    output = await walk.command("declare_phase", {"declarations": [action]}, error=True)
    assert "Smoke Bomb targets only the rogue" in output
    assert await walk.snapshot() == before


@pytest.mark.parametrize(
    "change",
    [
        {"expires_round": True},
        {"expires_round": 0},
        {"expires_round": 1.5},
        {"kind": "silence"},
        {"center_id": None},
    ],
)
async def test_persisted_smoke_expiry_contract(smoke_walk: MawlingHarness, change: dict) -> None:
    walk = smoke_walk
    await enter(walk)
    state = await walk.reload()
    snapshot = state.to_dict()
    spatial = snapshot["spatial"]
    spatial["locations"]["cloud_origin"] = pos(0)
    cloud = {"kind": "smoke", "center_id": "cloud_origin", "radius_ft": 10, "expires_round": 2}
    spatial["zones"]["cloud"] = cloud
    restored = CombatState.from_dict(snapshot)
    assert restored.to_dict()["spatial"]["zones"]["cloud"] == cloud
    if change == {"center_id": None}:
        change = {"center_id": walk.players[0]}
    spatial["zones"]["cloud"] = {**cloud, **change}
    with pytest.raises(ValueError, match="zone expiry"):
        CombatState.from_dict(snapshot)
