import json
from copy import deepcopy
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from _zhael_unravel_fixtures import activate, assert_refused, opening, patch_player
from _zhael_unravel_fixtures import unravel as unravel
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.defensive_reactions_harness import defense_fight, player_row
from acceptance.disruption_reactions_harness import open_stage
from acceptance.test_architect_fight import pos
from acceptance.test_departed_member_leaves_fight import assert_departed, depart
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_opportunity_strike import participant
from acceptance.test_paladin_oath_swear import patch_player as patch_oath_player
from acceptance.test_paladin_oath_swear import timed
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_still_anchors import strike
from combat._round_checkpoint_helpers import Fight
from livekit import rtc
from test_aelora_gift import _live_party
from weapon_fixtures import DAGGER

import ability_persistence
import db_queries
from check_resolution import D20Roll
from participant_lifecycle import _setup_party_join


async def test_intercept_recipient_departure_cancels_uncommitted_damage(reset_db_pool) -> None:
    async with defense_fight("warrior") as fight:
        host, guest = fight.players
        first, second = fight.enemies
        await fight.command(
            "declare_phase",
            {"declarations": [{"actor_id": actor, **strike(host, action=SWORD)} for actor in fight.enemies]},
        )
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16)):
            window = await open_stage(fight, "post_roll")
            assert any(r["id"] == "guardian_intercept" and r["actor_id"] == guest for r in window["reactions"])
            spent = await tool_receipt(fight, guest, "activate", {"id": "guardian_intercept"})
            assert not spent.is_error, spent.output
            before = [(await player_row(pid))["hp"] for pid in fight.players]
            lifecycle = await depart(fight, guest)
            try:
                assert_departed(await fight.reload(), guest)
                packets = await fight.drain()
                (receipt,) = [p for p in packets if p.get("outcome") == "target_left"]
                assert receipt["actor_id"] == first
                assert receipt["target_id"] == guest
                assert receipt["resolved"] is False
                (surviving_strike,) = [p for p in packets if p.get("damage", 0) > 0]
                assert surviving_strike["actor_id"] == second
                assert (await player_row(host))["hp"]["current"] == before[0]["current"] - surviving_strike["damage"]
                assert (await player_row(guest))["hp"] == before[1]
            finally:
                await lifecycle.aclose()


@pytest.mark.parametrize("rejoin", [False, True])
async def test_departure_survives_rewind_at_an_untouched_opening(unravel: Fight, rejoin: bool) -> None:
    host, guest = unravel.ids
    await opening(unravel, 0)
    original = deepcopy(unravel.session.combat_state.round_checkpoints[-1]["players"])
    await patch_player(unravel, host, focus={"current": 2, "max": 10})
    await patch_player(unravel, guest, hp={"current": 7, "max": 20})
    await unravel.declare()
    await unravel.finish_round(2)
    await leave_unravel_guest(unravel, guest)
    if rejoin:
        await rejoin_guest(unravel, host, guest)
        await patch_player(unravel, guest, hp={"current": 6, "max": 20})
    before = await player_row(guest)
    await activate(unravel)
    state = await unravel.reload()
    assert state["round_number"] == 1
    assert_departed(unravel.session.combat_state, guest)
    assert (await player_row(host))["focus"] == original[host]["data"]["focus"]
    assert await player_row(guest) == before
    if rejoin:
        await unravel.declare()
        await unravel.finish_round(2)
        assert_departed(unravel.session.combat_state, guest)
        after = await player_row(guest)
        assert after["hp"] == before["hp"]
        assert after.get("conditions") == before.get("conditions")


