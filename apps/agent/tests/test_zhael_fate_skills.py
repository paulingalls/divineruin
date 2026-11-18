from contextlib import nullcontext
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import defend
from _zhael_fate_skills_fixtures import (
    DESTINATION,
    DISCOVER,
    FATE,
    GATHER,
    INSPIRED,
    JOURNAL,
    ORIGIN,
    SKILL,
    SOCIAL,
    argument,
    declarations,
    herb_node,
    place_party,
    prepare_discovery,
    quantity,
    quest_stage,
)
from _zhael_fate_skills_fixtures import argument_scene as argument_scene
from _zhael_fate_skills_fixtures import party as party
from _zhael_fate_skills_fixtures import travel_quest as travel_quest
from acceptance._capstone_helpers import _d20
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from voice_condition_fixtures import participant

import db_mutations
import db_mutations_gathering
import db_queries
from db_content_queries import get_gathering_nodes_at_location
from party_state import PartyState
from patron_gifts import VEYTHAR_INSIGHT


def event_types(session):
    return [event["type"] for event in published_payloads(session.room)]


async def keep(call, offer):
    choice = {"id": FATE, "offer_id": offer["offer_id"]}
    await call(0, "activate", **choice)
    result = await call(0, "activate", **choice, keep="reroll")
    with pytest.raises(ToolError, match="current Fate"):
        await call(0, "activate", **choice, keep="reroll")
    return result


@pytest.mark.parametrize("new_standing", [None, "unfriendly"])
async def test_ally_social_sway_waits_and_uses_current_standing(world, party, new_standing):
    call, _ = party
    host, guest = world.ids
    session = world.ctx.userdata
    npc = SOCIAL["npc_id"]
    await db_mutations.set_npc_disposition(npc, guest, "neutral", "setup")
    with patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(20)]):
        offer = (await call(1, "check", roll=SOCIAL))["fate_offer"]
        assert offer["roller_id"] == guest
        assert await db_queries.get_npc_disposition(npc, guest) == "neutral"
        assert (await row(world))["conditions"] == INSPIRED
        assert not event_types(session)
        if new_standing:
            await db_mutations.set_npc_disposition(npc, guest, new_standing, "another session")
        kept = await keep(call, offer)
    expected = "friendly" if new_standing else "trusted"
    assert (kept["previous_disposition"], kept["new_disposition"]) == (new_standing or "neutral", expected)
    assert await db_queries.get_npc_disposition(npc, guest) == expected
    assert await db_queries.get_npc_disposition(npc, host) is None
    assert (await row(world))["conditions"] == []
    assert (await row(world, 0))["conditions"] == INSPIRED
    assert event_types(session) == ["dice_roll", "disposition_changed"]


@pytest.mark.parametrize("depleted", [False, True])
async def test_ally_gather_waits_and_selects_from_current_nodes(world, party, depleted):
    call, _ = party
    session = world.ctx.userdata
    host, guest = world.ids
    await place_party(world, DESTINATION)
    await world.pool.execute(
        "INSERT INTO skill_advancement (player_id,skill_id,tier,use_counter) VALUES ($1,'nature','expert',0)", guest
    )
    async with herb_node(world) as node_id:

        async def node():
            return next(n for n in await get_gathering_nodes_at_location(DESTINATION) if n["id"] == node_id)

        with patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(20)]):
            offer = (await call(1, "check", roll=GATHER))["fate_offer"]
            assert offer["roller_id"] == guest
            assert (await node())["quantity"] == 1 and not (await node())["discovered"]
            assert await db_queries.get_player_inventory(guest) == []
            assert (await row(world))["conditions"] == INSPIRED
            assert not event_types(session)
            if depleted:
                await db_mutations_gathering.deplete_node_quantity(node_id, 1, conn=world.pool)
            kept = await keep(call, offer)
        assert (await node())["quantity"] == 0
        assert (await node())["discovered"] is not depleted
        assert kept["node_revealed"] == (None if depleted else node_id)
    assert kept["materials"].count("quality_wood") == 2
    assert kept["materials"].count("plant_fiber") == (0 if depleted else 1)
    for item in set(kept["materials"]):
        assert await quantity(guest, item) == kept["materials"].count(item)
    assert await db_queries.get_player_inventory(host) == []
    assert (await row(world))["conditions"] == []
    assert event_types(session).count("dice_roll") == 1
    assert event_types(session).count("hidden_revealed") == int(not depleted)
    assert event_types(session).count("inventory_updated") == 1
    assert event_types(session).count("play_sound") == 1
    assert not session.session_items_found
    assert session.player_summary_metrics[guest]["items_found"]


