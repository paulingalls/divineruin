import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import (
    GUILD_PLAYER,
    make_context,
    make_db_mod,
    make_mock_room,
)

import event_types as E
from caster_state import ConcentrationState, ResonanceTrack
from party_state import PartyMember
from quest_tools import _update_quest_impl


def _marker_store(member_ids, progress=None):
    """A stand-in for the `player_quests` table: player_id -> stored blob. `progress` maps a
    player_id to the `current_stage` their row already carries; None means NO row at all (the
    absent-row case the replay hole rides on). Members not named default to stage 0."""
    progress = {**{pid: 0 for pid in member_ids}, **(progress or {})}
    return {pid: {"current_stage": stage} for pid, stage in progress.items() if stage is not None}


async def _complete_stage_for_party(
    member_ids, xp_reward, *, primary=None, store=None, unregistered=(), joins_during_lock=None
):
    """Complete a one-stage quest granting `xp_reward` for a party of `member_ids`, as
    `primary` (default: the first member).

    `store` is the live marker store (see `_marker_store`) — reads AND writes go through it, so
    a caller can run two stages in sequence and see the second read what the first recorded.
    `unregistered` names members with no `players` row, which the XP pass skips.
    `joins_during_lock` names a player appended to `party.members` partway through the lock pass,
    the way participant_lifecycle appends one on connect.
    Returns (mutations, queries, response)."""
    quest = {
        "id": "q1",
        "name": "Party Quest",
        "stages": [
            {"id": 0, "objective": "begin", "on_complete": {"xp": xp_reward}},
            {"id": 1, "objective": "next", "on_complete": {}},
        ],
    }
    store = _marker_store(member_ids) if store is None else store
    mock_db, _ = make_db_mod()
    content = MagicMock()
    content.get_quest = AsyncMock(return_value=quest)
    content.get_item = AsyncMock(return_value=None)
    queries = MagicMock()
    queries.get_player_quest = AsyncMock(side_effect=lambda pid, qid, **kw: store.get(pid))
    queries.get_player = AsyncMock(
        side_effect=lambda pid, **kw: None if pid in unregistered else {**GUILD_PLAYER, "player_id": pid}
    )
    mutations = MagicMock()
    mutations.set_player_quest = AsyncMock(side_effect=lambda pid, qid, data, **kw: store.__setitem__(pid, data))
    mutations.update_player_xp = AsyncMock()
    mutations.add_inventory_item = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    ctx = make_context(player_id=primary or member_ids[0], room=make_mock_room(), party_member_ids=member_ids)
    if joins_during_lock is not None:
        read_row = queries.get_player_quest.side_effect

        def _join_then_read(pid, qid, **kw):
            ctx.userdata.party.members.append(
                PartyMember(player_id=joins_during_lock, resonance=ResonanceTrack(), concentration=ConcentrationState())
            )
            queries.get_player_quest.side_effect = read_row
            return read_row(pid, qid, **kw)

        queries.get_player_quest.side_effect = _join_then_read
    raw = await _update_quest_impl(ctx, "q1", 1, db_mod=mock_db, mutations=mutations, queries=queries, content=content)
    return mutations, queries, json.loads(raw if isinstance(raw, str) else raw[1])


@pytest.mark.asyncio
async def test_quest_xp_pays_every_party_member():
    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200)

    paid = {call.args[0] for call in mutations.update_player_xp.await_args_list}
    assert paid == {"player_1", "player_2"}


@pytest.mark.asyncio
async def test_quest_xp_share_uses_the_same_party_curve_as_combat():
    """Quest and combat rewards share the same progression curve."""
    import encounter_loot

    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200)

    expected = int(200 * encounter_loot.party_reward_multiplier(2) / 2)
    for call in mutations.update_player_xp.await_args_list:
        assert call.args[1] == GUILD_PLAYER["xp"] + expected


@pytest.mark.asyncio
async def test_solo_quest_xp_is_unchanged_by_the_party_split():
    mutations, _, _ = await _complete_stage_for_party(["player_1"], 200)

    assert mutations.update_player_xp.await_count == 1
    assert mutations.update_player_xp.await_args.args[1] == GUILD_PLAYER["xp"] + 200


