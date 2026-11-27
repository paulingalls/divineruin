import json
from copy import deepcopy
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from _zhael_unravel_fixtures import activate, opening, patch_player
from _zhael_unravel_fixtures import unravel as unravel
from acceptance import test_departed_member_leaves_fight as departure
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.defensive_reactions_harness import defense_fight, player_row
from acceptance.disruption_reactions_harness import open_stage
from acceptance.test_architect_fight import pos
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_opportunity_strike import participant
from acceptance.test_paladin_oath_swear import patch_player as patch_oath_player
from acceptance.test_paladin_oath_swear import timed
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_valdris_party_yield import ability_action
from combat._round_checkpoint_helpers import Fight
from livekit import rtc

import ability_persistence
from check_resolution import D20Roll
from participant_lifecycle import _setup_party_join


async def test_intercept_recipient_departure_cancels_uncommitted_damage(reset_db_pool) -> None:
    async with defense_fight("warrior") as fight:
        host, guest = fight.players
        first, second = fight.enemies
        await departure.declare(fight, *(departure.swing(actor, host) for actor in fight.enemies))
        with departure.d20(16):
            await open_stage(fight, "post_roll")
            assert not (await tool_receipt(fight, guest, "activate", {"id": "guardian_intercept"})).is_error
            host_hp, guest_hp = [(await player_row(pid))["hp"] for pid in fight.players]
            async with departure.departed(fight, guest):
                departure.assert_departed(await fight.reload(), guest)
                packets = await fight.drain()
                assert departure.target_left(packets) == [(first, guest, False)]
                (hit,) = [p for p in packets if p.get("damage", 0) > 0]
                assert hit["actor_id"] == second
                assert (await player_row(host))["hp"]["current"] == host_hp["current"] - hit["damage"]
                assert (await player_row(guest))["hp"] == guest_hp


async def leave_unravel_guest(fight: Fight, guest: str) -> None:
    assert fight.lifecycle is not None and await fight.lifecycle.authorize(guest)
    await leave(fight.session, guest)


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
        assert unravel.lifecycle is not None
        await unravel.lifecycle.aclose()
        unravel.session.room.remote_participants = {host: SimpleNamespace(identity=host)}
        unravel.lifecycle = _setup_party_join(unravel.session.room, unravel.session)
        unravel.lifecycle._on_connected(cast(rtc.RemoteParticipant, SimpleNamespace(identity=guest)))
        assert await unravel.lifecycle.authorize(guest) and unravel.session.party.contains(guest)
        await patch_player(unravel, guest, hp={"current": 6, "max": 20})
    before = await player_row(guest)
    await activate(unravel)
    assert (await unravel.reload())["round_number"] == 1
    departure.assert_departed(unravel.session.combat_state, guest)
    assert (await player_row(host))["focus"] == original[host]["data"]["focus"]
    assert await player_row(guest) == before
    if rejoin:
        await unravel.declare()
        await unravel.finish_round(2)
        departure.assert_departed(unravel.session.combat_state, guest)
        assert await departure.saved_wounds(guest) == (before["hp"], before.get("conditions"))


async def test_departed_timed_oath_lapses_after_checkpoint_rotation(reset_db_pool) -> None:
    async with defense_fight("guardian") as fight:
        guest = fight.players[1]
        favor = {"patron": "zhael", "level": 90, "max": 100}
        await patch_oath_player(guest, **{"class": "paladin", "divine_favor": favor})
        async with departure.authorized(fight, guest):
            choice = json.loads((await tool_receipt(fight, guest, "query_info", {"kind": "combat"})).output)
            pledge = timed(choice["oath_choice"], target=fight.enemies[0], deadline=4)
            assert not (await tool_receipt(fight, guest, "select", pledge)).is_error
            await leave(fight.sd, guest)
            changes = []
            for _ in range(5):
                await departure.defend_all(fight)
                await fight.drain()
                changes.extend(fight.last_result.get("oath_changes", []))
            assert all(guest not in checkpoint["players"] for checkpoint in (await fight.reload()).round_checkpoints)
            (lapse,) = changes
            assert (lapse["owner_id"], lapse["new_status"], lapse["round_number"]) == (guest, "lapsed", 4)
            (saved,) = (await player_row(guest))["oaths"]["records"]
            assert (saved["status"], saved["latest_state_change_event_id"]) == ("lapsed", lapse["event_id"])