@pytest.mark.parametrize("kept_face,party_quest", [(20, True), (1, True), (20, False)])
async def test_ally_discovery_waits_before_granting_and_advances_primary_quest(world, party, kept_face, party_quest):
    call, _ = party
    host, guest = world.ids
    session = world.ctx.userdata
    if party_quest:
        await prepare_discovery(world)
    else:
        await place_party(world, "greyvale_ruins_entrance")
    quest_id = "greyvale_anomaly"
    with patch("check_resolution.dice_roll", side_effect=[_d20(21 - kept_face), _d20(kept_face)]):
        offer = (await call(1, "check", roll=DISCOVER))["fate_offer"]
        assert offer["roller_id"] == guest
        assert not (await row(world))["flags"]
        assert (await row(world))["conditions"] == INSPIRED
        if party_quest:
            assert await quest_stage(host, quest_id) == 3
        else:
            session.party.members.extend(PartyState.solo("new_ally").members)
        assert not session.attempted_discoveries
        assert not event_types(session)
        kept = await keep(call, offer)
    discovered = kept_face == 20
    assert kept["outcome"] == ("discovered" if discovered else "not_found")
    assert (await row(world))["flags"].get(f"{JOURNAL}.discovered", False) == discovered
    assert await quantity(guest, JOURNAL) == int(discovered)
    assert await db_queries.get_inventory_item(host, JOURNAL) is None
    if party_quest:
        assert await quest_stage(host, quest_id) == 3 + discovered
    assert session.attempted_discoveries == {f"{guest}:investigation:{JOURNAL}"}
    assert (await row(world))["conditions"] == []
    assert event_types(session).count("dice_roll") == 1
    assert event_types(session).count("hidden_revealed") == int(discovered)
    assert event_types(session).count("quest_updated") == int(discovered and party_quest)


@pytest.mark.parametrize("kept_face", [20, 1, None], ids=["arrival", "lost", "established-road"])
async def test_ally_navigation_waits_before_party_writes(world, party, travel_quest, kept_face):
    call, agent = party
    host, guest = world.ids
    session = world.ctx.userdata
    original_players = [await row(world, i) for i in range(2)]
    location = DESTINATION if kept_face else "greyvale_south_road"
    hours = 4 if kept_face != 1 else 12
    with patch(
        "check_resolution.dice_roll", side_effect=[_d20(21 - kept_face), _d20(kept_face)] if kept_face else []
    ) as d20:
        result = await call(
            1,
            "travel",
            destination_id=location,
            mode="scenic",
            hours=hours,
            forced_march=hours > 8,
        )
        if kept_face:
            assert result["fate_offer"]["roller_id"] == guest
            assert [await row(world, i) for i in range(2)] == original_players
            assert session.location_id == ORIGIN
            assert not event_types(session)
            assert await quest_stage(host, travel_quest) == 0
            result = await keep(call, result["fate_offer"])
        else:
            assert "fate_offer" not in result and not d20.called
    arrived = kept_face != 1
    assert result["arrived"] == arrived
    assert result["time_cost"] == (16 if not arrived else 4)
    for i in range(2):
        player = await row(world, i)
        assert player["travel_hours_since_rest"] == hours
        assert player["location_id"] == (location if arrived else ORIGIN)
        assert player.get("travel_state") == (
            None
            if arrived
            else {
                "destination": DESTINATION,
                "mode": "scenic",
                "wrong_area": True,
            }
        )
        assert ("inspired" in {c["type"] for c in player["conditions"]}) == (i == 0 or kept_face is None)
        assert [c["stacks"] for c in player["conditions"] if c["type"] == "exhausted"] == ([] if arrived else [1])
    assert event_types(session).count("location_changed") == int(arrived)
    navigation = [e for e in published_payloads(session.room) if e.get("roll_type") == "navigation_check"]
    assert [event["skill"] for event in navigation] == ([] if kept_face is None else ["survival"])
    assert await quest_stage(host, travel_quest) == int(kept_face == 20)
    if kept_face == 20:
        assert agent._agent_type == result["quest_updates"][0]["scene_transition"]["region"] == "wilderness"
    else:
        assert agent._agent_type == "city"


