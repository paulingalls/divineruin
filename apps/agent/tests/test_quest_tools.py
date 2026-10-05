import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from inventory_snapshot_fixture import snapshot_query
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
    queries.get_player_inventory = AsyncMock(return_value=[])
    queries.get_inventory_snapshot = snapshot_query([])
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
    queries.get_player_inventory = AsyncMock(return_value=[])
    queries.get_inventory_snapshot = snapshot_query([])
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


@pytest.mark.asyncio
async def test_quest_stage_crossing_l10_writes_extra_attack_flag():
    mutations, conn, _, _ = await _complete_warrior_quest_stage(level=9, xp=2900, xp_reward=550)
    mutations.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)


@pytest.mark.asyncio
async def test_quest_stage_crossing_l5_publishes_specialization_choice():
    mutations, _, room, _ = await _complete_warrior_quest_stage(level=4, xp=750, xp_reward=300)
    assert E.SPECIALIZATION_CHOICE in published_types(room)
    mutations.set_player_flag.assert_not_awaited()


@pytest.mark.asyncio
async def test_quest_stage_response_surfaces_milestone_grants():
    _, _, _, response = await _complete_warrior_quest_stage(level=9, xp=2900, xp_reward=550)
    assert response["milestone_grants"] == [
        {"name": "Extra Attack", "effect": "Your blade strikes twice.", "narration_cue": "cue"}
    ]


@pytest.mark.asyncio
async def test_quest_stage_response_surfaces_specialization_fork():
    _, _, _, response = await _complete_warrior_quest_stage(level=4, xp=750, xp_reward=300)
    assert response["specialization_fork"] is True


@pytest.mark.asyncio
async def test_quest_stage_no_levelup_has_empty_grants_and_no_fork():
    mutations, _, _, response = await _complete_warrior_quest_stage(level=1, xp=0, xp_reward=50)
    assert response["milestone_grants"] == []
    assert response["specialization_fork"] is False
    mutations.set_player_flag.assert_not_awaited()


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
    queries.get_player_inventory = AsyncMock(return_value=[])
    queries.get_inventory_snapshot = snapshot_query([])
    queries.get_player_quest = AsyncMock(return_value={"current_stage": current_stage})
    queries.get_player = AsyncMock(return_value=GUILD_PLAYER)
    mutations = MagicMock()
    mutations.set_player_quest = AsyncMock()
    mutations.add_inventory_item = AsyncMock()
    return make_context(room=room), mock_db, mock_conn, content, queries, mutations


@pytest.mark.asyncio
async def test_completing_final_stage_fires_its_on_complete():
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
    ctx, mock_db, _, content, queries, mutations = _completion_mocks(current_stage=0)
    await _update_quest_impl(ctx, "cq", 1, db_mod=mock_db, mutations=mutations, queries=queries, content=content)
    mutations.add_inventory_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_stage_beyond_completion_rejected():
    ctx, mock_db, _, content, queries, mutations = _completion_mocks(current_stage=1)
    with pytest.raises(ToolError, match="Invalid stage"):
        await _update_quest_impl(ctx, "cq", 3, db_mod=mock_db, mutations=mutations, queries=queries, content=content)


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
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    quests = json.loads((root / "content" / "quests.json").read_text())
    greyvale = next(q for q in quests if q["id"] == "greyvale_anomaly")
    final = greyvale["stages"][-1]
    assert final["id"] == "stage_5_return"
    assert "accord_guild_reputation completed_faction_quest" in final["on_complete"]["world_effects"]


def test_greyvale_completion_authors_divine_favor():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    quests = json.loads((root / "content" / "quests.json").read_text())
    greyvale = next(q for q in quests if q["id"] == "greyvale_anomaly")
    final = greyvale["stages"][-1]
    assert final["on_complete"]["favor"] == 5
