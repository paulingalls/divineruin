import json
from collections import Counter
from typing import Any
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_known_spells
from livekit.agents import Agent, AgentSession
from sample_fixtures import published_payloads

import combat_hollow_death
import combat_rewards
import db_mutations
import db_queries
import event_types as E
import still_scene
from combat_agent import CombatAgent
from db_mutations_resonance import read_player_resonance
from mode_tools import enter_mode
from query_tools import query_info
from scene_tools import enter_location
from session_data import CompanionState, SessionData


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.fixture
async def still(reset_db_pool):
    harness = MawlingHarness()
    try:
        await harness.prepare((18,), companion=None, location="ashmark_still")
        yield harness
    finally:
        await harness.close()


async def enter(harness):
    scene = await harness.command("enter_location", {"location_id": harness.sd.location_id})
    response = await harness.command("enter_mode", {"mode": "combat", "encounter_id": scene["still"]["encounter_id"]})
    assert isinstance(harness.session.current_agent, CombatAgent)
    return response, await harness.reload()


async def declare(harness, *, actor_id=None, error=False, **action):
    return await harness.command(
        "declare_phase", {"declarations": [{"actor_id": actor_id or harness.players[0], **action}]}, error=error
    )


async def test_still_entry_search_and_weapon_damage(still):
    response, state = await enter(still)
    record = state.still_encounter
    owner_id = record["owner_id"]
    anchors = record["anchor_ids"]
    assert len(set(anchors)) == 6
    assert {p.id for p in state.participants if p.type == "enemy"} == {owner_id, *anchors}
    assert [state.get_participant(a).hp_max for a in anchors] == [40, 40, 40, 40, 45, 45]
    assert all(state.get_participant(a).ac == 20 for a in anchors)
    from combat_action_availability import available_actions

    assert not available_actions(state.get_participant(owner_id))
    assert all(not state.get_participant(a).action_pool for a in anchors)
    assert record["revealed_ids"] == []
    initial_events = published_payloads(still.sd.room)
    hud = [p for p in initial_events if p["type"] == E.COMBAT_UI_UPDATE][-1]
    assert not set(anchors).intersection(p["id"] for p in hud["combatants"])
    refusals = {owner_id: "cannot be targeted directly", anchors[0]: "unrevealed Still anchor"}
    for target, reason in refusals.items():
        assert reason in await declare(still, **strike(target), error=True)
        assert reason in await declare(still, **spell("arcane_bolt", target), error=True)
    for actor_id, action in [
        (owner_id, strike(still.players[0]) | {"action": "Serenity's Touch"}),
        (anchors[0], {"kind": "defend", "reshape": []}),
        (
            anchors[0],
            {
                "kind": "move",
                "nythera_step": False,
                "movement_mode": "ground",
                "reshape": [],
                "destination": {"x": 20, "y": 0, "z": 0},
            },
        ),
    ]:
        assert "take no actions" in await declare(still, actor_id=actor_id, error=True, **action)
    assert (await still.reload()).to_dict() == state.to_dict()
    assert published_payloads(still.sd.room) == initial_events

    search = next(a for a in response["still"]["search_actions"] if a["skill"] == "perception")
    assert search["dc"] == 18
    roll = await search_round(still, search, 10)
    for total in (17, 18):
        result = await search_round(still, search, total - roll["modifier"])
        assert (result["total"], result["success"]) == (total, total == 18)
        state = await still.reload()
        assert state.still_encounter["revealed_ids"] == (anchors[:1] if total == 18 else [])
    hud = [p for p in published_payloads(still.sd.room) if p["type"] == E.COMBAT_UI_UPDATE][-1]
    assert set(anchors).intersection(p["id"] for p in hud["combatants"]) == {anchors[0]}
    for target, reason in {owner_id: refusals[owner_id], anchors[1]: refusals[anchors[0]]}.items():
        refusal = await declare(still, **spell("arcane_magic_missile", anchors[0], target), error=True)
        assert reason in refusal
    assert (await still.reload()).to_dict() == state.to_dict()
    assert state.get_participant(still.players[0]).hp_current == 100
    await hit(still, anchors[0])
    after = await still.reload()
    assert [after.get_participant(a).hp_current for a in anchors[1:]] == [40, 40, 40, 45, 45]


def strike(target, *, action="Longsword") -> dict[str, Any]:
    return dict(reshape=[], kind="attack", action=action, target_id=target, held_item_id="", rider="")


def spell(action, *targets) -> dict[str, Any]:
    return dict(kind="ability", action=action, targets=list(targets), argument_type="")


async def search_round(harness, action, face=20):
    await declare(harness, kind="interact", action=action["action"])
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        packets = await harness.drain()
    return next(packet for packet in packets if packet.get("action") == action["action"])