@pytest.mark.parametrize("roll", [SKILL, DISCOVER], ids=["skill", "discover"])
@pytest.mark.parametrize("decision", ["reroll", "original", "decline"])
async def test_veythar_reroll_gets_its_own_fate_offer(world, party, roll, decision):
    call, _ = party
    host, guest = world.ids
    session = world.ctx.userdata
    if roll is DISCOVER:
        await prepare_discovery(world)

    async def uses():
        return await world.pool.fetchval(
            "SELECT use_counter FROM skill_advancement WHERE player_id=$1 AND skill_id=$2",
            guest,
            roll["skill"],
        )

    with patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(2), _d20(20)]) as die:
        original = (await call(1, "check", roll=roll))["fate_offer"]
        await call(0, "activate", id=FATE, offer_id=original["offer_id"], keep="original")
        expected_uses = 1 if roll is SKILL else None
        assert await uses() == expected_uses
        events = published_payloads(session.room)
        held = (await call(1, "activate", id=VEYTHAR_INSIGHT))["fate_offer"]
        assert held["offer_id"] != original["offer_id"] and held["roller_id"] == guest
        assert (await row(world))["patron_gifts"][VEYTHAR_INSIGHT] == {"spent": True, "pending": None}
        assert published_payloads(session.room) == events
        assert await quantity(guest, JOURNAL) == 0
        choice = {"id": FATE, "offer_id": held["offer_id"]}
        if decision != "decline":
            await call(0, "activate", **choice)
        kept = await call(0, "activate", **choice, keep="original" if decision == "decline" else decision)
    success = decision == "reroll"
    assert kept["roll"] == (20 if success else 2) and "reroll_offer" not in kept
    assert die.call_count == (2 if decision == "decline" else 3)
    assert await uses() == expected_uses
    expected_spend = None if decision == "decline" else {"spent": True}
    assert (await row(world, 0)).get("patron_gifts", {}).get(FATE) == expected_spend
    if roll is DISCOVER:
        assert await quantity(guest, JOURNAL) == int(success)
        assert await quantity(host, JOURNAL) == 0
        assert await quest_stage(host, "greyvale_anomaly") == 3 + success
        assert session.attempted_discoveries == {f"{guest}:investigation:{JOURNAL}"}


@pytest.mark.parametrize("settlement", ["choice", "reload", "departed", "replaced"])
async def test_group_deescalation_holds_one_argument(world, party, argument_scene, settlement):
    reloaded = settlement == "reload"
    call, _ = party
    host, guest = world.ids
    session = world.ctx.userdata
    await call(0, "declare_phase", declarations=declarations(argument_scene, defend(host), argument(guest)))
    with patch("check_resolution.dice_roll", side_effect=[_d20(20)] if reloaded else [_d20(1), _d20(20)]) as roll:
        offer = (await call(0, "resolve_phase"))["fate_offer"]
        assert offer["roller_id"] == guest and offer["die"] == (20 if reloaded else 1)
        assert (await row(world))["focus"]["current"] == 0
        assert participant(session.combat_state, guest).conditions == INSPIRED
        assert session.combat_state is not None
        assert not session.combat_state.deescalation_scene.cumulative_shift
        assert session.combat_state.deescalation_scene.round_counter == 0
        assert not [event for event in published_payloads(session.room) if event.get("roll_type") == "de_escalate"]
        if settlement == "replaced":
            replacement = deepcopy(argument_scene)
            replacement.combat_id = uuid4().hex
            session.combat_state = replacement
            cancelled = (await call(0, "query_info", kind="inventory"))["settled_fate"]
            assert cancelled["outcome"] == "cancelled" and "no longer active" in cancelled["reason"]
            assert session.combat_state is replacement and replacement.deescalation_scene.round_counter == 0
            assert session.fate_offer is None and roll.call_count == 1
            assert (await row(world))["focus"]["current"] == 0
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
    assert [event.get("roll_type") for event in published_payloads(session.room)].count("de_escalate") == 1


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