@pytest.mark.parametrize("host_targeted", [True, False])
async def test_ally_cast_lands_on_the_targets_that_remain(reset_db_pool, host_targeted: bool) -> None:
    spell = "divine_bless"
    async with defense_fight("cleric", library=((0, spell),)) as fight:
        host, guest = fight.players
        targets = [host, guest] if host_targeted else [guest]
        await departure.declare(
            fight, {"actor_id": host, "kind": "ability", "action": spell, "targets": targets, "argument_type": ""}
        )
        focus = (await player_row(host))["focus"]["current"]
        async with departure.departed(fight, guest):
            left = departure.target_left(await fight.drain())
            spent = (await player_row(host))["focus"]["current"] < focus
            state = await fight.reload()
            blessed = any(c["type"] == "blessed" for c in participant(state, host).conditions)
            assert (spent, blessed, left) == (
                host_targeted,
                host_targeted,
                [] if host_targeted else [(host, guest, False)],
            )
            departure.assert_departed(state, guest)


async def test_departed_casters_guiding_light_expires_before_survivor_attacks(reset_db_pool) -> None:
    spell = "divine_guiding_light"
    async with defense_fight("warrior", ally_archetype="cleric", library=((1, spell),)) as fight:
        host, guest = fight.players
        foe = fight.enemies[0]
        await departure.declare(
            fight, {"actor_id": guest, "kind": "ability", "action": spell, "targets": [foe], "argument_type": ""}
        )
        await fight.drain()
        assert any(c["type"] == "guiding_light_mark" for c in participant(await fight.reload(), foe).conditions)
        async with departure.departed(fight, guest):
            await departure.declare(fight, weapon_attack(host, foe, ""))
            with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate_pair(3, 17)):
                (packet,) = [p for p in await fight.drain() if p["actor_id"] == host and "hit" in p]
            assert packet["roll"] == 3, packet


async def test_departed_counteractor_keeps_the_committed_attack_receipt(reset_db_pool) -> None:
    from acceptance.counter_reactions_harness import RIPOSTE, WEAPON, counter_fight, react
    from acceptance.test_bark_skin import keep_original

    async with counter_fight(RIPOSTE, gear=WEAPON, fate=True) as fight:
        departing, survivor = fight.players
        enemy = fight.enemies[0]
        before = participant(await fight.reload(), enemy).hp_current
        await departure.declare(fight, departure.swing(enemy, departing))
        faces = iter((1, 18))
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(next(faces))):
            for _ in range(6):
                result = await fight.command("resolve_phase", {})
                if offer := result.get("fate_offer"):
                    result = await keep_original(fight, offer)
                if (window := result["next"]["waiting_on"]) and any(r["id"] == RIPOSTE for r in window["reactions"]):
                    break
            await react(fight, RIPOSTE)
            assert (await fight.command("resolve_phase", {}))["fate_offer"]["roller_id"] == departing
            async with departure.departed(fight, departing):
                await fight.reload()
                receipt = await tool_receipt(fight, survivor, "resolve_phase", {})
                packets = json.loads(receipt.output)["packets"]
                (attack,) = [p for p in packets if p["actor_id"] == enemy and p.get("action") == SWORD]
                assert (attack["hit"], attack["roll"]) == (False, 1)
                assert not any(p.get("counter_attack") or p.get("outcome") == "target_left" for p in packets)
                assert participant(await fight.reload(), enemy).hp_current == before