async def _complete_favor_stage(
    member_ids, favor_amount, patrons, *, xp_amount=0, fail_after=False, room=None, store=None
):
    """Complete a one-stage quest granting `favor_amount` favor (and optionally `xp_amount` XP,
    for the cases that need BOTH reward branches). `patrons` maps player_id -> patron id ('none'
    for unaligned). `store` is the live marker store (see `_marker_store`).
    Returns (mutations, room, response)."""
    quest = {
        "id": "fq",
        "name": "Favor Quest",
        "stages": [
            {"id": 0, "objective": "begin", "on_complete": {"favor": favor_amount, "xp": xp_amount}},
            {"id": 1, "objective": "next", "on_complete": {}},
        ],
    }
    room = room or make_mock_room()
    store = _marker_store(member_ids) if store is None else store
    mock_db, _ = make_db_mod()
    content = MagicMock()
    content.get_quest = AsyncMock(return_value=quest)
    content.get_item = AsyncMock(return_value=None)
    queries = MagicMock()
    queries.get_player_quest = AsyncMock(side_effect=lambda pid, qid, **kw: store.get(pid))
    queries.get_player = AsyncMock(side_effect=lambda pid, **kw: {**GUILD_PLAYER, "player_id": pid})
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(
        side_effect=lambda pid, **kw: {"patron": patrons[pid], "level": 10, "max": 100, "last_whisper_level": 0}
    )
    mutations = MagicMock()
    mutations.set_player_quest = AsyncMock(
        side_effect=RuntimeError("tx blew up")
        if fail_after
        else (lambda pid, qid, data, **kw: store.__setitem__(pid, data))
    )
    mutations.update_player_xp = AsyncMock()
    mutations.add_inventory_item = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    mutations.update_divine_favor = AsyncMock()
    ctx = make_context(player_id=member_ids[0], room=room, party_member_ids=member_ids)
    raw = await _update_quest_impl(
        ctx,
        "fq",
        1,
        db_mod=mock_db,
        mutations=mutations,
        queries=queries,
        content=content,
        activities=activities,
        divine_mutations=mutations,
    )
    return mutations, room, json.loads(raw if isinstance(raw, str) else raw[1])


@pytest.mark.asyncio
async def test_quest_favor_pays_every_aligned_member_the_full_amount():
    """Divine favor is personal rather than shared party XP."""
    mutations, _, _ = await _complete_favor_stage(
        ["player_1", "player_2"], 5, {"player_1": "kaelen", "player_2": "solwyn"}
    )

    granted = {call.args[0]: call.args[1] for call in mutations.update_divine_favor.await_args_list}
    assert granted == {"player_1": 15, "player_2": 15}


@pytest.mark.asyncio
async def test_quest_favor_skips_a_patronless_member_without_failing_the_stage():
    """A patronless member must not abort the party's core rewards."""
    mutations, _, response = await _complete_favor_stage(
        ["player_1", "player_2"], 5, {"player_1": "kaelen", "player_2": "none"}
    )

    granted = {call.args[0] for call in mutations.update_divine_favor.await_args_list}
    assert granted == {"player_1"}
    assert response["new_stage"] == 1  # the quest still advanced


@pytest.mark.asyncio
async def test_quest_favor_surfaces_in_rewards_applied_for_the_dm():
    """The DM narrates from the tool response, not the bus."""
    _, _, response = await _complete_favor_stage(["player_1"], 5, {"player_1": "kaelen"})

    favor_rewards = [r for r in response["rewards_applied"] if r["type"] == "favor"]
    assert favor_rewards == [{"type": "favor", "amount": 5, "patron": "kaelen", "new_level": 15}]


