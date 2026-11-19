"""A risen player cannot attack with their patron data silently missing."""

from unittest.mock import AsyncMock

import pytest
from acceptance._capstone_helpers import _build_state, _enemy
from voice_condition_fixtures import participant

import check_resolution_attack
from combat_fate_hostile import roll_hostile
from declarations import resolve_declaration


async def test_risen_attacker_requires_its_player_row():
    state = _build_state("fight", "target", [_enemy("risen", 30)])
    attacker = participant(state, "risen")
    attacker.type = "temporary_hollowed"
    action = attacker.action_pool[0]
    raw = {"type": "attack", "action": action["name"], "target_id": "target"}
    head = {"actor_id": attacker.id, "declaration": raw}

    class Queries:
        get_player = AsyncMock(return_value=None)

    deps = {"queries": Queries, "conn": None, "resolver": check_resolution_attack}
    with pytest.raises(RuntimeError, match="Attack participant 'risen' has no player row"):
        await roll_hostile(None, state, head, resolve_declaration(raw), action, 0, deps, None)
    Queries.get_player.assert_awaited_once_with("risen", conn=None)
    assert "roll" not in head