async def test_order_from_departed_marshal_is_removed_on_reload_and_rewind(unravel: Fight) -> None:
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
    assert state["round_number"] == 2 and host not in state["order_riders"]
    departure.assert_departed(unravel.session.combat_state, guest)


@pytest.mark.parametrize("guest_first", [False, True])
async def test_departure_during_reshape_preserves_surviving_floor_work(reset_db_pool, guest_first: bool) -> None:
    from _zhael_fate_fixtures import defend
    from acceptance._capstone_helpers import _damage_die
    from acceptance.mawling_harness import MawlingHarness
    from acceptance.test_architect_fight import WORKS, enter
    from acceptance.test_architect_terrain import declare as declare_terrain
    from acceptance.test_architect_terrain import set_favor
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
        await declare_terrain(
            fight, {**defend(owner), "reshape": [{"kind": "open_floor", "min": pos(5, -5), "max": pos(7, 5)}]}
        )
        await fight.command("resolve_phase", {})
        with departure.d20(1), patch("architect_reshape.dice.roll", return_value=_damage_die(8)):
            offer = (await keep_original(fight, (await fight.command("resolve_phase", {}))["fate_offer"]))["fate_offer"]
            assert offer["roller_id"] == second
            assert first in departure.present((await fight.reload()).architect_encounter)["pits"]
            guest_hp = (await player_row(guest))["hp"]
            async with departure.departed(fight, guest):
                await fight.reload()
                result = await (keep_original(fight, offer) if guest_first else fight.command("resolve_phase", {}))
                (floor,) = [shape for p in result["packets"] for shape in p.get("reshape", [])]
                results = {p["target_id"]: p for p in floor["results"]}
                assert results[host]["damage"] == 8
                expected = {"damage": 8} if guest_first else {"outcome": "target_left"}
                assert expected.items() <= results[guest].items()
                assert (await player_row(guest))["hp"] == guest_hp
                assert departure.present((await fight.reload()).architect_encounter)["pits"] == {
                    host: floor["section_id"]
                }
    finally:
        await fight.close()


async def test_departed_hearthfire_source_leaves_a_working_fixed_zone(reset_db_pool) -> None:
    from acceptance._enemy_opportunity_helpers import move

    async with defense_fight("warrior", ally_archetype="warden") as fight:
        host, guest = fight.players
        foe = fight.enemies[0]
        await patch_oath_player(guest, divine_favor={"patron": "aelora", "level": 90, "max": 100})
        state = await fight.reload()
        departure.present(state.spatial)["positions"].update({host: pos(0), guest: pos(5), foe: pos(-25)})
        participant(state, guest).attributes["wisdom"] = 16
        await fight.persist()
        assert not (await tool_receipt(fight, guest, "activate", {"id": "aelora_hearthfire"})).is_error
        async with departure.departed(fight, guest):
            await fight.reload()
            await departure.declare(fight, move(foe, -5))
            with departure.d20(1):
                (entry,) = [entry for p in await fight.drain() for entry in p.get("hearthfire_entries", [])]
            assert (entry["source_id"], entry["mover_id"], entry["dc"], entry["success"]) == (guest, foe, 12, False)
            assert departure.present((await fight.reload()).spatial)["positions"][foe]["x"] == pytest.approx(-10)


async def test_departed_taunt_source_does_not_block_future_enemy_targeting(reset_db_pool) -> None:
    async with defense_fight("guardian", ally_archetype="warrior") as fight:
        host, guest = fight.players
        foe = fight.enemies[0]
        await ability_persistence.set_elective_equipped(guest, "warrior_taunt", equipped=True)
        await departure.declare(fight, ability_action(guest, "warrior_taunt", foe))
        with departure.d20(1):
            assert any(p.get("condition_inflicted") == "taunted" for p in await fight.drain())
        async with departure.departed(fight, guest):
            await fight.reload()
            await departure.declare(fight, departure.swing(foe, host))
            with departure.d20(16):
                assert any(p["actor_id"] == foe and p.get("damage", 0) > 0 for p in await fight.drain())