@pytest.mark.asyncio
async def test_quest_favor_reports_the_real_gain_when_the_patrons_max_clamps_it():
    """Narrate the actual clamped grant rather than the requested amount."""
    _, _, response = await _complete_favor_stage(["player_1"], 95, {"player_1": "kaelen"})

    favor_rewards = [r for r in response["rewards_applied"] if r["type"] == "favor"]
    assert favor_rewards == [{"type": "favor", "amount": 90, "patron": "kaelen", "new_level": 100}]


@pytest.mark.asyncio
async def test_a_rolled_back_stage_publishes_no_favor():
    """Publish rewards only after the durable transaction commits."""
    room = make_mock_room()
    with pytest.raises(RuntimeError):
        await _complete_favor_stage(["player_1"], 5, {"player_1": "kaelen"}, fail_after=True, room=room)

    published = [json.loads(c[0][0])["type"] for c in room.local_participant.publish_data.call_args_list]
    assert E.DIVINE_FAVOR_CHANGED not in published


@pytest.mark.asyncio
async def test_every_party_quest_row_is_locked_in_ascending_player_id_order():
    """Lock players in ascending order to avoid deadlocks between overlapping parties."""
    _, queries, _ = await _complete_stage_for_party(["player_5", "player_9", "player_2"], 200, primary="player_5")

    locked = [call.args[0] for call in queries.get_player_quest.await_args_list]
    assert locked == ["player_2", "player_5", "player_9"]
    assert all(call.kwargs["for_update"] for call in queries.get_player_quest.await_args_list)


@pytest.mark.asyncio
async def test_a_member_who_joins_mid_call_is_not_paid_off_an_unlocked_row():
    """Snapshot the eligible roster so joining during payout cannot acquire an unlocked reward."""
    store = _marker_store(["player_1", "player_2"], {"player_9": 2})
    mutations, queries, _ = await _complete_stage_for_party(
        ["player_1", "player_2"], 200, store=store, joins_during_lock="player_9"
    )

    assert "player_9" not in [call.args[0] for call in queries.get_player_quest.await_args_list]
    assert {call.args[0] for call in mutations.update_player_xp.await_args_list} == {"player_1", "player_2"}
    assert store["player_9"] == {"current_stage": 2}


@pytest.mark.asyncio
async def test_a_completed_stage_marks_every_paid_member():
    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200)

    marked = {call.args[0]: call.args[2]["current_stage"] for call in mutations.set_player_quest.await_args_list}
    assert marked == {"player_1": 1, "player_2": 1}


@pytest.mark.asyncio
async def test_a_member_the_xp_pass_skipped_is_not_marked():
    """Reward markers derive from actual payouts rather than a second eligibility predicate."""
    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200, unregistered={"player_2"})

    marked = {call.args[0] for call in mutations.set_player_quest.await_args_list}
    assert marked == {"player_1"}


@pytest.mark.asyncio
async def test_a_patronless_member_is_still_marked_because_xp_paid_them():
    mutations, _, _ = await _complete_favor_stage(
        ["player_1", "player_2"], 5, {"player_1": "kaelen", "player_2": "none"}, xp_amount=200
    )

    paid_favor = {call.args[0] for call in mutations.update_divine_favor.await_args_list}
    marked = {call.args[0] for call in mutations.set_player_quest.await_args_list}
    assert paid_favor == {"player_1"}
    assert marked == {"player_1", "player_2"}


@pytest.mark.asyncio
async def test_a_favor_only_stage_marks_the_members_it_paid():
    mutations, _, _ = await _complete_favor_stage(
        ["player_1", "player_2"], 5, {"player_1": "kaelen", "player_2": "solwyn"}
    )

    assert mutations.update_player_xp.await_count == 0
    marked = {call.args[0] for call in mutations.set_player_quest.await_args_list}
    assert marked == {"player_1", "player_2"}


@pytest.mark.asyncio
async def test_a_marked_member_cannot_replay_the_stage_as_their_own_primary():
    """A replay marker must prevent a second grant after an older stage write."""
    store = _marker_store(["player_1", "player_2"])
    await _complete_stage_for_party(["player_1", "player_2"], 200, store=store)

    with pytest.raises(ToolError, match="Cannot go backward"):
        await _complete_stage_for_party(["player_1", "player_2"], 200, primary="player_2", store=store)


