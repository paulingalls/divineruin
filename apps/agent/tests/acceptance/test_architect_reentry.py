"""Round and encounter state across a return to the Works."""

import json

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import WORKS, attack, enter, pos, reopen
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory

import architect_scene
import combat_spatial
import combat_structures
import db_mutations
import db_queries
from party_state import PartyState


@pytest.fixture
async def fight(reset_db_pool):
    harness = MawlingHarness()
    try:
        await harness.prepare((20, 20), companion=None, location=WORKS)
        await enter(harness)
        yield harness
    finally:
        await harness.close()


@pytest.mark.parametrize("history", ["known", "prior", "absent"])
async def test_flee_retains_damaged_owner_and_wall(fight, history):
    state = await fight.reload()
    record = state.architect_encounter
    owner_id, wall_id = record["owner_id"], record["structure_ids"][0]
    player_id = fight.players[0]
    combat_spatial.place(state, player_id, pos(13, 9))
    await fight.persist()
    wall, _, _ = await attack(fight, owner_id, wall_id, "Construct Slam", face=20)
    assert wall["hit"] and wall["damage"] > 0
    assert (await fight.reload()).encounter_facts["party_aggressors"] == {}
    for target in (owner_id, wall_id):
        summary, _, _ = await attack(fight, player_id, target, "Longsword", face=20)
        assert summary["damage"] > 0
    state = await fight.reload()
    south = record["structure_ids"][1]
    target = state.get_participant(south)
    assert target is not None
    target.hp_current = 1
    combat_spatial.place(state, player_id, pos(13, -9))
    await fight.persist()
    await attack(fight, player_id, south, "Longsword", face=20)
    before = await fight.reload()
    follower = fight.players[1]
    at = before.spatial["positions"][owner_id]
    combat_spatial.place(before, follower, {**at, "y": at["y"] + 2})
    await fight.persist()
    strike, _, _ = await attack(fight, owner_id, follower, "Geometry Strike", face=1)
    assert strike["resolved"] and not strike["hit"]
    before = await fight.reload()
    assert before.encounter_facts["party_aggressors"] == {owner_id: [follower]}
    owner = before.get_participant(owner_id)
    owner.legendary_actions = 0
    round_number = before.round_number
    walls = before.architect_encounter["structure_ids"]
    before.architect_encounter.update(reshape_round=round_number, reshape_count=1, reaction_round=round_number)
    reaction = f"{owner_id}_reaction_wall_{round_number}"
    combat_structures.add_wall(before, reaction, "Architect's reaction wall", pos(5, -3), pos(5, 3))
    walls.append(reaction)
    before = await fight.persist()
    await fight.command("end_combat", {"outcome": "fled"})
    dormant = architect_scene.read(await db_queries.get_player(player_id), WORKS)
    assert dormant is not None and reaction not in dormant["snapshot"]["spatial"]["structures"]
    assert dormant["snapshot"]["encounter_facts"]["party_aggressors"] == {owner_id: [follower]}
    snapshot = before.to_dict()
    if history == "absent":
        del snapshot["encounter_facts"]
    elif history == "prior":
        del snapshot["encounter_facts"]["party_aggressors"]
    await db_mutations.set_player_flag(
        player_id, architect_scene.key(WORKS), json.dumps({**dormant, "snapshot": snapshot})
    )
    await reopen(fight)
    fight.sd.party.members.extend(PartyState.solo(follower).members)
    after = await enter(fight)
    assert before.round_number == after.round_number
    assert after.spatial is not None and before.spatial is not None
    for pid in (owner_id, wall_id, south):
        restored, saved = after.get_participant(pid), before.get_participant(pid)
        assert restored is not None and saved is not None
        assert restored.hp_current == saved.hp_current
        assert after.spatial["positions"][pid] == before.spatial["positions"][pid]
    assert after.spatial["structures"] == {
        pid: segment for pid, segment in before.spatial["structures"].items() if pid != reaction
    }
    retired = after.get_participant(reaction)
    assert retired is not None and retired.is_dead
    restored_owner = after.get_participant(owner_id)
    assert restored_owner is not None and restored_owner.legendary_actions == owner.legendary_capacity
    record = after.architect_encounter
    assert record is not None
    assert (record["reshape_round"], record["reshape_count"], record["reaction_round"]) == (0, 0, 0)

    assert after.combat_id != before.combat_id
    expected = {owner_id: [follower]} if history == "known" else None
    assert after.encounter_facts["party_aggressors"] == expected
    at = after.spatial["positions"][owner_id]
    combat_spatial.place(after, player_id, {**at, "y": at["y"] - 2})
    await fight.persist()
    strike, _, _ = await attack(fight, owner_id, player_id, "Geometry Strike", face=1)
    assert strike["resolved"] and not strike["hit"]
    history_after = (await fight.reload()).encounter_facts["party_aggressors"]
    assert history_after == ({owner_id: [follower, player_id]} if history == "known" else None)
