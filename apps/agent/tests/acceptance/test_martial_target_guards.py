"""Martial target restrictions through the registered declaration tool."""

import pytest
from acceptance.test_martial_core_kit import RALLY, SECOND_WIND, adjacent_foe, declare, enter
from acceptance.test_martial_core_kit import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_martial_core_kit import warriors as warriors

import db_queries


@pytest.mark.parametrize(
    ("ability", "target", "reason"),
    [
        ("warrior_devastating_strike", "ally", "one standing foe"),
        ("warrior_devastating_strike", "fallen", "one standing foe"),
        (SECOND_WIND, "ally", "only heals the warrior"),
        (RALLY, "foe", "standing ally"),
        (RALLY, "self", "standing ally"),
        (RALLY, "missing", "standing ally"),
    ],
)
async def test_martial_target_refusal_leaves_state_unchanged(warriors, ability, target, reason):
    await enter(warriors)
    actor, ally = warriors.players
    foe = await adjacent_foe(warriors)
    state = await warriors.reload()
    if target == "fallen":
        state.get_participant(foe).is_fallen = True
        await warriors.persist()
    snapshot = (await warriors.reload()).to_dict()
    player = await db_queries.get_player(actor)
    targets = {"ally": [ally], "fallen": [foe], "foe": [foe], "self": [actor], "missing": []}
    assert reason in await declare(warriors, ability, targets[target], error=True)
    assert (await warriors.reload()).to_dict() == snapshot
    assert await db_queries.get_player(actor) == player
