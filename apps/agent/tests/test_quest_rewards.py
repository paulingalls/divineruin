"""Quest reward tests — what a COMPLETED stage pays and records: the party-wide XP share,
the per-member divine favor grant, and the anti-replay quest markers those payments leave.

Split out of test_quest_tools.py (story-009) so that module keeps stage transitions,
milestones and world effects; this one owns the reward/ledger side of `on_complete`."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import (
    GUILD_PLAYER,
    make_context,
    make_db_mod,
    make_mock_room,
)

import event_types as E
from quest_tools import _update_quest_impl

# ── Quest XP is party-wide (story-002, debt 6033f2bedcea) ─────────────────────
# story-001 made combat XP party-wide, but quest XP still paid only session.player_id, so a
# non-primary member earned combat XP and no quest XP and drifted down in level by quest volume.
# The share must follow the SAME rule combat uses, not a second copy of it.


def _marker_store(member_ids, progress=None):
    """A stand-in for the `player_quests` table: player_id -> stored blob. `progress` maps a
    player_id to the `current_stage` their row already carries; None means NO row at all (the
    absent-row case the replay hole rides on). Members not named default to stage 0."""
    progress = {**{pid: 0 for pid in member_ids}, **(progress or {})}
    return {pid: {"current_stage": stage} for pid, stage in progress.items() if stage is not None}


async def _complete_stage_for_party(member_ids, xp_reward, *, primary=None, store=None, unregistered=()):
    """Complete a one-stage quest granting `xp_reward` for a party of `member_ids`, as
    `primary` (default: the first member).

    `store` is the live marker store (see `_marker_store`) — reads AND writes go through it, so
    a caller can run two stages in sequence and see the second read what the first recorded.
    `unregistered` names members with no `players` row, which the XP pass skips.
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
    raw = await _update_quest_impl(ctx, "q1", 1, db_mod=mock_db, mutations=mutations, queries=queries, content=content)
    return mutations, queries, json.loads(raw if isinstance(raw, str) else raw[1])


@pytest.mark.asyncio
async def test_quest_xp_pays_every_party_member():
    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200)

    paid = {call.args[0] for call in mutations.update_player_xp.await_args_list}
    assert paid == {"player_1", "player_2"}


@pytest.mark.asyncio
async def test_quest_xp_share_uses_the_same_party_curve_as_combat():
    """Pinned to encounter_loot.party_reward_multiplier itself, not a copied number: grouping
    must never pay differently for quest progression than for combat progression."""
    import encounter_loot

    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200)

    expected = int(200 * encounter_loot.party_reward_multiplier(2) / 2)
    for call in mutations.update_player_xp.await_args_list:
        # update_player_xp(player_id, new_xp, new_level, conn=...) — new_xp is base + share.
        assert call.args[1] == GUILD_PLAYER["xp"] + expected


@pytest.mark.asyncio
async def test_solo_quest_xp_is_unchanged_by_the_party_split():
    """N=1 -> multiplier exactly 1.0: a solo player still receives the whole declared reward."""
    mutations, _, _ = await _complete_stage_for_party(["player_1"], 200)

    assert mutations.update_player_xp.await_count == 1
    assert mutations.update_player_xp.await_args.args[1] == GUILD_PLAYER["xp"] + 200


# ── Divine favor is a quest-completion Resolve (story-002, M28) ───────────────
# Favor was only ever written by the award_divine_favor LLM tool; story-003 deleted it, so
# without this path favor would be ungrantable. Party-wide at the FULL declared amount each —
# a patron relationship is personal, not a haul to divide (unlike XP and coin).


async def _complete_favor_stage(member_ids, favor_amount, patrons, *, fail_after=False, room=None, store=None):
    """Complete a one-stage quest granting `favor_amount` favor. `patrons` maps player_id ->
    patron id ('none' for unaligned). `store` is the live marker store (see `_marker_store`).
    Returns (mutations, room, response)."""
    quest = {
        "id": "fq",
        "name": "Favor Quest",
        "stages": [
            {"id": 0, "objective": "begin", "on_complete": {"favor": favor_amount}},
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
    """Not split by the party multiplier: standing with your own god is not a shared haul."""
    mutations, _, _ = await _complete_favor_stage(
        ["player_1", "player_2"], 5, {"player_1": "kaelen", "player_2": "solwyn"}
    )

    granted = {call.args[0]: call.args[1] for call in mutations.update_divine_favor.await_args_list}
    assert granted == {"player_1": 15, "player_2": 15}


@pytest.mark.asyncio
async def test_quest_favor_skips_a_patronless_member_without_failing_the_stage():
    """An unaligned member must be SKIPPED, not abort the stage — the core returns None for them."""
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
    """A stage promising more favor than the bar has room for reports what actually landed.
    The player sits at 10/100; the stage declares 95, so only 90 can be granted — narrating
    "95" would tell them their standing rose further than it did."""
    _, _, response = await _complete_favor_stage(["player_1"], 95, {"player_1": "kaelen"})

    favor_rewards = [r for r in response["rewards_applied"] if r["type"] == "favor"]
    assert favor_rewards == [{"type": "favor", "amount": 90, "patron": "kaelen", "new_level": 100}]


@pytest.mark.asyncio
async def test_a_rolled_back_stage_publishes_no_favor():
    """The cue is buffered, not published, until the transaction commits — so a failure after
    the favor write announces nothing the database does not hold."""
    room = make_mock_room()
    with pytest.raises(RuntimeError):
        await _complete_favor_stage(["player_1"], 5, {"player_1": "kaelen"}, fail_after=True, room=room)

    # Nothing reached the wire: publish happens only after the `async with` block returns.
    published = [json.loads(c[0][0])["type"] for c in room.local_participant.publish_data.call_args_list]
    assert E.DIVINE_FAVOR_CHANGED not in published


# ── Every paid member gets an anti-replay marker (story-009) ──────────────────
# story-002 made the REWARD party-wide but left the LEDGER singular: only the primary's
# player_quests row was written. A non-primary was paid and kept no record of it, so hosting
# their own session let them run the same quest from stage 0 — the backward guard read their
# ABSENT row, passed, and paid them again. Every stage was farmable once per member per host.


@pytest.mark.asyncio
async def test_every_party_quest_row_is_locked_in_ascending_player_id_order():
    """The marker pass writes every member's row, so every member's row must be locked. Taking
    them in ascending player_id — NOT primary-first — is what keeps two concurrent sessions with
    different primaries and overlapping membership from holding-and-waiting in opposing orders."""
    _, queries, _ = await _complete_stage_for_party(["player_5", "player_9", "player_2"], 200, primary="player_5")

    locked = [call.args[0] for call in queries.get_player_quest.await_args_list]
    assert locked == ["player_2", "player_5", "player_9"]
    assert all(call.kwargs["for_update"] for call in queries.get_player_quest.await_args_list)
