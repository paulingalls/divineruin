"""Beacon of Hope on healing producers outside the spell heal path."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_martial_core_kit import SECOND_WIND, declare, enter
from acceptance.test_martial_core_kit import warriors as warriors
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import db_mutations
import db_queries
from condition_catalog import BEACON_OF_HOPE
from conditions import apply_condition


@pytest.mark.parametrize(("beacon", "rolled"), [(True, 10), (False, 1)])
async def test_beacon_maximizes_second_wind(warriors: MawlingHarness, beacon: bool, rolled: int) -> None:
    actor, caster = warriors.players
    await db_mutations.update_player_hp(actor, 40)
    await enter(warriors)
    if beacon:
        warrior = (await warriors.reload()).get_participant(actor)
        assert warrior is not None
        warrior.conditions = apply_condition(warrior.conditions, BEACON_OF_HOPE, sustaining_caster_id=caster)
        await warriors.persist()
    await declare(warriors, SECOND_WIND, [])
    with patch("dice.roll", return_value=_damage_die(1)):
        packets = await warriors.drain()
    receipt = next(packet for packet in packets if packet["actor_id"] == actor)
    assert (receipt["rolled"], receipt["healed"]) == (rolled, rolled + 6)
    row = await db_queries.get_player(actor)
    assert row is not None and row["hp"]["current"] == 46 + rolled
    participant = (await warriors.reload()).get_participant(actor)
    assert participant is not None and participant.hp_current == 46 + rolled
