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
