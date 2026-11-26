"""Field Medic Order through the registered combat and Fate verbs."""

from unittest.mock import patch

import pytest
from _item_heal_fixtures import POTION, heal_roll
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from combat.test_marshal_direct_strike import HP, arrange, attack, declare_round, hp, pending, round_packets
from combat.test_marshal_orders import MEDIC
from combat.test_marshal_orders import marshal as marshal
from combat.test_marshal_orders import mock_combat_agent_factory as mock_combat_agent_factory
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party

import db_mutations
import db_queries
import event_types as E


async def battlefield(marshal, *, fate=False, quantity=2):
    fight = await arrange(marshal, level=4, owned=(MEDIC,), fate=fate)
    _, holder, other = fight.players
    state = await fight.reload()
    for player_id in (holder, other):
        required_player(state, player_id).hp_current = 30
    await fight.persist()
    if quantity:
        await db_mutations.add_inventory_item(holder, POTION, quantity, tainted=False)
    return fight


async def order(fight):
    source, holder, _ = fight.players
    abilities = (await fight.command("query_info", {"kind": "abilities"}))["abilities"]
    order_id = next(row["id"] for row in abilities if row["id"] == MEDIC)
    return dict(kind="ability", actor_id=source, action=order_id, targets=[holder], argument_type="", reshape=[])


def combined(fight, recipient=""):
    return dict(
        kind="attack_consume",
        actor_id=fight.players[1],
        action="Longsword",
        target_id=fight.enemies[0],
        item_id=POTION,
        heal_target_id=recipient,
    )


async def quantity(holder):
    item = await db_queries.get_inventory_item(holder, POTION)
    return item["quantity"] if item is not None else 0


async def assert_health(fight, player_id, expected):
    row = await db_queries.get_player(player_id)
    assert row is not None
    assert row["hp"]["current"] == await hp(fight, player_id) == expected


def heal_receipt(packet, source):
    medic = packet["field_medic"]
    assert (medic["order_id"], medic["name"], medic["source_id"]) == (MEDIC, "Field Medic Order", source)
    assert packet["effect_resolution"] == "engine"
    assert medic["heal"]["item_id"] == POTION
    return medic["heal"]


def inventory_events(fight):
    return [p for p in published_payloads(fight.sd.room) if p["type"] == E.INVENTORY_UPDATED]


async def assert_refused(fight, reason, recipient=""):
    before = await fight.snapshot()
    inventory = await db_queries.get_inventory_snapshot(fight.players[1])
    events = published_payloads(fight.sd.room)
    assert reason in await declare_round(fight, combined(fight, recipient), error=True)
    assert await fight.snapshot() == before
    assert await db_queries.get_inventory_snapshot(fight.players[1]) == inventory
    assert published_payloads(fight.sd.room) == events


@pytest.mark.parametrize("apply_to_ally", (False, True))
async def test_field_medic_lands_attack_and_heal_after_an_ordinary_attack(marshal, apply_to_ally):
    fight = await battlefield(marshal)
    source, holder, other = fight.players
    foe = fight.enemies[0]
    # Marshal resolves first, so the ordinary attack passes a live permission.
    packets = await round_packets(fight, await order(fight), attack(holder, foe), faces=(2,))
    assert packets[holder]["hit"] is False and "field_medic" not in packets[holder]
    riders = await pending(fight)
    assert riders[holder][0]["expires_round"] == 2
    await assert_health(fight, holder, 30)
    assert await quantity(holder) == 2

    recipient = other if apply_to_ally else holder
    before_players = (await fight.snapshot())[1]
    await declare_round(fight, combined(fight, other if apply_to_ally else ""))
    assert (await fight.snapshot())[1] == before_players
    assert await pending(fight) == riders and await quantity(holder) == 2
    events = inventory_events(fight)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(16)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as weapon,
        heal_roll(7) as heal,
    ):
        (packet,) = [p for p in await fight.drain() if p["actor_id"] == holder]
    weapon.assert_called_once_with("1d8", rng=None)
    heal.assert_called_once_with("2d4+2")
    assert packet["hit"] and packet["damage"] == 4 and await hp(fight, foe) == HP - 4
    healing = heal_receipt(packet, source)
    assert healing["resolved"] and healing["remaining_quantity"] == 1
    assert healing["healing_results"][0]["target_id"] == recipient
    assert healing["healing_results"][0]["healed"] == 7
    await assert_health(fight, recipient, 37)
    await assert_health(fight, holder if apply_to_ally else other, 30)
    assert await quantity(holder) == 1 and await quantity(other) == 0
    assert len(inventory_events(fight)) == len(events) + 1
    assert await pending(fight) == {}
    await assert_refused(fight, "Field Medic Order")