async def test_departed_timed_oath_lapses_after_checkpoint_rotation(reset_db_pool) -> None:
    async with defense_fight("guardian") as fight:
        host, guest = fight.players
        await patch_oath_player(
            guest, **{"class": "paladin", "divine_favor": {"patron": "zhael", "level": 90, "max": 100}}
        )
        lifecycle = _live_party(fight.sd, host, guest)
        try:
            assert await lifecycle.authorize(guest)
            receipt = await tool_receipt(fight, guest, "query_info", {"kind": "combat"})
            assert not receipt.is_error
            choice = json.loads(receipt.output)["oath_choice"]
            accepted = await tool_receipt(fight, guest, "select", timed(choice, target=fight.enemies[0], deadline=4))
            assert not accepted.is_error, accepted.output
            (oath,) = (await player_row(guest))["oaths"]["records"]
            assert oath["status"] == "active"
            await leave(fight.sd, guest)
            changes = []
            for _ in range(5):
                await fight.command(
                    "declare_phase",
                    {
                        "declarations": [
                            {"kind": "defend", "actor_id": p.id, "reshape": []}
                            for p in (await fight.reload()).participants
                        ]
                    },
                )
                await fight.drain()
                changes.extend(fight.last_result.get("oath_changes", []))
            state = await fight.reload()
            assert all(guest not in checkpoint["players"] for checkpoint in state.round_checkpoints)
            (lapse,) = changes
            assert (lapse["owner_id"], lapse["new_status"], lapse["round_number"]) == (guest, "lapsed", 4)
            (saved,) = (await player_row(guest))["oaths"]["records"]
            assert saved["status"] == "lapsed"
            assert saved["latest_state_change_event_id"] == lapse["event_id"]
        finally:
            await lifecycle.aclose()


async def leave_unravel_guest(fight: Fight, guest: str) -> None:
    assert fight.lifecycle is not None and await fight.lifecycle.authorize(guest)
    await leave(fight.session, guest)


async def rejoin_guest(fight: Fight, host: str, guest: str) -> None:
    assert fight.lifecycle is not None
    await fight.lifecycle.aclose()
    fight.session.room.remote_participants = {host: SimpleNamespace(identity=host)}
    fight.lifecycle = _setup_party_join(fight.session.room, fight.session)
    fight.lifecycle._on_connected(cast(rtc.RemoteParticipant, SimpleNamespace(identity=guest)))
    assert await fight.lifecycle.authorize(guest)
    assert fight.session.party.contains(guest)


async def test_rejoined_departure_cannot_rewind_a_quick_fingers_transfer(unravel: Fight) -> None:
    host, guest = unravel.ids
    await patch_player(unravel, guest, **{"class": "rogue", "equipment": {"main_hand": DAGGER}})
    await ability_persistence.set_elective_equipped(guest, "rogue_quick_fingers", equipped=True)
    await opening(unravel, 0)
    state = unravel.session.combat_state
    enemy = next(p for p in state.participants if p.type == "enemy")
    drop = {"item_id": "wolf_fangs", "quantity": 1, "tainted": False}
    enemy.carried_items = [drop]
    state.spatial["positions"][guest] = {**state.spatial["positions"][enemy.id]}
    enemy.ac = 8
    historical_enemy = next(p for p in state.round_checkpoints[-1]["combat"]["participants"] if p["id"] == enemy.id)
    historical_enemy["carried_items"] = [drop]
    await unravel.write_row(state.to_dict())
    action = {**weapon_attack(guest, enemy.id, "quick_fingers", weapon=DAGGER["name"]), "quick_fingers_mode": "steal"}
    await unravel.declare(action)
    with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(19)):
        result = await unravel.call("resolve_phase")
        packets = list(result["packets"])
        for _ in range(6):
            offer = result.get("fate_offer")
            if offer is None:
                break
            result = await unravel.call(
                "activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original"
            )
            packets.extend(result["packets"])
        attacks = [p for p in packets if p["actor_id"] == guest and p.get("quick_fingers")]
        assert len(attacks) == 1, (packets, result)
        (attack,) = attacks
        assert attack["quick_fingers"]["stolen"]["item_id"] == drop["item_id"]
        await unravel.finish_round(2)
    await leave_unravel_guest(unravel, guest)
    await rejoin_guest(unravel, host, guest)
    assert any(item["id"] == drop["item_id"] for item in await db_queries.get_player_inventory(guest))
    assert unravel.session.combat_state.get_participant(enemy.id).carried_items == []
    await assert_refused(unravel, "enemy pockets changed")