@pytest.mark.asyncio
async def test_a_member_further_along_in_their_own_run_is_not_written_backward():
    """Rolling back the whole stage blob must not leave a reward marker ahead of progress."""
    store = _marker_store(["player_1", "player_2"], {"player_2": 2})
    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200, store=store)

    marked = {call.args[0] for call in mutations.set_player_quest.await_args_list}
    assert marked == {"player_1"}
    assert store["player_2"] == {"current_stage": 2}


@pytest.mark.asyncio
async def test_a_member_further_along_in_their_own_run_is_not_paid():
    """A shrinking eligible roster cannot replay a grant to those already paid."""
    import encounter_loot

    store = _marker_store(["player_1", "player_2"], {"player_2": 2})
    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200, store=store)

    paid = {call.args[0] for call in mutations.update_player_xp.await_args_list}
    assert paid == {"player_1"}
    solo_share = int(200 * encounter_loot.party_reward_multiplier(1) / 1)
    assert mutations.update_player_xp.await_args.args[1] == GUILD_PLAYER["xp"] + solo_share


@pytest.mark.asyncio
async def test_a_member_further_along_in_their_own_run_is_not_paid_favor():
    store = _marker_store(["player_1", "player_2"], {"player_2": 2})
    mutations, _, _ = await _complete_favor_stage(
        ["player_1", "player_2"], 5, {"player_1": "kaelen", "player_2": "solwyn"}, store=store
    )

    granted = {call.args[0] for call in mutations.update_divine_favor.await_args_list}
    assert granted == {"player_1"}


@pytest.mark.asyncio
async def test_a_member_behind_the_host_is_locked_out_of_the_stages_they_skipped():
    """The stage marker deliberately replaces a per-stage reward ledger.
    A replay forfeits items and world effects as well as repeat grants."""
    quest = {
        "id": "q3",
        "name": "Long Quest",
        "stages": [
            {"id": 0, "objective": "one", "on_complete": {}},
            {"id": 1, "objective": "two", "on_complete": {}},
            {"id": 2, "objective": "three", "on_complete": {"xp": 200}},
        ],
    }
    store = {"player_1": {"current_stage": 2}}
    mock_db, _ = make_db_mod()
    content = MagicMock()
    content.get_quest = AsyncMock(return_value=quest)
    content.get_item = AsyncMock(return_value=None)
    queries = MagicMock()
    queries.get_player_quest = AsyncMock(side_effect=lambda pid, qid, **kw: store.get(pid))
    queries.get_player = AsyncMock(side_effect=lambda pid, **kw: {**GUILD_PLAYER, "player_id": pid})
    mutations = MagicMock()
    mutations.set_player_quest = AsyncMock(side_effect=lambda pid, qid, data, **kw: store.__setitem__(pid, data))
    mutations.update_player_xp = AsyncMock()
    mutations.add_inventory_item = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    ctx = make_context(player_id="player_1", room=make_mock_room(), party_member_ids=["player_1", "player_2"])

    await _update_quest_impl(ctx, "q3", 3, db_mod=mock_db, mutations=mutations, queries=queries, content=content)

    assert [c.args[0] for c in mutations.update_player_xp.await_args_list].count("player_2") == 1
    assert store["player_2"] == {"current_stage": 3, "quest_name": "Long Quest", "status": "completed"}


@pytest.mark.asyncio
async def test_a_partially_paid_member_is_marked_but_warned_about(caplog):
    """Partial payout records the union of paid members; replay forfeits the remainder
    rather than risking duplicate rewards."""
    with caplog.at_level("WARNING"):
        mutations, _, _ = await _complete_favor_stage(
            ["player_1", "player_2"], 5, {"player_1": "kaelen", "player_2": "none"}, xp_amount=100
        )

    marked = {call.args[0] for call in mutations.set_player_quest.await_args_list}
    assert marked == {"player_1", "player_2"}, "the partially-paid member is still marked"
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("player_2" in m and "marked fully paid" in m for m in warnings), warnings