async def hit(harness, target, *, action=None, already_declared=False):
    state = harness.sd.combat_state
    before = state.get_participant(target).hp_current
    if not already_declared:
        await declare(harness, **(action or strike(target)))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await harness.drain()
    if harness.sd.combat_state is not None:
        packet = next(p for p in packets if "damage" in p or "cast" in p)
        damage = packet["cast"]["damage_results"][0]["damage"] if action else packet["damage"]
        after = await harness.reload()
        assert damage > 0 and after.get_participant(target).hp_current == max(0, before - damage)
        record = after.still_encounter
        assert after.get_participant(record["owner_id"]).hp_current == sum(
            after.get_participant(a).hp_current for a in record["anchor_ids"]
        )
        return damage


async def destroy(harness, target):
    for _ in range(24):
        if harness.sd.combat_state is None or harness.sd.combat_state.get_participant(target).is_fallen:
            return
        await hit(harness, target)
    raise AssertionError(f"{target} survived 24 real weapon hits")


async def fresh_session(harness, state=None):
    companion = harness.sd.companion
    await harness.session.aclose()
    if harness.sd.background is not None:
        await harness.sd.background.stop()
    harness.sd = SessionData(
        player_id=harness.players[0], location_id=harness.sd.location_id, room=harness.sd.room, combat_state=state
    )
    harness.sd.companion = companion
    resonance = await read_player_resonance(harness.players[0])
    member = harness.sd.member_state(harness.players[0])
    member.resonance.current = resonance["current"]
    member.resonance.flickering_bonus = resonance["flickering_bonus"]
    harness.session = AgentSession(llm=harness.model, max_tool_steps=5, userdata=harness.sd)
    agent = (
        CombatAgent()
        if state is not None
        else Agent(instructions="Execute the command.", tools=[enter_mode, query_info, enter_location])
    )
    await harness.session.start(agent)


async def inventory(harness):
    items = Counter()
    for row in await db_queries.get_player_inventory(harness.players[0]):
        items[row["id"]] += row["slot_info"]["quantity"]
    return items


def enemy_snapshot(state):
    return {
        p.id: (p.hp_current, p.is_fallen, state.spatial["positions"][p.id])
        for p in state.participants
        if p.type == "enemy"
    }


async def touch(harness, state, owner: str, victim: str) -> None:
    original = state.spatial["positions"][victim]
    state.spatial["positions"][victim] = {**state.spatial["positions"][owner], "x": 120}
    state.get_participant(victim).attributes["wisdom"] = 30
    await harness.persist()
    await declare(harness, actor_id=owner, **strike(victim, action="Serenity's Touch"))
    with patch("check_resolution.dice_roll", return_value=_d20(20)), patch("dice.roll", return_value=_damage_die(2)):
        packets = await harness.drain()
    packet = next(p for p in packets if p.get("action") == "Serenity's Touch")
    assert packet["damage"] == 2 and packet["save_success"]
    state = await harness.reload()
    state.spatial["positions"][victim] = original
    await harness.persist()


