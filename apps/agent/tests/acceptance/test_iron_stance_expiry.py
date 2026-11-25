"""Iron Stance ends when the warrior's turn passes, even when that turn carries no packet."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_iron_stance import attack, declare, place_foe, stance
from acceptance.test_iron_stance import walk as walk
from acceptance.test_martial_core_kit import enter
from acceptance.test_opportunity_strike import participant
from acceptance.test_self_buff_electives import condition_types, defend, receipt
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import conditions


@pytest.mark.parametrize("stunned", [True, False])
async def test_turn_without_packet_ends_stance(walk: MawlingHarness, stunned: bool) -> None:
    await enter(walk)
    actor, ally = walk.players
    foe = await place_foe(walk, "bandit_captain")
    await declare(walk, stance(actor), defend(ally))
    await walk.drain()
    assert "iron_stance" in await condition_types(walk, actor)
    if stunned:
        state = await walk.reload()
        warrior = participant(state, actor)
        warrior.conditions = conditions.apply_condition(warrior.conditions, "stunned", duration=3, source=foe)
        await walk.persist()
        assert "is stunned" in await declare(walk, defend(actor), error=True)

    await declare(walk, defend(ally))
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        await walk.drain()
    held = await condition_types(walk, actor)
    assert "iron_stance" not in held
    assert ("stunned" in held) == stunned

    await declare(walk, defend(ally), attack(foe, actor, "Longsword"))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(9)),
    ):
        result = receipt(await walk.drain(), foe)
    assert (result["damage_type"], result["damage"]) == ("slashing", 11)
    assert participant(await walk.reload(), actor).hp_current == 89
