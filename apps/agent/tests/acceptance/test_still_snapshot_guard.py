import json
from copy import deepcopy
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.seeds import seed_player
from acceptance.test_still_anchors import declare, destroy, enter, hit, search_round, strike
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import still as still
from sample_fixtures import published_payloads

import db_mutations
import db_queries
from caster_state import ConcentrationState, ResonanceTrack
from party_state import PartyMember


async def test_load_rejects_corrupt_still_snapshots(still):
    _, state = await enter(still)
    original = state.to_dict()
    record = state.still_encounter
    anchor = record["anchor_ids"][0]

    def participant_with_id(data, target):
        return next(row for row in data["participants"] if row["id"] == target)

    def remove_anchor(data):
        data["participants"].remove(participant_with_id(data, anchor))
        data["initiative_order"].remove(anchor)
        data["spatial"]["positions"].pop(anchor)
        data["spatial"]["speeds"].pop(anchor)

    mutations = [
        lambda data: data.pop("still_encounter"),
        lambda data: data["still_encounter"]["anchor_ids"].__setitem__(1, anchor),
        remove_anchor,
        lambda data: participant_with_id(data, anchor).update(hp_current=41),
        lambda data: data["still_encounter"]["revealed_ids"].append("unknown"),
        lambda data: data["still_encounter"].update(phase="destroyed"),
        lambda data: data["still_encounter"].update(
            pending_rejection={"anchor_id": "unknown", "execution_id": "attack"}
        ),
        lambda data: data["still_encounter"].update(
            revealed_ids=[anchor], pending_rejection={"anchor_id": anchor, "execution_id": "attack"}
        ),
        lambda data: data["still_encounter"].update(
            revealed_ids=[anchor], pending_rejection={"anchor_id": anchor, "execution_id": ""}
        ),
        lambda data: participant_with_id(data, record["owner_id"])["action_ledger"].pop("final stillness"),
        lambda data: participant_with_id(data, record["owner_id"])["action_ledger"]["final stillness"].update(
            remaining=1
        ),
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
    location = still.sd.location_id
    guest = f"{still.players[0]}_guest"
    outsider = f"{still.players[0]}_outsider"
    key = f"still_charm:{location}"
    charm = json.dumps(dict(location_id=location, kind="paradise_trap", remaining_zone_hours=None))
    for pid in (guest, outsider):
        await seed_player(still.pool, player_id=pid, location_id=location)
        await db_mutations.set_player_flag(pid, key, charm)
    still.sd.party.members.append(PartyMember(guest, ResonanceTrack(), ConcentrationState()))
    assert state.get_participant(guest) is None
    before, player = await still.snapshot()
    guest_before = await db_queries.get_player(guest)
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
        assert await db_queries.get_player(guest) == guest_before
        assert published_payloads(still.sd.room) == events
        await still.drain()
    guest_after = await db_queries.get_player(guest)
    outsider_after = await db_queries.get_player(outsider)
    assert guest_after is not None and key not in guest_after["flags"]
    assert outsider_after is not None and outsider_after["flags"][key] == charm
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
