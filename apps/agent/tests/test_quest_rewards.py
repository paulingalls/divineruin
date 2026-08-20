"""Quest reward tests — what a COMPLETED stage pays and records: the party-wide XP share,
the per-member divine favor grant, and the anti-replay quest markers those payments leave.

Split out of test_quest_tools.py (story-009) so that module keeps stage transitions,
milestones and world effects; this one owns the reward/ledger side of `on_complete`."""

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


@pytest.mark.asyncio
async def test_a_member_who_joins_mid_call_is_not_paid_off_an_unlocked_row():
    """`party.member_ids` is a LIVE view over a list participant_lifecycle appends to on connect,
    so the roster is snapshotted once at the lock pass and every later pass reads the snapshot.
    Re-reading it would let a member who arrived after the lock pass into the reward passes with
    no row locked and no entry in the marker map — which reads as "unpaid" and pays them for a
    stage their own row already holds."""
    store = _marker_store(["player_1", "player_2"], {"player_9": 2})
    mutations, queries, _ = await _complete_stage_for_party(
        ["player_1", "player_2"], 200, store=store, joins_during_lock="player_9"
    )

    assert "player_9" not in [call.args[0] for call in queries.get_player_quest.await_args_list]
    assert {call.args[0] for call in mutations.update_player_xp.await_args_list} == {"player_1", "player_2"}
    assert store["player_9"] == {"current_stage": 2}


@pytest.mark.asyncio
async def test_a_completed_stage_marks_every_paid_member():
    """AC-1. The farming hole itself: before story-009 only the primary's row was written."""
    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200)

    marked = {call.args[0]: call.args[2]["current_stage"] for call in mutations.set_player_quest.await_args_list}
    assert marked == {"player_1": 1, "player_2": 1}


@pytest.mark.asyncio
async def test_a_member_the_xp_pass_skipped_is_not_marked():
    """The marker set is DERIVED from who the reward passes actually paid, never re-derived by
    copying their skip rules. distribute_xp skips a seat with no `players` row, so that member
    is eligible but unpaid — and an unpaid member must keep no record of a stage they did not
    earn, or the marker would bar them from being paid for it later."""
    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200, unregistered={"player_2"})

    marked = {call.args[0] for call in mutations.set_player_quest.await_args_list}
    assert marked == {"player_1"}


@pytest.mark.asyncio
async def test_a_patronless_member_is_still_marked_because_xp_paid_them():
    """AC-3. Favor returns None for an unaligned member, but XP paid them, so the stage IS
    theirs — the marker set is the UNION of what both passes paid."""
    mutations, _, _ = await _complete_favor_stage(
        ["player_1", "player_2"], 5, {"player_1": "kaelen", "player_2": "none"}, xp_amount=200
    )

    paid_favor = {call.args[0] for call in mutations.update_divine_favor.await_args_list}
    marked = {call.args[0] for call in mutations.set_player_quest.await_args_list}
    assert paid_favor == {"player_1"}
    assert marked == {"player_1", "player_2"}


@pytest.mark.asyncio
async def test_a_favor_only_stage_marks_the_members_it_paid():
    """A stage may declare favor and no XP at all. The marker set must still come from the favor
    loop's own returns — nothing about it may be scoped inside the XP branch."""
    mutations, _, _ = await _complete_favor_stage(
        ["player_1", "player_2"], 5, {"player_1": "kaelen", "player_2": "solwyn"}
    )

    assert mutations.update_player_xp.await_count == 0
    marked = {call.args[0] for call in mutations.set_player_quest.await_args_list}
    assert marked == {"player_1", "player_2"}


@pytest.mark.asyncio
async def test_a_marked_member_cannot_replay_the_stage_as_their_own_primary():
    """AC-2 as amended. The whole point of the marker: player_2 is paid in player_1's session,
    then hosts their own and runs the same quest. The backward guard now reads a row act 1
    ADVANCED and refuses — before story-009 act 1 left player_2's row where it was, so this call
    passed the guard and paid them a second time."""
    store = _marker_store(["player_1", "player_2"])
    await _complete_stage_for_party(["player_1", "player_2"], 200, store=store)

    with pytest.raises(ToolError, match="Cannot go backward"):
        await _complete_stage_for_party(["player_1", "player_2"], 200, primary="player_2", store=store)


