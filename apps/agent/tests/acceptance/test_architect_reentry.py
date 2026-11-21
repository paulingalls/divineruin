"""Round and encounter state across a return to the Works."""

import json

from acceptance.test_architect_fight import WORKS, attack, enter, pos, reopen
from acceptance.test_architect_fight import fight as fight
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory

import architect_scene
import combat_spatial
import combat_structures
import db_mutations
import db_queries


async def test_flee_retains_damaged_owner_and_wall(fight):
    state = await fight.reload()
    record = state.architect_encounter
    owner_id, wall_id = record["owner_id"], record["structure_ids"][0]
    player_id = fight.players[0]
    combat_spatial.place(state, player_id, pos(13, 9))
    await fight.persist()
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
    await db_mutations.set_player_flag(
        player_id, architect_scene.key(WORKS), json.dumps({**dormant, "snapshot": before.to_dict()})
    )
    await reopen(fight)
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
