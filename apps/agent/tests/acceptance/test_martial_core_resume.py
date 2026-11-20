"""Martial packets across a saved combat continuation."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_martial_core_kit import SECOND_WIND, adjacent_foe, declare, enter
from acceptance.test_martial_core_kit import warriors as warriors
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import db_mutations
import db_queries


async def test_second_wind_is_complete_before_a_reloaded_hostile_blow(warriors) -> None:
    actor = warriors.players[0]
    await db_mutations.update_player_hp(actor, 40)
    await enter(warriors)
    foe = await adjacent_foe(warriors)
    state = await warriors.reload()
    enemy = state.get_participant(foe)
    assert enemy is not None
    await warriors.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "ability",
                    "actor_id": actor,
                    "action": SECOND_WIND,
                    "targets": [],
                    "argument_type": "",
                    "reshape": [],
                },
                {
                    "kind": "attack",
                    "actor_id": foe,
                    "target_id": actor,
                    "action": enemy.action_pool[0]["name"],
                    "held_item_id": "",
                    "rider": "",
                    "reshape": [],
                },
            ]
        },
    )
    with patch("dice.roll", return_value=_damage_die(7)) as healed:
        first = await warriors.command("resolve_phase", {})
    healed.assert_called_once_with("1d10")
    assert next(p for p in first["packets"] if p["actor_id"] == actor)["healed"] == 13
    state = await warriors.reload()
    assert state.held_actions and state.held_actions[0]["actor_id"] == foe
    real_player = await db_queries.get_player(actor)
    assert real_player is not None and real_player["hp"]["current"] == 53
    assert real_player["stamina"]["current"] == 6
    await fresh_session(warriors, state)
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        packets = await warriors.drain()
    assert not any(packet.get("action") == SECOND_WIND for packet in packets)
    assert await db_queries.get_player(actor) == real_player
    participant = (await warriors.reload()).get_participant(actor)
    assert participant is not None and participant.action_ledger[SECOND_WIND]["remaining"] == 0


@pytest.mark.parametrize("bash", [False, True], ids=["devastating_attack", "bash_save"])
async def test_martial_roll_reloads_without_rolling_or_charging_again(warriors: MawlingHarness, bash: bool) -> None:
    actor = warriors.players[0]
    await enter(warriors)
    foe = await adjacent_foe(warriors)
    await favor(warriors)
    if bash:
        await warriors.command(
            "declare_phase",
            {
                "declarations": [
                    {
                        "kind": "attack",
                        "actor_id": actor,
                        "action": "Longsword",
                        "target_id": foe,
                        "held_item_id": "",
                        "rider": "shield_bash",
                        "reshape": [],
                    },
                ]
            },
        )
    else:
        await declare(warriors, "warrior_devastating_strike", [foe])
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(1)]) as d20,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        first = await warriors.command("resolve_phase", {})
        assert (first["fate_offer"]["roll_kind"], first["fate_offer"]["roller_id"]) == ("attack", actor)
        saved = await warriors.reload()
        assert saved.ally_continuation and saved.ally_continuation["attack"]["prepared"]
        damage.assert_not_called()
        await fresh_session(warriors, saved)
        if bash:
            second = await warriors.command("resolve_phase", {})
            assert (second["fate_offer"]["roll_kind"], second["fate_offer"]["roller_id"]) == ("save", foe)
            saved = await warriors.reload()
            target = saved.get_participant(foe)
            assert target is not None and target.hp_current == 95 and not target.conditions
            assert saved.ally_continuation
            damage.assert_called_once()
            row = await db_queries.get_player(actor)
            assert row is not None and row["stamina"]["current"] == 8
            await fresh_session(warriors, saved)
        packets = await warriors.drain()
    assert d20.call_count == (2 if bash else 1)
    assert damage.call_count == (1 if bash else 2)
    receipt = next(packet for packet in packets if packet["actor_id"] == actor)
    assert receipt["damage"] == (5 if bash else 9)
    if bash:
        assert receipt["condition_inflicted"] == "stunned"
    row = await db_queries.get_player(actor)
    assert row is not None and row["stamina"]["current"] == (8 if bash else 7)
    target = (await warriors.reload()).get_participant(foe)
    assert target is not None and target.hp_current == (95 if bash else 91)
