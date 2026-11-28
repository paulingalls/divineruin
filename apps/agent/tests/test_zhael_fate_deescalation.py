from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import defend
from _zhael_fate_skills_fixtures import FATE, INSPIRED, ORIGIN, argument, declarations, event_types, keep
from _zhael_fate_skills_fixtures import argument_scene as argument_scene
from _zhael_fate_skills_fixtures import party as party
from acceptance._capstone_helpers import _d20
from sample_fixtures import published_payloads
from voice_condition_fixtures import participant

import db_mutations


@pytest.mark.parametrize("settlement", ["choice", "reload", "departed", "replaced"])
async def test_group_deescalation_holds_one_argument(world, party, argument_scene, settlement):
    reloaded = settlement == "reload"
    call, _ = party
    host, guest = world.ids
    session = world.ctx.userdata

    def argument_packets():
        return [event for event in published_payloads(session.room) if event.get("roll_type") == "de_escalate"]

    await call(0, "declare_phase", declarations=declarations(argument_scene, defend(host), argument(guest)))
    with patch("check_resolution.dice_roll", side_effect=[_d20(20)] if reloaded else [_d20(1), _d20(20)]) as roll:
        offer = (await call(0, "resolve_phase"))["fate_offer"]
        assert offer["roller_id"] == guest and offer["die"] == (20 if reloaded else 1)
        assert (await row(world))["focus"]["current"] == 0
        assert participant(session.combat_state, guest).conditions == INSPIRED
        assert session.combat_state is not None
        assert not session.combat_state.deescalation_scene.cumulative_shift
        assert session.combat_state.deescalation_scene.round_counter == 0
        assert not argument_packets()
        if settlement == "replaced":
            replacement = deepcopy(argument_scene)
            replacement.combat_id = uuid4().hex
            session.combat_state = replacement
            cancelled = (await call(0, "query_info", kind="inventory"))["settled_fate"]
            assert cancelled["outcome"] == "cancelled" and "no longer active" in cancelled["reason"]
            assert session.combat_state is replacement and replacement.deescalation_scene.round_counter == 0
            assert session.fate_offer is None and roll.call_count == 1
            assert (await row(world))["focus"]["current"] == 0
            assert not argument_packets()
            return
        if settlement == "departed":
            session.multiplayer_owner.lifecycle.mark_departed(guest)
            response = (await call(0, "query_info", kind="inventory"))["settled_fate"]
            cancelled = next(packet for packet in response["packets"] if packet["actor_id"] == guest)
            assert cancelled["outcome"] == "cancelled" and "no longer present" in cancelled["reason"]
            assert session.fate_offer is None and roll.call_count == 1
            assert (await row(world))["focus"]["current"] == 0
            assert participant(session.combat_state, guest).conditions == INSPIRED
            assert session.combat_state is not None
            assert not session.combat_state.deescalation_scene.cumulative_shift
            assert session.combat_state.deescalation_scene.round_counter == 0
            assert not argument_packets()
            return
        if reloaded:
            session.fate_offer = None
            session.combat_state = await db_mutations.load_combat_state(argument_scene.combat_id)
            kept = await call(0, "resolve_phase")
        else:
            kept = await keep(call, offer)
    assert roll.call_count == (1 if reloaded else 2)
    assert "fate_offer" not in kept
    assert (await row(world))["focus"]["current"] == 0
    assert participant(session.combat_state, guest).conditions == []
    assert session.combat_state is not None
    assert session.combat_state.deescalation_scene.round_counter == 1
    assert session.combat_state.deescalation_scene.cumulative_shift == {"pragmatist": 1, "skeptic": 0}
    assert session.combat_state.deescalation_scene.enemy_dispositions == {
        "pragmatist": "unfriendly",
        "skeptic": "hostile",
    }
    [packet] = argument_packets()
    assert (packet["roll"], packet["modifier"], packet["total"], packet["success"]) == (20, 4, 24, True)
    assert (packet["actor"], packet["round"], packet["surrendered"], packet["living"], packet["ends_combat"]) == (
        argument_scene.get_participant(guest).name,
        1,
        0,
        2,
        False,
    )
    assert (packet["dramatic"], packet["context"]) == (True, "de_escalate")


