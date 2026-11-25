from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _enemy
from acceptance.test_catalog_combat_translation import reload
from acceptance.test_catalog_combat_translation import runtime as runtime
from acceptance.test_still_anchors import declare, destroy, enter, search_round, spell
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import still as still
from test_party_aggressors import reset_db_pool as reset_db_pool
from test_party_aggressors import round_packets
from voice_condition_fixtures import participant, place_actors

from check_resolution import D20Roll


@pytest.mark.parametrize("species,action", [("bandit", "Dirty Fighting"), ("hollow_choir", "Stolen Melody")])
async def test_resisted_condition_attempt(runtime, species: str, action: str) -> None:
    ctx, pid, eid, _ = await runtime(species)
    target = participant(ctx.userdata.combat_state, pid)
    target.attributes.update(dexterity=30, wisdom=30)
    payload = {"kind": "ability", "actor_id": eid, "action": action, "targets": [pid], "argument_type": ""}
    packets = await round_packets(ctx.userdata, defend(pid), payload)
    packet = next(p for p in packets if p["actor_id"] == eid)
    assert packet["resolved"] and packet["save_success"] and "condition_inflicted" not in packet
    assert (await reload(ctx)).encounter_facts["party_aggressors"] == {eid: [pid]}


async def test_still_successful_zone_save(still) -> None:
    response, state = await enter(still)
    owner = state.still_encounter["owner_id"]
    for anchor in state.still_encounter["anchor_ids"][:4]:
        await search_round(still, response["still"]["search_actions"][0])
        await destroy(still, anchor)
    await declare(still, actor_id=owner, **spell("Final Stillness"))
    with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(20)):
        packets = await still.drain()
    [target] = next(p["targets"] for p in packets if p.get("action") == "Final Stillness")
    assert target["save_success"] and target["target_id"] == still.players[0]
    assert (await still.reload()).encounter_facts["party_aggressors"] == {owner: still.players}


async def test_corruption_field_success(runtime) -> None:
    ctx, pid, eid, _ = await runtime("hollow_veilrender", "boss")
    state = ctx.userdata.combat_state
    other = _enemy("other_foe", 100)
    state.participants.append(other)
    state.initiative_order.append(other.id)
    place_actors(state)
    state.spatial["positions"][pid]["x"] = 1000
    hp = participant(state, pid).hp_current
    defend_all = [defend(pid), defend(eid), defend(other.id)]
    await round_packets(ctx.userdata, *defend_all)
    state = await reload(ctx)
    assert state.encounter_facts["party_aggressors"] == {}
    assert state.spatial is not None
    state.spatial["positions"][pid]["x"] = 0
    packets = await round_packets(ctx.userdata, *defend_all)
    state = await reload(ctx)
    assert participant(state, pid).hp_current == hp
    effects = next(p["turn_start_effects"] for p in packets if p["actor_id"] == pid)
    [field] = [effect for effect in effects if effect["effect"] == "corruption_field"]
    assert field["source_id"] == eid and field["save_success"]
    assert state.encounter_facts["party_aggressors"] == {eid: [pid]}


async def test_area_saves_only_record_party_members(runtime) -> None:
    ctx, pid, eid, _ = await runtime("hollow_choir")
    state = ctx.userdata.combat_state
    other = _enemy("other_foe", 100)
    state.participants.append(other)
    state.initiative_order.append(other.id)
    place_actors(state)
    payload = {**attack(eid, pid), "action": "Cacophony"}
    with patch("combat_enemy_action.dice_roll", return_value=SimpleNamespace(total=1)):
        packets = await round_packets(ctx.userdata, defend(pid), payload, defend(other.id))
    area = next(p for p in packets if p.get("action") == "Cacophony")
    assert [(p["target_id"], p["save_success"], p["damage"]) for p in area["targets"]] == [
        (pid, True, 0),
        (other.id, True, 0),
    ]
    assert (await reload(ctx)).encounter_facts["party_aggressors"] == {eid: [pid]}
