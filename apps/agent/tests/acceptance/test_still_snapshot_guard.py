from copy import deepcopy
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_still_anchors import declare, destroy, enter, hit, search_round, strike
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import still as still
from sample_fixtures import published_payloads

import db_mutations
import db_queries


async def test_load_rejects_corrupt_still_snapshots(still):
    _, state = await enter(still)
    original = state.to_dict()
    record = state.still_encounter
    anchor = record["anchor_ids"][0]

    def participant(data):
        return next(row for row in data["participants"] if row["id"] == anchor)

    def remove_anchor(data):
        data["participants"].remove(participant(data))
        data["initiative_order"].remove(anchor)
        data["spatial"]["positions"].pop(anchor)
        data["spatial"]["speeds"].pop(anchor)

    mutations = [
        lambda data: data.pop("still_encounter"),
        lambda data: data["still_encounter"]["anchor_ids"].__setitem__(1, anchor),
        remove_anchor,
        lambda data: participant(data).update(hp_current=41),
        lambda data: data["still_encounter"]["revealed_ids"].append("unknown"),
        lambda data: data["still_encounter"].update(phase="destroyed"),
    ]
    try:
        for corrupt in mutations:
            data = deepcopy(original)
            corrupt(data)
            await db_mutations.save_combat_state(state.combat_id, data)
            with pytest.raises(ValueError, match="Still"):
                await db_mutations.load_combat_state(state.combat_id)
    finally:
        await db_mutations.save_combat_state(state.combat_id, original)
    assert (await still.reload()).to_dict() == original


async def test_held_weapon_cannot_land_on_unrevealed_anchor(still):
    response, state = await enter(still)
    revealed, hidden = state.still_encounter["anchor_ids"][:2]
    await search_round(still, response["still"]["search_actions"][0])
    await still.pool.execute(
        """UPDATE players SET data=jsonb_set(data,'{divine_favor}',
           '{"patron":"zhael","level":0,"max":100,"last_whisper_level":0}'::jsonb) WHERE player_id=$1""",
        still.players[0],
    )
    await declare(still, **strike(revealed))
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        offered = await still.command("resolve_phase", {})
    assert offered["fate_offer"]["roller_id"] == still.players[0]
    state = await still.reload()
    state.ally_continuation["attack"]["target_id"] = hidden
    before = state.to_dict()
    await db_mutations.save_combat_state(state.combat_id, before)
    still.sd.combat_state = await db_mutations.load_combat_state(state.combat_id)
    events = published_payloads(still.sd.room)
    player = await db_queries.get_player(still.players[0])

    await still.command("resolve_phase", {}, error=True)
    assert (await still.reload()).to_dict() == before
    assert await db_queries.get_player(still.players[0]) == player
    assert published_payloads(still.sd.room) == events


async def test_final_anchor_write_failure_rolls_back_before_retry(still, monkeypatch):
    response, state = await enter(still)
    anchors = state.still_encounter["anchor_ids"]
    search = response["still"]["search_actions"][0]
    for target in anchors[:-1]:
        await search_round(still, search)
        await destroy(still, target)
    await search_round(still, search)

    save = db_mutations.save_combat_state
    failed = []

    async def fail_final_snapshot(combat_id, data, *, conn=None):
        await save(combat_id, data, conn=conn)
        if data["still_encounter"]["phase"] == "destroyed":
            failed.append(combat_id)
            raise RuntimeError("Injected final-anchor snapshot failure")

    target = anchors[-1]
    damage = await hit(still, target)
    for _ in range(24):
        if still.sd.combat_state.get_participant(target).hp_current <= damage:
            break
        await hit(still, target)
    else:
        raise AssertionError("Could not stage the final weapon hit")

    await declare(still, **strike(target))
    before, player = await still.snapshot()
    events = published_payloads(still.sd.room)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        with monkeypatch.context() as fault:
            fault.setattr(db_mutations, "save_combat_state", fail_final_snapshot)
            await still.command("resolve_phase", {}, error=True)
        assert failed == [state.combat_id]
        assert await still.snapshot() == (before, player)
        assert published_payloads(still.sd.room) == events
        await still.drain()
    assert still.last_result["outcome"] == "victory"
    assert still.last_result["xp_granted"] == 5000
    assert {drop["item_id"] for drop in still.last_result["loot"]} == {"absorbed_memories"}


async def test_discover_check_cannot_reveal_still_anchors(still):
    await enter(still)
    events = published_payloads(still.sd.room)
    roll = {"kind": "discover", "skill": "perception", "target": "still_anchors", "hearing_only": False}
    refusal = await still.command("check", {"roll": roll}, error=True)
    assert "Still discovery requires a declared Interact search action" in refusal
    assert (await still.reload()).still_encounter["revealed_ids"] == []
    assert published_payloads(still.sd.room) == events
