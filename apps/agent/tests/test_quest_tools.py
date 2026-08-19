"""Quest completion tests — archetype-aware LEVEL_UP hp_gains + milestone side-effects
routed through the shared _award_xp_core Resolve (story-002)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import (
    _WARRIOR_MILESTONES,
    GUILD_PLAYER,
    _milestones_mod_for,
    level_up_payload,
    make_context,
    make_db_mod,
    make_mock_room,
    published_types,
)

import event_types as E
from leveling import build_level_up_payload_for_archetype, get_level_up_rewards
from quest_tools import _update_quest_impl

QUEST = {
    "id": "q1",
    "name": "Test Quest",
    "stages": [
        {"id": 0, "objective": "begin", "on_complete": {"xp": 50}},
        {"id": 1, "objective": "middle", "on_complete": {"xp": 100}},
        {"id": 2, "objective": "end", "on_complete": {"xp": 150}},
    ],
}


async def _complete_warrior_quest_stage(level, xp, xp_reward):
    """Complete stage 0 of a single-reward quest for a warrior at (level, xp), awarding
    `xp_reward`, with the shared warrior milestone ladder injected. Returns
    (mutations, conn, room, response)."""
    quest = {
        "id": "q1",
        "name": "Test Quest",
        "stages": [
            {"id": 0, "objective": "begin", "on_complete": {"xp": xp_reward}},
            {"id": 1, "objective": "next", "on_complete": {}},
        ],
    }
    player = {**GUILD_PLAYER, "class": "warrior", "level": level, "xp": xp}
    room = make_mock_room()
    mock_db, mock_conn = make_db_mod()
    content = MagicMock()
    content.get_quest = AsyncMock(return_value=quest)
    content.get_item = AsyncMock(return_value=None)
    queries = MagicMock()
    queries.get_player_quest = AsyncMock(return_value={"current_stage": 0})
    queries.get_player = AsyncMock(return_value=player)
    mutations = MagicMock()
    mutations.set_player_quest = AsyncMock()
    mutations.update_player_xp = AsyncMock()
    mutations.add_inventory_item = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    ctx = make_context(room=room)
    raw = await _update_quest_impl(
        ctx,
        "q1",
        1,
        db_mod=mock_db,
        mutations=mutations,
        queries=queries,
        content=content,
        milestones_mod=_milestones_mod_for(_WARRIOR_MILESTONES, "warrior"),
    )
    response = json.loads(raw if isinstance(raw, str) else raw[1])
    return mutations, mock_conn, room, response


@pytest.mark.asyncio
async def test_quest_level_up_payload_carries_archetype_hp_gains():
    # Completing stage 1 awards xp 100; player at xp 250 crosses level 1 -> 2.
    player = {
        **GUILD_PLAYER,
        "class": "artificer",
        "xp": 250,
        "attributes": {**GUILD_PLAYER["attributes"], "constitution": 14},
    }
    room = make_mock_room()
    mock_db, _ = make_db_mod()
    content = MagicMock()
    content.get_quest = AsyncMock(return_value=QUEST)
    content.get_item = AsyncMock(return_value=None)
    queries = MagicMock()
    queries.get_player_quest = AsyncMock(return_value={"current_stage": 1})
    queries.get_player = AsyncMock(return_value=player)
    mutations = MagicMock()
    mutations.set_player_quest = AsyncMock()
    mutations.update_player_xp = AsyncMock()
    mutations.add_inventory_item = AsyncMock()
    ctx = make_context(room=room)

    await _update_quest_impl(ctx, "q1", 2, db_mod=mock_db, mutations=mutations, queries=queries, content=content)

    payload = level_up_payload(room)
    expected = build_level_up_payload_for_archetype(1, get_level_up_rewards(1, 2), "artificer", con_mod=2)
    assert payload is not None
    assert payload["hp_gains"] == expected["hp_gains"]


# --- Milestone side-effects on quest-stage XP (story-002): routing update_quest through
# _award_xp_core means quest rewards now apply auto-grants + surface the L5 fork, which the
# old inline copy dropped (debt ee947a154b10). ---


@pytest.mark.asyncio
async def test_quest_stage_crossing_l10_writes_extra_attack_flag():
    # The bug fix: a quest stage that crosses L10 now writes the extra_attack flag — the
    # inline copy never called apply_milestone_grant. L9 (2900) + 550 -> L10.
    mutations, conn, _, _ = await _complete_warrior_quest_stage(level=9, xp=2900, xp_reward=550)
    mutations.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)


@pytest.mark.asyncio
async def test_quest_stage_crossing_l5_publishes_specialization_choice():
    # A quest stage crossing L5 surfaces the fork via the SPECIALIZATION_CHOICE event (the
    # HUD overlay), persisting no choice. L4 (750) + 300 -> L5.
    mutations, _, room, _ = await _complete_warrior_quest_stage(level=4, xp=750, xp_reward=300)
    assert E.SPECIALIZATION_CHOICE in published_types(room)
    mutations.set_player_flag.assert_not_awaited()


@pytest.mark.asyncio
async def test_quest_stage_response_surfaces_milestone_grants():
    # The DM voices from the tool response: the crossed auto-grant's name + cue must reach it.
    _, _, _, response = await _complete_warrior_quest_stage(level=9, xp=2900, xp_reward=550)
    assert response["milestone_grants"] == [
        {"name": "Extra Attack", "effect": "Your blade strikes twice.", "narration_cue": "cue"}
    ]


@pytest.mark.asyncio
async def test_quest_stage_response_surfaces_specialization_fork():
    # The L5 fork cue reaches the DM in the quest response, symmetric to the combat-exit response.
    _, _, _, response = await _complete_warrior_quest_stage(level=4, xp=750, xp_reward=300)
    assert response["specialization_fork"] is True


@pytest.mark.asyncio
async def test_quest_stage_no_levelup_has_empty_grants_and_no_fork():
    # A small award that crosses no milestone leaves grants empty + fork false, and writes
    # no flag — guards the response defaults when no milestone is crossed.
    mutations, _, _, response = await _complete_warrior_quest_stage(level=1, xp=0, xp_reward=50)
    assert response["milestone_grants"] == []
    assert response["specialization_fork"] is False
    mutations.set_player_flag.assert_not_awaited()


# --- Terminal-stage completion (story-002 inc 4a, debt 7918cd848e90) -----------------
# update_quest never fired the FINAL stage's on_complete (guard rejected new_stage >=
# len(stages)), so terminal rewards were dead. The completion transition — new_stage_id ==
# len(stages) — fires the final on_complete and writes status=completed.

_COMPLETION_QUEST = {
    "id": "cq",
    "name": "Completion Quest",
    "stages": [
        {"id": 0, "objective": "start", "on_complete": {}},
        {"id": 1, "objective": "finish", "on_complete": {"rewards": [{"item": "prize", "quantity": 1}]}},
    ],
}


def _completion_mocks(current_stage: int):
    room = make_mock_room()
    mock_db, mock_conn = make_db_mod()
    content = MagicMock()
    content.get_quest = AsyncMock(return_value=_COMPLETION_QUEST)
    content.get_item = AsyncMock(return_value={"name": "Prize"})
    content.get_scenes_batch = AsyncMock(return_value={})
    queries = MagicMock()
    queries.get_player_quest = AsyncMock(return_value={"current_stage": current_stage})
    queries.get_player = AsyncMock(return_value=GUILD_PLAYER)
    mutations = MagicMock()
    mutations.set_player_quest = AsyncMock()
    mutations.add_inventory_item = AsyncMock()
    return make_context(room=room), mock_db, mock_conn, content, queries, mutations


@pytest.mark.asyncio
async def test_completing_final_stage_fires_its_on_complete():
    # Player at the final stage (1) of a 2-stage quest; completing (-> len==2) fires
    # stage-1's on_complete, so the previously-dead terminal item reward lands.
    ctx, mock_db, conn, content, queries, mutations = _completion_mocks(current_stage=1)
    raw = await _update_quest_impl(ctx, "cq", 2, db_mod=mock_db, mutations=mutations, queries=queries, content=content)
    response = json.loads(raw)
    mutations.add_inventory_item.assert_awaited_once_with("player_1", "prize", 1, conn=conn)
    assert response["completed"] is True


@pytest.mark.asyncio
async def test_completion_writes_status_completed():
    ctx, mock_db, _conn, content, queries, mutations = _completion_mocks(current_stage=1)
    await _update_quest_impl(ctx, "cq", 2, db_mod=mock_db, mutations=mutations, queries=queries, content=content)
    data = mutations.set_player_quest.await_args.args[2]
    assert data["status"] == "completed"
    assert data["current_stage"] == 2


@pytest.mark.asyncio
async def test_advancing_into_final_stage_does_not_fire_its_on_complete():
    # Advancing 0 -> 1 fires stage-0's (empty) on_complete, NOT stage-1's — the terminal
    # reward waits for the explicit completion transition.
    ctx, mock_db, _, content, queries, mutations = _completion_mocks(current_stage=0)
    await _update_quest_impl(ctx, "cq", 1, db_mod=mock_db, mutations=mutations, queries=queries, content=content)
    mutations.add_inventory_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_stage_beyond_completion_rejected():
    ctx, mock_db, _, content, queries, mutations = _completion_mocks(current_stage=1)
    with pytest.raises(ToolError, match="Invalid stage"):
        await _update_quest_impl(ctx, "cq", 3, db_mod=mock_db, mutations=mutations, queries=queries, content=content)


# --- Quest -> reputation world effect (story-002 inc 4b) ------------------------------
# A "<faction>_reputation <event_type>" world effect routes through reputation_shift +
# the writer, the faction-scoped analogue of the "<npc>_disposition +N" shorthand.


def _faction_content(exists=True):
    """A content mock whose get_faction resolves (or not) a faction — mirrors the DM tool's
    existence guard so the world_effect path never writes a phantom-faction row."""
    content = MagicMock()
    content.get_faction = AsyncMock(return_value={"id": "accord_guild"} if exists else None)
    return content


@pytest.mark.asyncio
async def test_reputation_world_effect_applies_via_writer():
    from quest_tools import _apply_world_effects

    session = make_context().userdata
    rm = MagicMock()
    rm.adjust_player_faction_reputation = AsyncMock(return_value=5)
    await _apply_world_effects(
        ["accord_guild_reputation completed_faction_quest"],
        session,
        [],
        conn=None,
        reputation_mutations=rm,
        content=_faction_content(),
    )
    # completed_faction_quest -> +5; faction_id parsed off the "_reputation" suffix; the
    # stage-transaction conn is threaded through to the writer.
    rm.adjust_player_faction_reputation.assert_awaited_once_with(
        session.player_id,
        "accord_guild",
        5,
        "world_effect: accord_guild_reputation completed_faction_quest",
        conn=None,
    )


@pytest.mark.asyncio
async def test_reputation_world_effect_unknown_event_skips():
    from quest_tools import _apply_world_effects

    session = make_context().userdata
    rm = MagicMock()
    rm.adjust_player_faction_reputation = AsyncMock()
    await _apply_world_effects(
        ["accord_guild_reputation bogus_event"], session, [], reputation_mutations=rm, content=_faction_content()
    )
    rm.adjust_player_faction_reputation.assert_not_awaited()


@pytest.mark.asyncio
async def test_reputation_world_effect_unknown_faction_skips():
    # A mistyped faction id in authored on_complete content must NOT write a phantom-faction
    # reputation row — the writer is never called, mirroring the DM tool's fail-on-unknown guard.
    from quest_tools import _apply_world_effects

    session = make_context().userdata
    rm = MagicMock()
    rm.adjust_player_faction_reputation = AsyncMock()
    await _apply_world_effects(
        ["phantom_faction_reputation completed_faction_quest"],
        session,
        [],
        reputation_mutations=rm,
        content=_faction_content(exists=False),
    )
    rm.adjust_player_faction_reputation.assert_not_awaited()


def test_greyvale_completion_authors_accord_reputation():
    # The terminal stage (now reachable via inc 4a) grants Accord standing on quest
    # completion — the semantically correct home ("report to the Accord").
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    quests = json.loads((root / "content" / "quests.json").read_text())
    greyvale = next(q for q in quests if q["id"] == "greyvale_anomaly")
    final = greyvale["stages"][-1]
    assert final["id"] == "stage_5_return"
    assert "accord_guild_reputation completed_faction_quest" in final["on_complete"]["world_effects"]


def test_greyvale_completion_authors_divine_favor():
    # story-002: the ONLY authored favor grant in the game now that story-003 has deleted the
    # award_divine_favor tool — unpinned, a content edit could silently make favor ungrantable.
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    quests = json.loads((root / "content" / "quests.json").read_text())
    greyvale = next(q for q in quests if q["id"] == "greyvale_anomaly")
    final = greyvale["stages"][-1]
    assert final["on_complete"]["favor"] == 5


# ── Quest XP is party-wide (story-002, debt 6033f2bedcea) ─────────────────────
# story-001 made combat XP party-wide, but quest XP still paid only session.player_id, so a
# non-primary member earned combat XP and no quest XP and drifted down in level by quest volume.
# The share must follow the SAME rule combat uses, not a second copy of it.


async def _complete_stage_for_party(member_ids, xp_reward):
    """Complete a one-stage quest granting `xp_reward` for a party of `member_ids`.
    Returns (mutations, response)."""
    quest = {
        "id": "q1",
        "name": "Party Quest",
        "stages": [
            {"id": 0, "objective": "begin", "on_complete": {"xp": xp_reward}},
            {"id": 1, "objective": "next", "on_complete": {}},
        ],
    }
    mock_db, _ = make_db_mod()
    content = MagicMock()
    content.get_quest = AsyncMock(return_value=quest)
    content.get_item = AsyncMock(return_value=None)
    queries = MagicMock()
    queries.get_player_quest = AsyncMock(return_value={"current_stage": 0})
    queries.get_player = AsyncMock(side_effect=lambda pid, **kw: {**GUILD_PLAYER, "player_id": pid})
    mutations = MagicMock()
    mutations.set_player_quest = AsyncMock()
    mutations.update_player_xp = AsyncMock()
    mutations.add_inventory_item = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    ctx = make_context(room=make_mock_room(), party_member_ids=member_ids[1:])
    raw = await _update_quest_impl(ctx, "q1", 1, db_mod=mock_db, mutations=mutations, queries=queries, content=content)
    return mutations, json.loads(raw if isinstance(raw, str) else raw[1])


@pytest.mark.asyncio
async def test_quest_xp_pays_every_party_member():
    mutations, _ = await _complete_stage_for_party(["player_1", "player_2"], 200)

    paid = {call.args[0] for call in mutations.update_player_xp.await_args_list}
    assert paid == {"player_1", "player_2"}


@pytest.mark.asyncio
async def test_quest_xp_share_uses_the_same_party_curve_as_combat():
    """Pinned to encounter_loot.party_reward_multiplier itself, not a copied number: grouping
    must never pay differently for quest progression than for combat progression."""
    import encounter_loot

    mutations, _ = await _complete_stage_for_party(["player_1", "player_2"], 200)

    expected = int(200 * encounter_loot.party_reward_multiplier(2) / 2)
    for call in mutations.update_player_xp.await_args_list:
        # update_player_xp(player_id, new_xp, new_level, conn=...) — new_xp is base + share.
        assert call.args[1] == GUILD_PLAYER["xp"] + expected


@pytest.mark.asyncio
async def test_solo_quest_xp_is_unchanged_by_the_party_split():
    """N=1 -> multiplier exactly 1.0: a solo player still receives the whole declared reward."""
    mutations, _ = await _complete_stage_for_party(["player_1"], 200)

    assert mutations.update_player_xp.await_count == 1
    assert mutations.update_player_xp.await_args.args[1] == GUILD_PLAYER["xp"] + 200


# ── Divine favor is a quest-completion Resolve (story-002, M28) ───────────────
# Favor was only ever written by the award_divine_favor LLM tool; story-003 deleted it, so
# without this path favor would be ungrantable. Party-wide at the FULL declared amount each —
# a patron relationship is personal, not a haul to divide (unlike XP and coin).


async def _complete_favor_stage(member_ids, favor_amount, patrons, *, fail_after=False, room=None):
    """Complete a one-stage quest granting `favor_amount` favor. `patrons` maps player_id ->
    patron id ('none' for unaligned). Returns (mutations, room, response)."""
    quest = {
        "id": "fq",
        "name": "Favor Quest",
        "stages": [
            {"id": 0, "objective": "begin", "on_complete": {"favor": favor_amount}},
            {"id": 1, "objective": "next", "on_complete": {}},
        ],
    }
    room = room or make_mock_room()
    mock_db, _ = make_db_mod()
    content = MagicMock()
    content.get_quest = AsyncMock(return_value=quest)
    content.get_item = AsyncMock(return_value=None)
    queries = MagicMock()
    queries.get_player_quest = AsyncMock(return_value={"current_stage": 0})
    queries.get_player = AsyncMock(side_effect=lambda pid, **kw: {**GUILD_PLAYER, "player_id": pid})
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(
        side_effect=lambda pid, **kw: {"patron": patrons[pid], "level": 10, "max": 100, "last_whisper_level": 0}
    )
    mutations = MagicMock()
    mutations.set_player_quest = AsyncMock(side_effect=RuntimeError("tx blew up") if fail_after else AsyncMock())
    mutations.update_player_xp = AsyncMock()
    mutations.add_inventory_item = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    mutations.update_divine_favor = AsyncMock()
    ctx = make_context(room=room, party_member_ids=member_ids[1:])
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
async def test_a_rolled_back_stage_publishes_no_favor():
    """The cue is buffered, not published, until the transaction commits — so a failure after
    the favor write announces nothing the database does not hold."""
    room = make_mock_room()
    with pytest.raises(RuntimeError):
        await _complete_favor_stage(["player_1"], 5, {"player_1": "kaelen"}, fail_after=True, room=room)

    # Nothing reached the wire: publish happens only after the `async with` block returns.
    published = [json.loads(c[0][0])["type"] for c in room.local_participant.publish_data.call_args_list]
    assert E.DIVINE_FAVOR_CHANGED not in published