@pytest.mark.parametrize("expired", (False, True))
async def test_combined_action_requires_an_unspent_order(marshal, expired):
    fight = await battlefield(marshal)
    if expired:
        await round_packets(fight, await order(fight))
        assert await pending(fight)
        await round_packets(fight)
        assert (await fight.reload()).round_number == 3
        assert await pending(fight) == {}
    await assert_refused(fight, "Field Medic Order")


@pytest.mark.parametrize("invalid", ("past_round", "non_player"))
async def test_combined_action_refuses_an_inapplicable_persisted_grant(marshal, invalid):
    fight = await battlefield(marshal)
    _, holder, other = fight.players
    await round_packets(fight, await order(fight))
    state = await fight.reload()
    [rider] = state.order_riders[holder]
    if invalid == "past_round":
        rider["expires_round"] = state.round_number - 1
    else:
        required_player(state, holder).type = "companion"
    await fight.persist()
    await assert_refused(fight, "Field Medic Order", other)


async def test_combined_action_checks_the_held_item_at_declaration(marshal):
    fight = await battlefield(marshal, quantity=0)
    await round_packets(fight, await order(fight))
    await assert_refused(fight, "has no untainted Healing Potion")


@pytest.fixture
async def fate_fight(marshal):
    fight = await battlefield(marshal, fate=True)
    lifecycle = _live_party(fight.sd, *fight.players)
    try:
        yield fight
    finally:
        await lifecycle.aclose()


@pytest.mark.parametrize("keep,face", (("original", 15), ("reroll", 17)))
async def test_fate_held_attack_and_item_settle_once_after_reload(fate_fight, keep, face):
    fight = fate_fight
    source, holder, other = fight.players
    foe = fight.enemies[0]
    await round_packets(fight, await order(fight))
    riders = await pending(fight)
    await declare_round(fight, combined(fight, other))
    events = inventory_events(fight)

    async def assert_held():
        state = await fight.reload()
        assert state.ally_continuation["attack"]
        assert state.pending_declarations[holder]["healing_item"] == {"item_id": POTION, "target_id": other}
        assert state.order_riders == riders
        assert await hp(fight, foe) == HP and await quantity(holder) == 2
        await assert_health(fight, other, 30)
        assert inventory_events(fight) == events

    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, (15, 17))),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as weapon,
        heal_roll(7) as heal,
    ):
        offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert offer["roller_id"] == holder and offer["die"] == 15 and source in offer["eligible_followers"]
        await assert_held()
        ability = {"id": "zhael_fates_thread", "offer_id": offer["offer_id"]}
        assert (await fight.command("activate", ability))["reroll"]["die"] == 17
        await assert_held()
        weapon.assert_not_called()
        heal.assert_not_called()
        result = await fight.command("activate", {**ability, "keep": keep})
        (packet,) = [p for p in result["packets"] if p["actor_id"] == holder]
        assert not any("field_medic" in p for p in await fight.drain())
    weapon.assert_called_once_with("1d8", rng=None)
    heal.assert_called_once_with("2d4+2")
    assert packet["roll"] == face and packet["damage"] == 4 and await hp(fight, foe) == HP - 4
    assert heal_receipt(packet, source)["healing_results"][0]["target_id"] == other
    assert await quantity(holder) == 1
    await assert_health(fight, other, 37)
    assert len(inventory_events(fight)) == len(events) + 1
    assert await pending(fight) == {}


