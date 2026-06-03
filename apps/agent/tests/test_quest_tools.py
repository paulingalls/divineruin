"""Quest completion tests — archetype-aware LEVEL_UP hp_gains + milestone side-effects
routed through the shared _award_xp_core Resolve (story-002)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import (
    _WARRIOR_MILESTONES,
    GUILD_PLAYER,
    _milestones_mod_for,
    level_up_payload,
    make_context,
    make_db_mod,
    make_mock_room,
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


def _published_types(room):
    """Event types published to the room's data channel, in order."""
    return [json.loads(c[0][0])["type"] for c in room.local_participant.publish_data.call_args_list]


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
    assert E.SPECIALIZATION_CHOICE in _published_types(room)
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
    # The L5 fork cue reaches the DM in the quest response, symmetric to award_xp.
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