async def test_two_diplomats_share_a_scene_round_and_terminal_choice_hands_off(world, party, argument_scene):
    call, _ = party
    host, guest = world.ids
    session = world.ctx.userdata
    await configure(
        world,
        "zhael",
        "diplomat",
        location_id=ORIGIN,
        focus={"current": 3, "max": 20},
        attributes={"charisma": 16},
        hp={"current": 30, "max": 30},
    )
    await configure(
        world,
        "veythar",
        "diplomat",
        index=1,
        location_id=ORIGIN,
        focus={"current": 6, "max": 20},
        attributes={"charisma": 24},
        hp={"current": 30, "max": 30},
    )
    await call(0, "declare_phase", declarations=declarations(argument_scene, argument(guest), argument(host)))
    with patch("check_resolution.dice_roll", side_effect=[_d20(20)] * 3) as roll:
        first = (await call(0, "resolve_phase"))["fate_offer"]
        second = (await call(0, "activate", id=FATE, offer_id=first["offer_id"], keep="original"))["fate_offer"]
        assert {first["roller_id"], second["roller_id"]} == {host, guest}
        await call(0, "activate", id=FATE, offer_id=second["offer_id"], keep="original")
        assert session.combat_state is not None
        scene = session.combat_state.deescalation_scene
        assert scene.round_counter == 1 and scene.cumulative_shift == {"pragmatist": 3, "skeptic": 0}
        assert (await row(world, 0))["focus"]["current"] == 0
        assert (await row(world))["focus"]["current"] == 3
        await call(0, "resolve_phase")
        await configure(world, "veythar", "diplomat", index=1, attributes={"charisma": 28})
        await call(
            0, "declare_phase", declarations=declarations(argument_scene, argument(guest, "evidence"), defend(host))
        )
        terminal = (await call(0, "resolve_phase"))["fate_offer"]
        assert terminal["roller_id"] == guest
        agent, handoff = await call(0, "query_info", kind="npc")
    assert roll.call_count == 3
    assert agent is not None and handoff["outcome"] == "deescalated"
    assert session.combat_state is None and session.fate_offer is None
    assert await db_mutations.load_combat_state(argument_scene.combat_id) is None
    assert (await row(world))["focus"]["current"] == 0
    assert event_types(session).count("combat_ended") == 1


async def test_terminal_parley_preserves_a_dismissal_from_the_same_commit(world, party, argument_scene):
    call, _ = party
    host, guest = world.ids
    session = world.ctx.userdata
    await configure(
        world, "zhael", "druid", level=5, focus={"current": 10, "max": 10}, stamina={"current": 6, "max": 6}
    )
    await configure(world, "veythar", "diplomat", index=1, attributes={"charisma": 28})
    druid = participant(argument_scene, host)
    druid.level = 5
    druid.initiative = participant(argument_scene, guest).initiative - 1
    shift = {
        "kind": "ability",
        "actor_id": host,
        "action": "druid_wild_shape",
        "targets": [],
        "argument_type": "grey_wolf",
        "reshape": [],
    }
    await call(0, "declare_phase", declarations=declarations(argument_scene, shift, defend(guest)))
    await call(0, "resolve_phase")
    await call(0, "resolve_phase")
    state = session.combat_state
    form = participant(state, host).wild_shape
    assert form is not None and form["form_id"] == "grey_wolf"
    state.deescalation_scene.cumulative_shift["pragmatist"] = 3
    dismiss = {"kind": "interact", "actor_id": host, "action": "dismiss_wild_shape"}
    await call(0, "declare_phase", declarations=declarations(state, argument(guest, "evidence"), dismiss))
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        offer = (await call(0, "resolve_phase"))["fate_offer"]
        assert offer["roller_id"] == guest
        _, receipt = await call(0, "query_info", kind="npc")
    event = next(e for e in published_payloads(session.room) if e["type"] == "combat_ended")
    assert receipt["outcome"] == "deescalated"
    fact = {"actor_id": host, "form_id": "grey_wolf", "reason": "dismissed"}
    assert receipt["wild_shape_ended"] == event["wild_shape_ended"] == [fact]
