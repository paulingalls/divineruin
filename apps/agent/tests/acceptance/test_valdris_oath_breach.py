"""Oath of Justice at the registered combat and patron boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools
from _zhael_fate_skills_fixtures import argument
from acceptance.test_paladin_oath_swear import invoke, stored
from acceptance.test_valdris_party_yield import dev_db_pool as dev_db_pool
from acceptance.test_valdris_party_yield import registered, yield_action
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, published_payloads
from session_lifecycle.test_party_connection import _make_mods, _participant, _recording_room
from test_aelora_gift import _live_party
from test_encounter_facts_damage import GOBLIN, OTHER, Fight, dice, fight, goblin_strike
from voice_condition_fixtures import participant

import character_spells
import db_mutations
import db_queries
import oath_breach
from combat_structures import add_wall
from exploration_agent import ExplorationAgent
from participant_lifecycle import _setup_party_join
from session_data import SessionData
from session_hydration import hydrate_patron_ability_session, hydrate_session_state


async def oath_book(actor: str) -> dict:
    book = await stored(actor)
    assert book is not None
    return book


async def swear(session: SessionData) -> dict:
    offer = (await invoke(session, "query_info", kind="abilities"))["oath_choice"]
    return await invoke(session, "select", choice_id=offer["choice_id"], option="justice")


async def opening_miss(world: SimpleNamespace) -> None:
    async with fight(world, "valdris", archetype="paladin") as f:
        registered(f)
        oath = await swear(f.session)
        await configure(world, "valdris", "paladin", index=1, resonance={"current": 0})
        f.session.member_state(f.ally).resonance.current = 0
        with f.session._bind_authenticated_actor(f.ally, 1, lambda *_: None):
            await swear(f.session)
        ally = await row(world, 1)
        packets = await f.round(attack(f.hero, GOBLIN), faces=(1,))
        packet = next(p for p in packets if p["actor_id"] == f.hero)
        assert packet["hit"] is False
        book = await oath_book(f.hero)
        [record] = book["records"]
        assert record["status"] == "broken"
        breach = packet["oath_breach"]
        assert breach["terms"] == ["strike_first"] and breach["oath_id"] == oath["oath_id"]
        marker = book["valdris_breach"]
        assert marker["session_id"] == f.session.session_id
        assert marker["breach_event_id"] == breach["breach_event_id"] == record["latest_state_change_event_id"]
        assert f.session.combat_state.encounter_facts["opening_actors"] == {GOBLIN: f.hero}
        assert await row(world, 1) == ally


SCENARIOS = {"valdris_oath_breach": ("oath_breach:settle", opening_miss, [()])}
LAYER_3 = ("valdris_discern_lies", "valdris_mark_of_justice", "valdris_the_scales_verdict")


def assert_locked(rows: list[dict]) -> None:
    assert [ability["id"] for ability in rows] == list(LAYER_3)
    assert all(row["state"] == "locked" and row["eligible"] and not row["available"] for row in rows)
    assert all("Oath of Justice" in row["reason"] and "broken" in row["reason"] for row in rows)


def patron_packet(f: Fight, actor: str) -> dict:
    for call in reversed(f.session.room.local_participant.publish_data.await_args_list):
        payload = json.loads(call.args[0])
        if payload["type"] == "patron_abilities_updated" and payload["player_id"] == actor:
            assert call.kwargs["destination_identities"] == [actor]
            return payload
    raise AssertionError(f"No patron snapshot for {actor}")


async def test_surrendered_enemy_breaks_oath_after_another_actor_opens(world: SimpleNamespace) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        await configure(
            world, "thyra", "diplomat", index=1, focus={"current": 10, "max": 10}, attributes={"charisma": 26}
        )
        state = f.session.combat_state
        participant(state, f.ally).archetype_id = "diplomat"
        participant(state, GOBLIN).resistance_tags = ["cowardly"]
        participant(state, OTHER).resistance_tags = ["greedy"]
        await swear(f.session)
        await f.call("activate", id="valdris_mark_of_justice", target_id=OTHER)
        await f.round(attack(f.ally, GOBLIN), goblin_strike(OTHER, f.hero), faces=(1, 1))
        packets = await f.round(argument(f.ally, "threat"), faces=(20,))
        scene = next(p["deescalation"] for p in packets if p.get("deescalation"))
        assert {e["id"]: e["surrendered"] for e in scene["per_enemy"]} == {GOBLIN: True, OTHER: False}
        packets = await f.round(attack(f.hero, GOBLIN), faces=(1,))
        assert next(p["oath_breach"]["terms"] for p in packets if "oath_breach" in p) == ["strike_surrendered_enemy"]
        assert (await oath_book(f.hero))["records"][0]["status"] == "broken"
        assert f.session.combat_state.encounter_facts["opening_actors"][GOBLIN] == f.ally
        assert any(c["type"] == "mark_of_justice" for c in participant(f.session.combat_state, OTHER).conditions)
        await character_spells.record_learned(f.hero, "divine_command", "training", is_prepared=True, conn=world.pool)
        cast = {
            "kind": "ability",
            "actor_id": f.hero,
            "action": "divine_command",
            "targets": [OTHER],
            "argument_type": "",
        }
        packets = await f.round(cast)
        result = next(p["cast"] for p in packets if p["actor_id"] == f.hero)
        assert result["wrongdoing"]["target_id"] == OTHER
        assert result["resonance_generated"] == 0


@pytest.mark.parametrize(
    "control", ["charmed", "hostile_first", "ally_first", "legacy", "changed_patron", "rejected", "structure"]
)
async def test_attack_controls(world: SimpleNamespace, control: str) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        await swear(f.session)
        before = await oath_book(f.hero)
        if control == "charmed":
            participant(f.session.combat_state, f.hero).conditions = [
                {"type": "charmed", "source": OTHER, "duration": 3}
            ]
        if control in {"hostile_first", "ally_first", "legacy"}:
            opening = goblin_strike(GOBLIN, f.hero) if control == "hostile_first" else attack(f.ally, GOBLIN)
            await f.round(opening, faces=(1,))
        if control == "legacy":
            legacy = f.session.combat_state.to_dict()
            legacy["encounter_facts"].pop("opening_actors")
            await db_mutations.save_combat_state(f.combat_id, legacy)
            await f.reload()
        if control == "changed_patron":
            await configure(world, "zhael", "paladin")
        if control == "rejected":
            with pytest.raises(ToolError, match="cannot target"):
                await f.declare(attack(f.hero, f.ally))
            assert f.session.combat_state.first_hostility == {}
            assert not any(p["type"] == "patron_abilities_updated" for p in published_payloads(f.session.room))
        else:
            target = GOBLIN
            if control == "structure":
                target = "wall"
                state = f.session.combat_state
                at = state.spatial["positions"][f.hero]
                add_wall(
                    state, target, "Slate Wall", {**at, "x": at["x"] + 3}, {**at, "x": at["x"] + 3, "y": at["y"] + 5}
                )
            packets = await f.round(attack(f.hero, target), faces=(1,))
            packet = next(p for p in packets if p["actor_id"] == f.hero)
            assert packet["hit"] is False and "oath_breach" not in packet
            expected_actor = {"hostile_first": GOBLIN, "ally_first": f.ally, "legacy": None}.get(control, f.hero)
            assert f.session.combat_state.encounter_facts["opening_actors"].get(target) == expected_actor
        assert await oath_book(f.hero) == before


async def test_yielded_ally_committed_attack_facts(world: SimpleNamespace) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        state = f.session.combat_state
        assert oath_breach.evaluate(state, participant(state, f.hero), participant(state, f.ally)) == []
        await f.round(yield_action(f.ally))
        state = f.session.combat_state
        attacker, ally = participant(state, f.hero), participant(state, f.ally)
        # combat_declaration_validation.validate_declaration refuses same-side attacks.
        assert oath_breach.evaluate(state, attacker, ally) == ["strike_yielded_ally"]
        attacker.conditions = [{"type": "charmed", "source": OTHER, "duration": 3}]
        assert oath_breach.evaluate(state, attacker, ally) == []


async def test_breach_rolls_back_with_attack(world: SimpleNamespace) -> None:
    async with fight(world, "valdris", archetype="paladin") as f:
        registered(f)
        await swear(f.session)
        await f.declare(attack(f.hero, GOBLIN))
        before = f.session.combat_state.to_dict()
        events = published_payloads(f.session.room)
        oath = await oath_book(f.hero)
        save = db_mutations.save_combat_state

        async def abort(combat_id: str, data: dict, *, conn: asyncpg.Connection) -> None:
            await save(combat_id, data, conn=conn)
            inside = await db_queries.get_player(f.hero, conn=conn)
            assert inside is not None and inside["oaths"]["records"][0]["status"] == "broken"
            assert data["encounter_facts"]["opening_actors"] == {GOBLIN: f.hero}
            await conn.execute("SELECT 1 / 0")

        with patch.object(db_mutations, "save_combat_state", side_effect=abort), dice(15):
            with pytest.raises(asyncpg.DivisionByZeroError):
                await f.call("resolve_phase")
        assert (await f.reload()).to_dict() == before
        assert await oath_book(f.hero) == oath
        assert published_payloads(f.session.room) == events
        with dice(15):
            assert (await f.call("resolve_phase"))["packets"][0]["oath_breach"]["terms"] == ["strike_first"]


async def test_held_attack_breaches_only_on_kept_roll(world: SimpleNamespace) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        await swear(f.session)
        await configure(world, "zhael", "warrior", index=1, patron_gifts={"zhael_lucky": {"spent": True}})
        lifecycle = _live_party(f.session, f.hero, f.ally)
        try:
            await f.declare(attack(f.hero, GOBLIN))
            with dice(1):
                offer = (await f.call("resolve_phase"))["fate_offer"]
                assert (await f.reload()).first_hostility == {}
                assert (await oath_book(f.hero))["records"][0]["status"] == "active"
                with f.session._bind_authenticated_actor(f.ally, 1, lambda *_: None):
                    pick = dict(id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")
                    packet = (await f.call("activate", **pick))["packets"][0]
                    assert packet["hit"] is False and packet["oath_breach"]["terms"] == ["strike_first"]
                    broken = await oath_book(f.hero)
                    with pytest.raises(ToolError, match="current Fate's Thread offer_id"):
                        await f.call("activate", **pick)
                    assert await oath_book(f.hero) == broken
        finally:
            await lifecycle.aclose()


async def test_layer_3_lock_rest_and_fresh_host_session(world: SimpleNamespace) -> None:
    async with fight(world, "valdris", archetype="paladin") as f:
        registered(f)
        await configure(
            world,
            "valdris",
            "paladin",
            divine_favor={"patron": "valdris", "level": 90, "max": 100},
            location_id="millhaven_inn",
            hp={"current": 20, "max": 20},
            stamina={"current": 8, "max": 8},
            focus={"current": 8, "max": 8},
        )
        f.session.location_id = "millhaven_inn"
        sworn = await swear(f.session)
        await f.round(attack(f.hero, GOBLIN), faces=(1,))
        original = await oath_book(f.hero)
        hud = patron_packet(f, f.hero)
        assert_locked(hud["abilities"])
        patron = await f.call("query_info", kind="patron")
        assert_locked(patron["abilities"])
        assert patron["synergy"]["clauses"][0]["implementation_id"] == "valdris_oath_breach"
        before = await row(world, 0)
        combat = f.session.combat_state.to_dict()
        events = published_payloads(f.session.room)
        for ability_id in LAYER_3:
            with pytest.raises(ToolError, match="Oath of Justice is broken"):
                await f.call("activate", id=ability_id, target_id=OTHER)
        assert await row(world, 0) == before
        assert (await f.reload()).to_dict() == combat
        assert published_payloads(f.session.room) == events
        gift = await f.call("activate", id="valdris_weight_of_truth")
        assert gift["id"] == "valdris_weight_of_truth"
        assert (await row(world, 0))["patron_gifts"]["valdris_weight_of_truth"]["spent"]
        packets = await f.round(attack(f.hero, OTHER), faces=(1,))
        assert "oath_breach" not in next(p for p in packets if p["actor_id"] == f.hero)
        assert await oath_book(f.hero) == original
        assert (await f.call("query_info", kind="abilities"))["oath_choice"] is None
        replay = await f.call("select", choice_id=sworn["choice_id"], option="justice")
        assert replay["status"] == "broken" and replay["oath_id"] == sworn["oath_id"]
        assert await oath_book(f.hero) == original
        with pytest.raises(ToolError, match="Oath of Justice is broken"):
            await f.call("select", choice_id=f"oath_{f.hero}_justice_1", option="justice")
        with patch("combat_end._build_handoff_agent", return_value=ExplorationAgent()):
            await f.call("end_combat", outcome="fled")
        assert f.session.combat_state is None
        explore = game_tools(f.session, agent=ExplorationAgent())
        await explore("rest", rest_type="long", use_song_of_rest=False)
        assert await oath_book(f.hero) == original
        assert_locked(patron_packet(f, f.hero)["abilities"])
        fresh = make_context(f.hero, "millhaven_inn", room=f.session.room).userdata
        await hydrate_session_state(fresh, await row(world, 0), conn=world.pool)
        assert await oath_book(f.hero) == original
        latest = patron_packet(f, f.hero)
        assert latest["patron_revision"] > hud["patron_revision"]
        assert all(a["available"] for a in latest["abilities"])
        assert (await row(world, 0))["session_count"] == before.get("session_count", 0) + 1
        assert (await swear(fresh))["status"] == "active"


async def test_guest_reconnect_keeps_lock_and_fresh_guest_entry_clears_it(world: SimpleNamespace) -> None:
    async with fight(world, "thyra", ally_hp=20) as f:
        registered(f)
        await configure(
            world,
            "valdris",
            "paladin",
            index=1,
            session_count=7,
            divine_favor={"patron": "valdris", "level": 90, "max": 100},
        )
        participant(f.session.combat_state, f.ally).archetype_id = "paladin"
        with f.session._bind_authenticated_actor(f.ally, 1, lambda *_: None):
            await swear(f.session)
        await f.round(attack(f.ally, GOBLIN), faces=(1,))
        original = await oath_book(f.ally)
        assert original["valdris_breach"]["session_id"] == f.session.session_id
        assert_locked(patron_packet(f, f.ally)["abilities"])
        room, handlers = _recording_room()
        room.isconnected.return_value = True
        room.local_participant.publish_data = f.session.room.local_participant.publish_data
        mods = _make_mods(await row(world, 1))
        owner = _setup_party_join(room, f.session, queries=mods[0], resonance_mod=mods[1], concentration_mod=mods[2])
        try:
            handlers["participant_connected"](_participant(f.ally))
            assert await owner.authorize(f.ally) is not None
            handlers["participant_disconnected"](_participant(f.ally))
            handlers["participant_connected"](_participant(f.ally))
            assert await owner.authorize(f.ally) is not None
            event = json.loads(room.local_participant.publish_data.await_args.args[0])
            assert event["type"] == "session_init"
            assert_locked(event["abilities"])
            assert await oath_book(f.ally) == original
        finally:
            await owner.aclose()
        fresh = make_context(f.hero, room=f.session.room, party_member_ids=[f.ally]).userdata
        fresh.combat_state = await f.reload()
        await hydrate_patron_ability_session(fresh, f.ally, conn=world.pool)
        assert all(a["available"] for a in patron_packet(f, f.ally)["abilities"])
        assert (await row(world, 1))["session_count"] == 7
        assert await oath_book(f.ally) == original
        with fresh._bind_authenticated_actor(f.ally, 1, lambda *_: None):
            assert (await swear(fresh))["status"] == "active"
        f.session = fresh
        registered(f)
        await f.round(attack(f.ally, OTHER), faces=(1,))
        second = await oath_book(f.ally)
        assert second["records"][0] == original["records"][0]
        assert second["records"][1]["status"] == "broken"
        assert second["valdris_breach"]["session_id"] == fresh.session_id
