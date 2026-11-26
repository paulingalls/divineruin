"""A Lucky flip on a stanced warrior's death save keeps the flipped face and draws no fresh die."""

import json
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_iron_stance import attack, declare, place_foe, stance
from acceptance.test_iron_stance import walk as walk
from acceptance.test_martial_core_kit import enter
from acceptance.test_opportunity_strike import participant
from acceptance.test_self_buff_electives import defend
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

from patron_ability_tools import LUCKY
from zhael_fate import FATE


@pytest.mark.parametrize("walk", [("fragment_shadeling", "greyvale_wilderness_north")], indirect=True)
async def test_lucky_flip_keeps_flipped_death_save(walk: MawlingHarness) -> None:
    actor, ally = walk.players
    favor = {"patron": "zhael", "level": 40, "max": 100}
    await walk.pool.execute(
        "UPDATE players SET data = data || $2::jsonb WHERE player_id = $1",
        actor,
        json.dumps({"divine_favor": favor, "patron_gifts": {FATE: {"spent": True}}}),
    )
    await enter(walk)
    foe = await place_foe(walk, "hollow_shadeling")
    state = await walk.reload()
    participant(state, actor).hp_current = 4
    await walk.persist()
    await declare(walk, stance(actor), defend(ally), attack(foe, actor, "Corrosive Touch"))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(9)),
    ):
        await walk.drain()
    assert participant(await walk.reload(), actor).is_fallen

    with patch("combat_resolution.dice_roll", side_effect=map(_d20, [1, 1, 7])) as rolls:
        offer = (await walk.command("request_death_save", {"player_id": actor}))["fate_offer"]
        assert offer["die"] == 1 and rolls.call_count == 2
        assert [ability["id"] for ability in offer["abilities"]] == [LUCKY]
        saved = await walk.command("activate", {"id": LUCKY, "offer_id": offer["offer_id"]})
    assert rolls.call_count == 2
    assert saved["roll"] == 20 and saved["revived"]
    after = participant(await walk.reload(), actor)
    assert (after.hp_current, after.is_fallen) == (1, False)
