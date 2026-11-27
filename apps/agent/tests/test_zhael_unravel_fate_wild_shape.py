from unittest.mock import patch

from _zhael_fate_fixtures import attack, defend
from _zhael_unravel_fixtures import activate, assert_restored, durable, favor, patch_player
from _zhael_unravel_fixtures import unravel as unravel
from acceptance._capstone_helpers import _d20, _damage_die
from combat._round_checkpoint_helpers import Fight
from sample_fixtures import published_payloads

import event_types as E


async def test_rewind_restores_wild_shape_and_its_resources(unravel: Fight) -> None:
    fight = unravel
    restorer, pid = fight.ids
    await favor(fight, pid, "thyra")
    await patch_player(fight, pid, **{"class": "druid", "level": 5, "focus": {"current": 10, "max": 10}})
    await fight.start()
    initial = await fight.row()
    checkpoint = initial["round_checkpoints"][0]
    original = next(p for p in initial["participants"] if p["id"] == pid)
    assert original["wild_shape"] is None and original["temp_hp"] == 2
    await fight.declare(
        {
            "kind": "ability",
            "actor_id": pid,
            "action": "druid_wild_shape",
            "targets": [],
            "argument_type": "grey_wolf",
            "reshape": [],
        },
        *(defend(p["id"]) for p in initial["participants"] if p["id"] != pid),
    )
    await fight.finish_round(2)
    second = await durable(fight)
    shifted = next(p for p in second["combat"]["participants"] if p["id"] == pid)
    assert shifted["wild_shape"]["form_id"] == "grey_wolf" and shifted["ac"] != original["ac"]
    assert [action["name"] for action in shifted["action_pool"]] == ["Bite"]
    assert shifted["deferred_effects"][0]["name"] == "Bite"
    before = checkpoint["players"][pid]["data"]
    after = second["players"][pid]["data"]
    assert after["focus"]["current"] == before["focus"]["current"] - 4
    assert after["stamina"]["current"] == before["stamina"]["current"] - 3

    assert (shifted["temp_hp"], after["temp_hp"]) == (5, 5)

    receipt = await activate(fight)
    assert receipt["round"] == 1 and "wild_shape_ended" not in receipt
    restored = await durable(fight)
    assert restored["players"][pid]["data"]["temp_hp"] == 2
    assert_restored(fight, restored, checkpoint, restorer)
    events = published_payloads(fight.session.room)
    update = next(event for event in reversed(events) if event["type"] == E.COMBAT_UI_UPDATE)
    assert "wildShape" not in next(p for p in update["combatants"] if p["id"] == pid)


async def test_rewind_restores_beast_and_player_pools(unravel: Fight) -> None:
    fight = unravel
    restorer, pid = fight.ids
    await favor(fight, pid, "thyra")
    await patch_player(fight, pid, **{"class": "druid", "level": 5, "hp": {"current": 30, "max": 30}})
    await fight.start("bandit_ambush")
    initial = await fight.row()
    await fight.declare(
        {
            "kind": "ability",
            "actor_id": pid,
            "action": "druid_wild_shape",
            "targets": [],
            "argument_type": "grey_wolf",
            "reshape": [],
        },
        *(defend(p["id"]) for p in initial["participants"] if p["id"] != pid),
    )
    await fight.finish_round(2)
    shaped = await fight.row()
    checkpoint = shaped["round_checkpoints"][-1]
    assert checkpoint["round_number"] == 2
    await fight.declare(
        attack("bandit_1", pid, "Light Crossbow"),
        *(defend(p["id"]) for p in shaped["participants"] if p["id"] != "bandit_1"),
    )
    with (
        patch("check_resolution.dice_roll", return_value=_d20(17)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(28)),
    ):
        await fight.finish_round(3)
    landed = await durable(fight)
    player = landed["players"][pid]["data"]
    actor = next(p for p in landed["combat"]["participants"] if p["id"] == pid)
    assert actor["wild_shape"] is None
    assert (actor["hp_current"], actor["temp_hp"]) == (player["hp"]["current"], player["temp_hp"]) == (25, 0)

    receipt = await activate(fight)
    assert receipt["round"] == 2
    assert_restored(fight, await durable(fight), checkpoint, restorer)
    update = next(e for e in reversed(published_payloads(fight.session.room)) if e["type"] == E.COMBAT_UI_UPDATE)
    projected = next(p for p in update["combatants"] if p["id"] == pid)
    assert (projected["wildShape"]["hpCurrent"], projected["hpCurrent"], projected["tempHp"]) == (11, 30, 5)
