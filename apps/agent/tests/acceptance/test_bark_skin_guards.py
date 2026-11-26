from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_bark_skin import BANDIT, TREANT, attack_face, blow, declare, effect, opening, spend
from acceptance.test_bark_skin import fight as fight
from acceptance.test_bark_skin import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_guardian_intercept import pools
from acceptance.test_opportunity_strike import participant


@pytest.mark.parametrize(("scenario", "margin"), [("plain", 2), ("plain", 3), ("natural", 0)])
async def test_bonus_lasts_one_round(fight: MawlingHarness, scenario: str, margin: int) -> None:
    expected = attack_face(fight, BANDIT, margin)
    face, total, ac = expected
    followup, follow_total, _ = attack_face(fight, TREANT, 1)
    if scenario == "natural":
        assert face == 20 and total == ac
    assert 1 < followup < 20
    before = await pools(fight)
    await declare(fight, BANDIT, TREANT)
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face), _d20(followup), _d20(followup)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
    ):
        window, original = await opening(fight, expected)
        ability_id = await spend(fight, window)
        packets = await fight.drain()
        attack, second = blow(packets), blow(packets, TREANT)
        assert (attack["roll"], attack["attack_total"], attack["target_ac"], attack["hit"]) == (
            face,
            total,
            ac + 2,
            True,
        )
        assert attack["damage"] == original["damage"] > 0
        assert attack["critical"] is (scenario == "natural")
        assert (second["attack_total"], second["target_ac"], second["hit"], second["damage"]) == (
            follow_total,
            ac + 2,
            False,
            0,
        )
        assert effect(packets, ability_id) == "round_ac_bonus"
        assert (await pools(fight))[0][0] == before[0][0] - attack["damage"]
        await declare(fight, TREANT)
        next_attack = blow(await fight.drain(), TREANT)

    assert (next_attack["attack_total"], next_attack["target_ac"], next_attack["hit"]) == (follow_total, ac, True)
    assert next_attack["damage"] > 0
    assert (await pools(fight))[0][0] == before[0][0] - attack["damage"] - next_attack["damage"]
    assert not participant(await fight.reload(), fight.players[0]).bark_skin_active