async def test_still_flee_reload_and_settle_once(still):
    pid = still.players[0]
    follower = "companion_kael"
    still.sd.companion = CompanionState(id=follower, name="Kael", player_level=18)
    await still.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", pid, json.dumps({"class": "mage"})
    )
    await still.pool.execute("INSERT INTO skill_advancement(player_id,skill_id,tier) VALUES($1,'arcana','expert')", pid)
    await seed_known_spells(still.pool, pid, ("arcane_bolt", "arcane_magic_missile"))
    response, state = await enter(still)
    owner_id = state.still_encounter["owner_id"]
    anchors = state.still_encounter["anchor_ids"]
    arcana = next(action for action in response["still"]["search_actions"] if action["skill"] == "arcana")
    before_loot = await inventory(still)
    player = await db_queries.get_player(pid)
    assert player is not None
    before_xp = player.get("xp", 0)
    roll = await search_round(still, arcana, 5)
    failed = await search_round(still, arcana, 17 - roll["modifier"])
    assert failed["total"] == 17 and failed["still"]["revealed_anchor_ids"] == []
    for index, target in enumerate(anchors[:2], 1):
        result = await search_round(still, arcana, 18 - roll["modifier"])
        assert result["total"] == 18 and result["still"]["revealed_anchor_ids"] == anchors[:index]
        await destroy(still, target)
    await search_round(still, arcana)
    await hit(still, anchors[2], action=spell("arcane_bolt", anchors[2]))
    await hit(still, anchors[2], action=spell("arcane_magic_missile", anchors[2]))
    saved = await still.reload()
    assert 0 < saved.get_participant(anchors[2]).hp_current < 40

    await declare(still, **strike(anchors[2]))
    pending = await still.reload()
    await fresh_session(still, pending)
    assert enemy_snapshot(await still.reload()) == enemy_snapshot(saved)
    await hit(still, anchors[2], already_declared=True)
    saved = await still.reload()
    assert saved.still_encounter["revealed_ids"] == anchors[:3]
    assert all(saved.get_participant(target).hp_current == 0 for target in anchors[:2])
    await touch(still, saved, owner_id, follower)
    saved = await still.reload()
    assert saved.encounter_facts["party_aggressors"] == {owner_id: [follower]}
    await still.command("end_combat", {"outcome": "fled"})
    dormant = still_scene.read(await db_queries.get_player(pid), saved.location_id)
    assert dormant is not None
    assert dormant["snapshot"]["encounter_facts"]["party_aggressors"] == {owner_id: [follower]}
    await fresh_session(still)
    _, reentered = await enter(still)
    assert enemy_snapshot(reentered) == enemy_snapshot(saved)
    assert reentered.still_encounter == {**saved.still_encounter, "illusion": None}
    assert reentered.combat_id != saved.combat_id
    assert reentered.encounter_facts["party_aggressors"] == {owner_id: [follower]}
    await touch(still, reentered, owner_id, pid)
    assert (await still.reload()).encounter_facts["party_aggressors"] == {owner_id: [follower, pid]}

    accrue_death = combat_hollow_death.accrue_death
    awards = []

    async def count_death(session, state, owner, *, conn, queries):
        before = (await read_player_resonance(pid, conn=conn))["current"]
        await accrue_death(session, state, owner, conn=conn, queries=queries)
        awards.append((await read_player_resonance(pid, conn=conn))["current"] - before)

    with (
        patch("combat_hollow_death.accrue_death", side_effect=count_death) as death,
        patch("combat_rewards.grant_victory_rewards", wraps=combat_rewards.grant_victory_rewards) as reward,
    ):
        await destroy(still, anchors[2])
        for target in anchors[3:5]:
            await search_round(still, arcana)
            await destroy(still, target)
        live = await still.reload()
        assert all(live.get_participant(a).is_fallen for a in anchors[:5])
        assert live.get_participant(owner_id).hp_current == 45
        death.assert_not_awaited()
        reward.assert_not_awaited()
        player = await db_queries.get_player(pid)
        assert player is not None and player.get("xp", 0) == before_xp
        assert await inventory(still) == before_loot
        refusal = await still.command("end_combat", {"outcome": "victory"}, error=True)
        assert "All six Still anchors" in refusal
        assert (await still.reload()).to_dict() == live.to_dict()

        await search_round(still, arcana)
        await destroy(still, anchors[5])
        assert still.sd.combat_state is None
        assert still.last_result["outcome"] == "victory"
        assert still.last_result["xp_total"] == still.last_result["xp_granted"] == 5000
        assert awards == [6]
        reward.assert_awaited_once()
        death.assert_awaited_once()
        assert death.await_args is not None
        source = death.await_args.args[2]
        assert source.id == owner_id and source.hollow_death_resolved
        assert source.hollow["resonance_on_death"] == 6

        player = await db_queries.get_player(pid)
        assert player is not None and player["xp"] - before_xp == 5000
        receipt = still_scene.read(player, live.location_id)
        assert receipt is not None and receipt["status"] == "destroyed"
        assert await db_mutations.load_combat_state(live.combat_id) is None
        loot = (await inventory(still)) - before_loot
        memories = loot["absorbed_memories"]
        assert 1 <= memories <= 6
        assert still.last_result["still"]["absorbed_memories"] == memories
        assert loot == {"absorbed_memories": memories, "named_fragment": 1, "shard_false_paradise": 6}
        assert any(
            drop["item_id"] == "absorbed_memories" and drop["quantity"] == memories
            for drop in still.last_result["loot"]
        )
        resonance = await read_player_resonance(pid)
        assert resonance["current"] > 0
        await fresh_session(still)
        refusal = await still.command("enter_mode", {"mode": "combat", "encounter_id": "hollow_still"}, error=True)
        assert "destroyed" in refusal
        assert (await inventory(still)) - before_loot == loot
        assert await read_player_resonance(pid) == resonance
        death.assert_awaited_once()
        reward.assert_awaited_once()


async def test_still_area_spell_skips_owner_and_hidden_anchors(still):
    pid = still.players[0]
    await still.pool.execute(
        "UPDATE players SET data=jsonb_set(data || $2::jsonb,'{focus,current}','100') WHERE player_id=$1",
        pid,
        json.dumps({"class": "mage"}),
    )
    await seed_known_spells(still.pool, pid, ("arcane_elemental_burst",))
    response, state = await enter(still)
    anchors = state.still_encounter["anchor_ids"]
    search = next(a for a in response["still"]["search_actions"] if a["skill"] == "perception")
    await search_round(still, search)
    assert (await still.reload()).still_encounter["revealed_ids"] == anchors[:1]
    burst = spell("arcane_elemental_burst", anchors[0]) | {"argument_type": "cold"}
    await hit(still, anchors[0], action=burst)
    after = await still.reload()
    assert [after.get_participant(a).hp_current for a in anchors[1:]] == [40, 40, 40, 45, 45]
