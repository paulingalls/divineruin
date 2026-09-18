from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context

import check_resolution_attack
import combat_packet
from combat_phase import ResolutionPacket
from conditions import apply_condition
from declarations import Declaration, DeclarationType

WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}


class ScriptedRng:
    def __init__(self, values: list[int]):
        self.values = iter(values)
        self.calls: list[tuple[int, int]] = []

    def randint(self, low: int, high: int) -> int:
        self.calls.append((low, high))
        value = next(self.values)
        assert low <= value <= high
        return value


class RealResolver:
    def __init__(self, rng: ScriptedRng):
        self.rng = rng

    def resolve_attack(self, attacker_data, action, target_ac, target_hp, **kwargs):
        return check_resolution_attack.resolve_attack(
            attacker_data,
            action,
            target_ac,
            target_hp,
            rng=cast(Any, self.rng),
            **kwargs,
        )


def _combat_mocks():
    mutations = MagicMock()
    mutations.update_player_hp = AsyncMock()
    mutations.save_combat_state = AsyncMock()
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])
    concentration = MagicMock()
    concentration.break_concentration_on_damage = AsyncMock(return_value=None)
    return mutations, queries, concentration


@pytest.mark.asyncio
async def test_shaken_is_consumed_after_one_attack_before_the_next_swing():
    state = _make_combat_state(enemy_hp=40)
    player = state.get_participant("player_1")
    assert player is not None
    player.action_pool = [dict(WEAPON)]
    player.enhancers = ["extra_attack"]
    player.conditions = apply_condition([], "shaken")
    packet = ResolutionPacket(
        actor_id=player.id,
        declaration=Declaration(type=DeclarationType.ATTACK, action="Longsword", target_id="goblin_scout_1"),
        initiative=20,
    )
    rng = ScriptedRng([18, 5, 16, 4])
    mutations, queries, concentration = _combat_mocks()

    summary = await combat_packet._resolve_one_packet(
        make_context().userdata,
        state,
        packet,
        mutations=mutations,
        queries=queries,
        resolver=cast(Any, RealResolver(rng)),
        concentration_break_mod=concentration,
    )

    assert rng.calls.count((1, 20)) == 3
    assert [attack["roll"] for attack in summary["attacks"]] == [5, 16]
    assert summary["attacks"][0]["consumed_conditions"] == ("shaken",)
    assert summary["attacks"][1]["consumed_conditions"] == ()
    assert "shaken" not in {condition["type"] for condition in player.conditions}


def test_attack_consumption_preserves_bearer_order_and_deduplicates():
    conditions = apply_condition(apply_condition([], "shaken"), "blessed")
    rng = ScriptedRng([2, 18, 5])

    result = check_resolution_attack.resolve_attack(
        {"attributes": {"strength": 10}, "level": 1, "conditions": conditions},
        WEAPON,
        target_ac=20,
        target_hp=40,
        rng=cast(Any, rng),
    )

    assert result.consumed_conditions == ("shaken", "blessed")