@pytest.mark.parametrize("departing_roller", [False, True])
async def test_departure_drops_only_its_ally_continuation(reset_db_pool, departing_roller: bool) -> None:
    async with defense_fight("warrior", fate=True) as fight:
        host, guest = fight.players
        first, second = fight.enemies
        state = fight.sd.combat_state
        assert state is not None
        participant(state, host).initiative = 21
        participant(state, guest).initiative = 25 if departing_roller else 20
        participant(state, first).ac = 8
        assert state.spatial is not None
        state.spatial["positions"].update({host: pos(0), first: pos(0, 5), guest: pos(5), second: pos(5, 5)})
        before = participant(state, first).hp_current
        await fight.persist()
        await fight.command(
            "declare_phase",
            {
                "declarations": [
                    weapon_attack(host, first, ""),
                    weapon_attack(guest, second, ""),
                ]
            },
        )
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16)):
            paused = (await fight.command("resolve_phase", {}))["fate_offer"]
            assert paused["roller_id"] == (guest if departing_roller else host)
            lifecycle = await depart(fight, guest)
            try:
                assert_departed(await fight.reload(), guest)
                if not departing_roller:
                    assert fight.sd.fate_offer is not None and fight.sd.fate_offer.id == paused["offer_id"]
                packets = []
                for _ in range(8):
                    result = await fight.command("resolve_phase", {})
                    packets.extend(result.get("settled_fate", {}).get("packets", []))
                    packets.extend(result["packets"])
                    if (await fight.reload()).round_number == 2:
                        break
                else:
                    pytest.fail("The next round did not open")
                assert all(p["actor_id"] != guest for p in packets)
                assert any(p["actor_id"] == host and p.get("hit") for p in packets), packets
                assert participant(await fight.reload(), first).hp_current < before
            finally:
                await lifecycle.aclose()


@pytest.mark.parametrize("host_targeted", [True, False])
async def test_ally_cast_lands_on_the_targets_that_remain(reset_db_pool, host_targeted: bool) -> None:
    spell = "divine_bless"
    async with defense_fight("cleric", library=((0, spell),)) as fight:
        host, guest = fight.players
        targets = [host, guest] if host_targeted else [guest]
        bless = {"actor_id": host, "kind": "ability", "action": spell, "targets": targets, "argument_type": ""}
        await fight.command("declare_phase", {"declarations": [bless]})
        before = await player_row(host)
        lifecycle = await depart(fight, guest)
        try:
            packets = await fight.drain()
            left = [p for p in packets if p.get("outcome") == "target_left"]
            spent = (await player_row(host))["focus"]["current"] < before["focus"]["current"]
            state = await fight.reload()
            blessed = any(c["type"] == "blessed" for c in participant(state, host).conditions)
            assert (spent, blessed, bool(left)) == (host_targeted, host_targeted, not host_targeted)
            if left:
                assert (left[0]["actor_id"], left[0]["target_id"], left[0]["resolved"]) == (host, guest, False)
            assert_departed(state, guest)
        finally:
            await lifecycle.aclose()


async def test_departed_casters_guiding_light_expires_before_survivor_attacks(reset_db_pool) -> None:
    spell = "divine_guiding_light"
    async with defense_fight("warrior", ally_archetype="cleric", library=((1, spell),)) as fight:
        host, guest = fight.players
        foe = fight.enemies[0]
        await fight.command(
            "declare_phase",
            {
                "declarations": [
                    {"actor_id": guest, "kind": "ability", "action": spell, "targets": [foe], "argument_type": ""},
                ]
            },
        )
        await fight.drain()
        state = await fight.reload()
        assert any(c["type"] == "guiding_light_mark" for c in participant(state, foe).conditions)
        lifecycle = await depart(fight, guest)
        try:
            await fight.command("declare_phase", {"declarations": [weapon_attack(host, foe, "")]})
            with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate_pair(3, 17)):
                packets = await fight.drain()
            (packet,) = [p for p in packets if p["actor_id"] == host and "hit" in p]
            assert packet["roll"] == 3, packet
        finally:
            await lifecycle.aclose()


