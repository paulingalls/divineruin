"""Martial packets across a saved combat continuation."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_martial_core_kit import SECOND_WIND, adjacent_foe, declare, enter, weapon_attack
from acceptance.test_martial_core_kit import rogue as rogue
from acceptance.test_martial_core_kit import warriors as warriors
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from weapon_fixtures import DAGGER

import combat_spatial
import db_mutations
import db_queries


@pytest.mark.parametrize(
    "ability", [SECOND_WIND, "warrior_rallying_shout", "warrior_devastating_strike", "shield_bash"]
)
async def test_warrior_action_is_complete_before_a_reloaded_hostile_blow(
    warriors: MawlingHarness, ability: str
) -> None:
    actor, ally = warriors.players
    await db_mutations.update_player_hp(actor, 40)
    await enter(warriors)
    foe = await adjacent_foe(warriors)
    state = await warriors.reload()
    enemy = state.get_participant(foe)
    assert enemy is not None
    martial = (
        weapon_attack(actor, foe, ability)
        if ability == "shield_bash"
        else {
            "kind": "ability",
            "actor_id": actor,
            "action": ability,
            "targets": {
                SECOND_WIND: [],
                "warrior_rallying_shout": [ally],
                "warrior_devastating_strike": [foe],
            }[ability],
            "argument_type": "",
            "reshape": [],
        }
    )
    await warriors.command(
        "declare_phase",
        {
            "declarations": [
                martial,
                {
                    **weapon_attack(foe, actor, ""),
                    "action": enemy.action_pool[0]["name"],
                },
            ]
        },
    )
    with (
        patch("dice.roll", return_value=_damage_die(7)),
        patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(20)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        first = await warriors.command("resolve_phase", {})
    receipt = next(p for p in first["packets"] if p["actor_id"] == actor)
    assert receipt["resolved"]
    if ability == SECOND_WIND:
        assert receipt["healed"] == 13
    state = await warriors.reload()
    assert state.held_actions and state.held_actions[0]["actor_id"] == foe
    player = await db_queries.get_player(actor)
    assert player is not None
    participant = state.get_participant(actor)
    recipient = state.get_participant(ally)
    target = state.get_participant(foe)
    assert participant is not None and recipient is not None and target is not None
    expected_cost = {SECOND_WIND: 4, "warrior_rallying_shout": 2, "warrior_devastating_strike": 3, "shield_bash": 2}
    assert player["stamina"]["current"] == 10 - expected_cost[ability]
    if ability == "warrior_rallying_shout":
        assert any(condition["type"] == "precise_strike" for condition in recipient.conditions)
    await fresh_session(warriors, state)
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        packets = await warriors.drain()
    assert not any(packet.get("actor_id") == actor for packet in packets)
    assert await db_queries.get_player(actor) == {**player, "temp_hp": 0}
    reloaded = await warriors.reload()
    reloaded_actor = reloaded.get_participant(actor)
    reloaded_ally = reloaded.get_participant(ally)
    reloaded_target = reloaded.get_participant(foe)
    assert reloaded_actor is not None and reloaded_actor.action_ledger == participant.action_ledger
    assert reloaded_ally is not None and reloaded_ally.conditions == recipient.conditions
    assert reloaded_target is not None and reloaded_target.hp_current == target.hp_current


@pytest.mark.parametrize("bash", [False, True], ids=["devastating_attack", "bash_save"])
async def test_martial_roll_reloads_without_rolling_or_charging_again(warriors: MawlingHarness, bash: bool) -> None:
    from _zhael_marshal_rally_fixtures import pending

    actor = warriors.players[0]
    await enter(warriors)
    foe = await adjacent_foe(warriors)
    await favor(warriors)
    if bash:
        state = await warriors.reload()
        source = warriors.players[1]
        pending(state, actor, source)
        await warriors.persist()
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
        assert "rally_bonuses" not in receipt
        assert (await warriors.reload()).encounter_facts["rally_pending"] == {warriors.players[1]: actor}
    row = await db_queries.get_player(actor)
    assert row is not None and row["stamina"]["current"] == (8 if bash else 7)
    target = (await warriors.reload()).get_participant(foe)
    assert target is not None and target.hp_current == (95 if bash else 91)


async def test_cunning_hide_reloads_after_the_attack(rogue: MawlingHarness) -> None:
    actor = rogue.players[0]
    await enter(rogue)
    foe = await adjacent_foe(rogue)
    await favor(rogue)
    await rogue.pool.execute(
        """UPDATE players SET data = data || '{"patron_gifts":{"zhael_fates_thread":{"spent":true}}}'
        WHERE player_id = $1""",
        actor,
    )
    state = await rogue.reload()
    enemy = state.get_participant(foe)
    assert enemy is not None
    await rogue.command(
        "declare_phase",
        {
            "declarations": [
                weapon_attack(actor, foe, "hide", weapon=DAGGER["name"]),
                {**weapon_attack(foe, actor, ""), "action": enemy.action_pool[0]["name"]},
            ]
        },
    )
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(20)]) as d20,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        held = (await rogue.command("resolve_phase", {}))["fate_offer"]
        assert (held["roll_kind"], held["roller_id"]) == ("skill", actor)
        saved = await rogue.reload()
        assert saved.ally_continuation and saved.ally_continuation["steps"]["cunning_hide"]["skill"]
        before = await db_queries.get_player(actor)
        assert before is not None and before["stamina"]["current"] == 8
        assert not before.get("flags", {}).get("concealed", False)
        target = saved.get_participant(foe)
        assert target is not None and target.hp_current == 91
        await fresh_session(rogue, saved)
        third = await rogue.command("resolve_phase", {})
    receipt = next(packet for packet in third["packets"] if packet["actor_id"] == actor)
    assert receipt["damage"] == 9 and receipt["cunning_action"]["concealed"]
    assert d20.call_count == 2 and damage.call_count == 2
    after = await db_queries.get_player(actor)
    assert after is not None and after["flags"]["concealed"] and after["stamina"] == before["stamina"]
    suspended = await rogue.reload()
    assert suspended.held_actions and suspended.held_actions[0]["actor_id"] == foe
    position = combat_spatial.position(combat_spatial.require_spatial(suspended), actor)
    await fresh_session(rogue, suspended)
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        packets = await rogue.drain()
    assert not any(packet.get("actor_id") == actor for packet in packets)
    assert await db_queries.get_player(actor) == after
    state = await rogue.reload()
    target = state.get_participant(foe)
    assert target is not None and target.hp_current == 91
    assert combat_spatial.position(combat_spatial.require_spatial(state), actor) == position


@pytest.mark.parametrize(("rider", "stamina"), [("hide", 10), ("dash", 8)])
async def test_cunning_action_cost_when_target_stays_out_of_reach(
    rogue: MawlingHarness, rider: str, stamina: int
) -> None:
    actor = rogue.players[0]
    await enter(rogue)
    foe = await adjacent_foe(rogue)
    state = await rogue.reload()
    origin = combat_spatial.position(state.spatial, actor)
    combat_spatial.place(state, foe, {**origin, "x": origin["x"] + 200})
    await rogue.persist()

    await rogue.command("declare_phase", {"declarations": [weapon_attack(actor, foe, rider, weapon=DAGGER["name"])]})
    with patch("check_resolution.dice_roll") as roll:
        packet = next(packet for packet in await rogue.drain() if packet["actor_id"] == actor)
    assert not packet["attack_resolved"] and packet["moved_ft"] > 0
    assert "cunning_action" not in packet
    roll.assert_not_called()
    player = await db_queries.get_player(actor)
    assert player is not None and player["stamina"]["current"] == stamina