@pytest.mark.asyncio
async def test_a_member_further_along_in_their_own_run_is_not_written_backward():
    """AC-4, first half. set_player_quest is a whole-blob upsert, so an unguarded party-wide
    write would drag a member who has already finished the quest back to stage 1."""
    store = _marker_store(["player_1", "player_2"], {"player_2": 2})
    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200, store=store)

    marked = {call.args[0] for call in mutations.set_player_quest.await_args_list}
    assert marked == {"player_1"}
    assert store["player_2"] == {"current_stage": 2}


@pytest.mark.asyncio
async def test_a_member_further_along_in_their_own_run_is_not_paid():
    """AC-4, second half — and the other route into the same farming hole: skipping only the
    MARKER would leave someone who finished the quest solo free to join any host's fresh run and
    collect for every stage forever, their marker never moving. One predicate gates both.

    Accepted consequence, pinned deliberately rather than left to be discovered: filtering the
    ahead member out shrinks the seat list party_reward_multiplier divides by, so the remaining
    member takes a SOLO-sized share. That is consistent — one eligible member is a party of one —
    but it makes this player's reward depend on another player's history, so it is not silent."""
    import encounter_loot

    store = _marker_store(["player_1", "player_2"], {"player_2": 2})
    mutations, _, _ = await _complete_stage_for_party(["player_1", "player_2"], 200, store=store)

    paid = {call.args[0] for call in mutations.update_player_xp.await_args_list}
    assert paid == {"player_1"}
    solo_share = int(200 * encounter_loot.party_reward_multiplier(1) / 1)
    assert mutations.update_player_xp.await_args.args[1] == GUILD_PLAYER["xp"] + solo_share


@pytest.mark.asyncio
async def test_a_member_further_along_in_their_own_run_is_not_paid_favor():
    """The same predicate gates the favor loop — favor is farmable exactly the same way."""
    store = _marker_store(["player_1", "player_2"], {"player_2": 2})
    mutations, _, _ = await _complete_favor_stage(
        ["player_1", "player_2"], 5, {"player_1": "kaelen", "player_2": "solwyn"}, store=store
    )

    granted = {call.args[0] for call in mutations.update_divine_favor.await_args_list}
    assert granted == {"player_1"}


@pytest.mark.asyncio
async def test_a_member_behind_the_host_is_credited_with_the_stages_they_skipped():
    """The SECOND accepted consequence of the current_stage marker (concern 0322739e5e4b).

    The marker is a single `current_stage`, not a per-stage ledger — the customer chose that
    over a `paid_stages` list. So a member who never started the quest and joins for a LATE
    stage is paid for that one stage, and their row is written forward to it: stages they never
    played become unreachable, and on the completion transition the whole quest reads as done in
    their own log.

    Pinned rather than argued: this is what the chosen design costs, and it should go red if
    anyone changes the marker's shape without deciding about it again.
    """
    quest = {
        "id": "q3",
        "name": "Long Quest",
        "stages": [
            {"id": 0, "objective": "one", "on_complete": {}},
            {"id": 1, "objective": "two", "on_complete": {}},
            {"id": 2, "objective": "three", "on_complete": {"xp": 200}},
        ],
    }
    # player_1 is on the last stage; player_2 has NO row at all — they never started it.
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

    # Paid once, for the one stage they were present for.
    assert [c.args[0] for c in mutations.update_player_xp.await_args_list].count("player_2") == 1
    # But credited with the whole quest: stages 0 and 1 are now unreachable for them.
    assert store["player_2"] == {"current_stage": 3, "quest_name": "Long Quest", "status": "completed"}


@pytest.mark.asyncio
async def test_a_partially_paid_member_is_marked_but_warned_about(caplog):
    """ONE marker flag, TWO possible rewards — a member paid only one of them is recorded as
    fully paid and forfeits the other for this stage, for good.

    The union is the deliberately safe direction: marking only members paid EVERYTHING would
    leave an unmarked member free to re-collect the reward they did get, once per host, forever
    — the farming hole story-009 closes. Closing this gap properly needs per-reward markers
    (a schema change, debt 27944a8fcd50). Until then the forfeit must be LOUD, because it only
    fires on a degraded row and it silently costs that member a reward.
    """
    # player_2 has no patron, so the favor pass skips them; the XP pass pays them. They end up
    # in exactly one of the two paid sets.
    with caplog.at_level("WARNING"):
        mutations, _, _ = await _complete_favor_stage(
            ["player_1", "player_2"], 5, {"player_1": "kaelen", "player_2": "none"}, xp_amount=100
        )

    marked = {call.args[0] for call in mutations.set_player_quest.await_args_list}
    assert marked == {"player_1", "player_2"}, "the partially-paid member is still marked"
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("player_2" in m and "marked fully paid" in m for m in warnings), warnings