async def test_departed_counteractor_keeps_the_committed_attack_receipt(reset_db_pool) -> None:
    from acceptance.counter_reactions_harness import RIPOSTE, WEAPON, counter_fight, react
    from acceptance.test_bark_skin import keep_original

    async with counter_fight(RIPOSTE, gear=WEAPON, fate=True) as fight:
        departing, survivor = fight.players
        enemy = fight.enemies[0]
        before = participant(await fight.reload(), enemy).hp_current
        await fight.command("declare_phase", {"declarations": [{"actor_id": enemy, **strike(departing, action=SWORD)}]})
        faces = iter((1, 18))
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(next(faces))):
            for _ in range(6):
                result = await fight.command("resolve_phase", {})
                if offer := result.get("fate_offer"):
                    result = await keep_original(fight, offer)
                if (window := result["next"]["waiting_on"]) and any(r["id"] == RIPOSTE for r in window["reactions"]):
                    break
            else:
                pytest.fail("Riposte was never offered")
            await react(fight, RIPOSTE)
            result = await fight.command("resolve_phase", {})
            assert result["fate_offer"]["roller_id"] == departing
            lifecycle = await depart(fight, departing)
            try:
                await fight.reload()
                receipt = await tool_receipt(fight, survivor, "resolve_phase", {})
                assert not receipt.is_error, receipt.output
                packets = json.loads(receipt.output)["packets"]
                (attack,) = [p for p in packets if p["actor_id"] == enemy and p.get("action") == SWORD]
                assert attack["hit"] is False and attack["roll"] == 1
                assert not any(p.get("counter_attack") or p.get("outcome") == "target_left" for p in packets)
                assert participant(await fight.reload(), enemy).hp_current == before
            finally:
                await lifecycle.aclose()


async def test_order_from_departed_marshal_is_removed_on_reload_and_rewind(unravel: Fight) -> None:
    from acceptance.test_valdris_party_yield import ability_action

    host, guest = unravel.ids
    await patch_player(unravel, guest, **{"class": "marshal", "level": 8})
    await opening(unravel, 0)
    foe = next(p.id for p in unravel.session.combat_state.participants if p.type == "enemy")
    await unravel.declare(ability_action(guest, "marshal_direct_strike", host, foe))
    await unravel.finish_round(2)
    assert unravel.session.combat_state.order_riders[host][0]["source_id"] == guest
    await unravel.declare()
    await unravel.finish_round(3)
    await leave_unravel_guest(unravel, guest)
    await unravel.reload()
    await activate(unravel)
    state = await unravel.reload()
    assert state["round_number"] == 2
    assert host not in state["order_riders"]
    assert_departed(unravel.session.combat_state, guest)


@pytest.mark.parametrize("guest_first", [False, True])
async def test_departure_during_reshape_preserves_surviving_floor_work(reset_db_pool, guest_first: bool) -> None:
    from _zhael_fate_fixtures import defend
    from acceptance._capstone_helpers import _damage_die
    from acceptance.mawling_harness import MawlingHarness
    from acceptance.test_architect_fight import WORKS, enter
    from acceptance.test_architect_terrain import declare, set_favor
    from acceptance.test_bark_skin import keep_original

    fight = MawlingHarness()
    try:
        await fight.prepare((20, 20), companion=None, location=WORKS)
        state = await enter(fight)
        host, guest = fight.players
        first, second = (guest, host) if guest_first else (host, guest)
        assert state.architect_encounter is not None and state.spatial is not None
        owner = state.architect_encounter["owner_id"]
        state.participants.sort(key=lambda p: p.id != first)
        state.spatial["positions"].update({first: pos(6), second: pos(7), owner: pos(5, 0, 5)})
        await fight.persist()
        await set_favor(fight, "zhael", 40)
        floor = {"kind": "open_floor", "min": pos(5, -5), "max": pos(7, 5)}
        await declare(fight, {**defend(owner), "reshape": [floor]})
        await fight.command("resolve_phase", {})
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(1)),
            patch("architect_reshape.dice.roll", return_value=_damage_die(8)),
        ):
            paused = await fight.command("resolve_phase", {})
            assert paused["fate_offer"]["roller_id"] == first
            paused = await keep_original(fight, paused["fate_offer"])
            assert paused["fate_offer"]["roller_id"] == second
            state = await fight.reload()
            assert state.architect_encounter is not None and first in state.architect_encounter["pits"]
            guest_hp = (await player_row(guest))["hp"]
            lifecycle = await depart(fight, guest)
            try:
                await fight.reload()
                if guest_first:
                    result = await keep_original(fight, paused["fate_offer"])
                else:
                    result = await fight.command("resolve_phase", {})
                (floor_receipt,) = [shape for p in result["packets"] for shape in p.get("reshape", [])]
                results = {p["target_id"]: p for p in floor_receipt["results"]}
                assert results[host]["damage"] == 8
                if guest_first:
                    assert results[guest]["damage"] == 8
                else:
                    assert results[guest]["outcome"] == "target_left"
                assert (await player_row(guest))["hp"] == guest_hp
                state = await fight.reload()
                assert state.architect_encounter is not None
                assert state.architect_encounter["pits"] == {host: floor_receipt["section_id"]}
            finally:
                await lifecycle.aclose()
    finally:
        await fight.close()