@pytest.mark.parametrize("producer", ["skill", "insight", "discover", "insight_discover", "social", "gather", "travel"])
async def test_departed_roller_cancels_the_held_operation(world, party, producer):
    call, _ = party
    guest = world.ids[1]
    session = world.ctx.userdata
    if producer == "gather":
        await place_party(world, DESTINATION)
    if "discover" in producer:
        await prepare_discovery(world)
    checks = {
        "skill": SKILL,
        "insight": SKILL,
        "discover": DISCOVER,
        "insight_discover": DISCOVER,
        "social": SOCIAL,
        "gather": GATHER,
    }
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        if producer == "travel":
            held = await call(1, "travel", destination_id=DESTINATION, mode="scenic")
        else:
            held = await call(1, "check", roll=checks[producer])
        if producer.startswith("insight"):
            await call(0, "activate", id=FATE, offer_id=held["fate_offer"]["offer_id"], keep="original")
            held = await call(1, "activate", id=VEYTHAR_INSIGHT)
        assert held["fate_offer"]["roller_id"] == guest
        player_before = await row(world)
        events_before = event_types(session).count("dice_roll")
        session.multiplayer_owner.lifecycle.mark_departed(guest)
        cancelled = (await call(0, "query_info", kind="inventory"))["settled_fate"]
    assert cancelled["outcome"] == "cancelled" and "no longer present" in cancelled["reason"]
    assert session.fate_offer is None
    assert await row(world) == player_before
    assert event_types(session).count("dice_roll") == events_before


@pytest.mark.parametrize("change", ["origin", "roster", "db-location", "revealed", "foraged-out"])
async def test_held_operation_surfaces_changed_precondition(world, party, change):
    call, _ = party
    host, guest = world.ids
    session = world.ctx.userdata
    if change == "revealed":
        await prepare_discovery(world)
    # Millhaven has no resource_table, so its one finite node is all there is to forage.
    node = herb_node(world, ORIGIN) if change == "foraged-out" else nullcontext()
    async with node as node_id:
        with patch("check_resolution.dice_roll", return_value=_d20(20)):
            if change == "origin":
                held = await call(1, "check", roll=SOCIAL)
                session.location_id = DESTINATION
                expected = "original location"
            elif change == "revealed":
                held = await call(1, "check", roll=DISCOVER)
                await db_mutations.set_player_flag(guest, f"{JOURNAL}.discovered", True)
                expected = "already been revealed"
            elif change == "foraged-out":
                held = await call(1, "check", roll=GATHER)
                assert node_id is not None
                await db_mutations_gathering.deplete_node_quantity(node_id, 1, conn=world.pool)
                expected = "nothing left to forage"
            else:
                held = await call(1, "travel", destination_id=DESTINATION, mode="scenic")
                if change == "roster":
                    session.party.members.extend(PartyState.solo("new_ally").members)
                    expected = "party roster"
                else:
                    await db_mutations.update_player_location(host, DESTINATION)
                    expected = "original location"
            assert held["fate_offer"]["roller_id"] == guest
            before = [await row(world, i) for i in range(2)]

            # Other workers' herb_node fixtures come and go at the same location on the shared dev DB.
            async def nodes():
                rows = await get_gathering_nodes_at_location(ORIGIN)
                return [n for n in rows if not n["id"].startswith("fate_herb_") or n["id"] == node_id]

            nodes_before = await nodes()
            cancelled = (await call(0, "query_info", kind="inventory"))["settled_fate"]
            assert await nodes() == nodes_before
    assert cancelled["outcome"] == "cancelled" and expected in cancelled["reason"]
    assert [await row(world, i) for i in range(2)] == before
    assert await db_queries.get_player_inventory(guest) == []
    assert not session.attempted_discoveries
    assert "location_changed" not in event_types(session) and "dice_roll" not in event_types(session)