async def test_departed_roller_cancels_both_halves_of_the_held_declaration(fate_fight):
    fight = fate_fight
    _, holder, other = fight.players
    await round_packets(fight, await order(fight))
    riders = await pending(fight)
    await declare_round(fight, combined(fight, other))
    events = inventory_events(fight)

    with patch("check_resolution.dice_roll", return_value=_d20(15)), heal_roll(7):
        offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert offer["roller_id"] == holder
        assert (await fight.reload()).ally_continuation["attack"]
        owner = fight.sd.multiplayer_owner
        assert owner is not None
        owner.lifecycle.mark_departed(holder)
        result = await fight.command(
            "activate", {"id": "zhael_fates_thread", "offer_id": offer["offer_id"], "keep": "original"}
        )
    (packet,) = [p for p in result["packets"] if p["actor_id"] == holder]
    assert packet["outcome"] == "cancelled"
    assert await quantity(holder) == 2
    assert "field_medic" not in packet and inventory_events(fight) == events
    await assert_health(fight, other, 30)
    assert await pending(fight) == riders


async def test_approach_reaction_window_defers_the_item(marshal):
    fight = await battlefield(marshal)
    source, holder, _ = fight.players
    target, reactor = fight.enemies
    await round_packets(fight, await order(fight))
    state = await fight.reload()
    actor = required_player(state, holder)
    actor.has_reaction_ability = True
    actor.reaction_ids = ["rogue_uncanny_dodge"]
    assert state.spatial is not None
    state.spatial["positions"][target]["x"] = 25
    state.spatial["positions"][reactor]["x"] = 0
    await fight.persist()
    riders = await pending(fight)
    await declare_round(fight, combined(fight))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        heal_roll(7) as heal,
    ):
        result = await fight.command("resolve_phase", {})
        waiting = result["next"]["waiting_on"]
        assert waiting["opportunity_attack"] and waiting["stage"] == "pre_roll"
        assert await pending(fight) == riders
        assert await hp(fight, target) == HP and await quantity(holder) == 2
        await assert_health(fight, holder, 30)
        heal.assert_not_called()
        (packet,) = [p for p in await fight.drain() if "field_medic" in p]
    assert packet["hit"] and await hp(fight, target) == HP - 4
    assert heal_receipt(packet, source)["resolved"]
    heal.assert_called_once_with("2d4+2")
    assert await quantity(holder) == 1 and await pending(fight) == {}


async def test_missing_item_does_not_reopen_phase_or_cancel_attack(marshal):
    fight = await battlefield(marshal, quantity=1)
    source, holder, _ = fight.players
    await round_packets(fight, await order(fight))
    await declare_round(fight, combined(fight))
    assert await db_mutations.remove_inventory_item(holder, POTION)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(16)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        heal_roll(7) as heal,
    ):
        result = await fight.command("resolve_phase", {})
    assert result["beat"] == "narration"
    (packet,) = [p for p in result["packets"] if p["actor_id"] == holder]
    assert packet["hit"] and packet["damage"] == 4 and await hp(fight, fight.enemies[0]) == HP - 4
    failed = heal_receipt(packet, source)
    assert failed["resolved"] is False and "has no untainted Healing Potion" in failed["reason"]
    heal.assert_not_called()
    await assert_health(fight, holder, 30)
    assert await quantity(holder) == 0 and await pending(fight) == {}


async def test_fallen_foe_does_not_cancel_the_heal(marshal):
    fight = await battlefield(marshal)
    source, holder, other = fight.players
    foe = fight.enemies[0]
    await round_packets(fight, await order(fight))
    state = await fight.reload()
    required_player(state, foe).hp_current = 1
    await fight.persist()
    with heal_roll(7) as heal:
        packets = await round_packets(fight, attack(other, foe), combined(fight), faces=(16,), damage=(("1d8", 4),))
    assert packets[other]["hit"]
    packet = packets[holder]
    assert packet["declaration_type"] == "attack" and packet["action"] == "Longsword"
    assert packet["resolved"] is False and "already fell" in packet["reason"]
    assert heal_receipt(packet, source)["resolved"]
    heal.assert_called_once_with("2d4+2")
    await assert_health(fight, holder, 37)
    assert await quantity(holder) == 1 and await pending(fight) == {}