async def test_focus_mark_from_departed_source_cannot_block_a_survivor_swing(reset_db_pool) -> None:
    from combat_marks import resolve_mark_action

    async with defense_fight("warrior") as fight:
        host, guest = fight.players
        foe = fight.enemies[0]
        state = await fight.reload()
        resolve_mark_action(state, state.get_participant(guest), state.get_participant(foe), "command")
        await fight.persist()
        lifecycle = await depart(fight, guest)
        try:
            await fight.command("declare_phase", {"declarations": [weapon_attack(host, foe, "")]})
            with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16)):
                packets = await fight.drain()
            assert any(p["actor_id"] == host and p.get("hit") for p in packets)
        finally:
            await lifecycle.aclose()


async def test_departed_hearthfire_source_leaves_a_working_fixed_zone(reset_db_pool) -> None:
    from acceptance._enemy_opportunity_helpers import move

    async with defense_fight("warrior", ally_archetype="warden") as fight:
        host, guest = fight.players
        foe = fight.enemies[0]
        await patch_oath_player(guest, divine_favor={"patron": "aelora", "level": 90, "max": 100})
        state = await fight.reload()
        assert state.spatial is not None
        state.spatial["positions"].update({host: pos(0), guest: pos(5), foe: pos(-25)})
        participant(state, guest).attributes["wisdom"] = 16
        await fight.persist()
        lit = await tool_receipt(fight, guest, "activate", {"id": "aelora_hearthfire"})
        assert not lit.is_error, lit.output
        lifecycle = await depart(fight, guest)
        try:
            await fight.reload()
            await fight.command("declare_phase", {"declarations": [move(foe, -5)]})
            with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(1)):
                packets = await fight.drain()
            (entry,) = [entry for p in packets for entry in p.get("hearthfire_entries", [])]
            assert (entry["source_id"], entry["mover_id"], entry["dc"], entry["success"]) == (guest, foe, 12, False)
            state = await fight.reload()
            assert state.spatial is not None
            assert state.spatial["positions"][foe]["x"] == pytest.approx(-10)
        finally:
            await lifecycle.aclose()


async def test_departed_taunt_source_does_not_block_future_enemy_targeting(reset_db_pool) -> None:
    from acceptance.test_valdris_party_yield import ability_action

    async with defense_fight("guardian", ally_archetype="warrior") as fight:
        host, guest = fight.players
        foe = fight.enemies[0]
        await ability_persistence.set_elective_equipped(guest, "warrior_taunt", equipped=True)
        await fight.command("declare_phase", {"declarations": [ability_action(guest, "warrior_taunt", foe)]})
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(1)):
            packets = await fight.drain()
        assert any(p.get("condition_inflicted") == "taunted" for p in packets)
        lifecycle = await depart(fight, guest)
        try:
            await fight.reload()
            await fight.command("declare_phase", {"declarations": [{"actor_id": foe, **strike(host, action=SWORD)}]})
            with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16)):
                packets = await fight.drain()
            assert any(p["actor_id"] == foe and p.get("damage", 0) > 0 for p in packets)
        finally:
            await lifecycle.aclose()
