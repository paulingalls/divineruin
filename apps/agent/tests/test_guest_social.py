import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import _WARRIOR_MILESTONES, make_context, make_db_mod

from card_tap_handler import SpecializationTapHandler
from choice_tools import _select_impl
from db_activity_queries import count_session_story_moments
from reputation_tools import _adjust_faction_reputation_impl
from session_tools import _record_story_moment_impl, _update_npc_disposition_impl


def party_context():
    return make_context(party_member_ids=["player_2"])


def choice_seams(host=None, guest=None):
    db, conn = make_db_mod()
    rows = {
        "player_1": host or {"class": "guardian", "level": 5},
        "player_2": guest or {"class": "warrior", "level": 5},
    }
    queries = MagicMock(get_players_for_update=AsyncMock(return_value=rows))
    persistence = MagicMock(set_player_specialization=AsyncMock())
    milestone = next(m for m in _WARRIOR_MILESTONES if m.id == "warrior_identity")
    catalog = MagicMock(get_milestone=MagicMock(return_value=milestone))
    return db, conn, queries, persistence, catalog


async def choose(ctx, seams):
    db, _, queries, persistence, catalog = seams
    return await _select_impl(
        ctx,
        "warrior_identity",
        "battle_master",
        db_mod=db,
        queries_mod=queries,
        persistence_mod=persistence,
        milestones_mod=catalog,
    )


async def test_guest_disposition_reads_and_writes_guest_row():
    ctx = party_context()
    db, conn = make_db_mod()
    queries = MagicMock(
        get_npc_disposition=AsyncMock(side_effect=lambda _, pid, **__: "unfriendly" if pid == "player_2" else "trusted")
    )
    queries.get_npcs_at_location = AsyncMock(return_value=[{"npc_id": "keeper"}])
    mutations = MagicMock(set_npc_disposition=AsyncMock())
    content = MagicMock(get_npc=AsyncMock(return_value={"name": "Keeper"}))
    with (
        patch("session_tools.require_npc_present", AsyncMock()),
        patch("session_tools.publish_game_event", AsyncMock()),
    ):
        with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_: None):
            result = json.loads(
                await _update_npc_disposition_impl(
                    ctx, "keeper", 1, "helped", db_mod=db, queries=queries, mutations=mutations, content=content
                )
            )
    assert result["previous"] == "unfriendly"
    queries.get_npc_disposition.assert_awaited_once_with("keeper", "player_2", conn=conn, for_update=True)
    assert mutations.set_npc_disposition.await_args.args[:2] == ("keeper", "player_2")


async def test_guest_disposition_revoked_before_write_refuses():
    ctx = party_context()
    db, _ = make_db_mod()
    queries = MagicMock(get_npc_disposition=AsyncMock(return_value="neutral"))
    mutations = MagicMock(set_npc_disposition=AsyncMock())
    content = MagicMock(get_npc=AsyncMock(return_value={"name": "Keeper"}))
    calls = 0

    def validate(*_):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("stale")

    with patch("session_tools.require_npc_present", AsyncMock()):
        with ctx.userdata._bind_authenticated_actor("player_2", 4, validate):
            with pytest.raises(RuntimeError, match="stale"):
                await _update_npc_disposition_impl(
                    ctx, "keeper", 1, "helped", db_mod=db, queries=queries, mutations=mutations, content=content
                )
    mutations.set_npc_disposition.assert_not_awaited()


async def test_guest_reputation_writes_guest_row():
    ctx = party_context()
    mutations = MagicMock(adjust_player_faction_reputation=AsyncMock(return_value=5))
    content = MagicMock(get_faction=AsyncMock(return_value={"name": "Guild"}))
    with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_: None):
        result = json.loads(
            await _adjust_faction_reputation_impl(
                ctx, "accord_guild", "completed_faction_quest", "helped", mutations=mutations, content=content
            )
        )
    assert result["new_value"] == 5
    assert mutations.adjust_player_faction_reputation.await_args.args[0] == "player_2"


async def test_guest_reputation_revoked_before_write_refuses():
    ctx = party_context()
    mutations = MagicMock(adjust_player_faction_reputation=AsyncMock())
    content = MagicMock(get_faction=AsyncMock(return_value={"name": "Guild"}))
    calls = 0

    def validate(*_):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("stale")

    with ctx.userdata._bind_authenticated_actor("player_2", 4, validate):
        with pytest.raises(RuntimeError, match="stale"):
            await _adjust_faction_reputation_impl(
                ctx, "accord_guild", "completed_faction_quest", "helped", mutations=mutations, content=content
            )
    mutations.adjust_player_faction_reputation.assert_not_awaited()


async def test_guest_select_resolves_only_guest_fork():
    ctx = party_context()
    seams = choice_seams()
    with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_: None):
        result = json.loads(await choose(ctx, seams))
    assert result["player_id"] == "player_2"
    seams[3].set_player_specialization.assert_awaited_once_with("player_2", "battle_master", conn=seams[1])


async def test_host_cannot_resolve_guests_sole_pending_fork():
    ctx = party_context()
    seams = choice_seams()
    with pytest.raises(ToolError, match="your specialization"):
        await choose(ctx, seams)
    seams[3].set_player_specialization.assert_not_awaited()


async def test_guest_select_revoked_before_write_refuses():
    ctx = party_context()
    seams = choice_seams()
    calls = 0

    def validate(*_):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("stale")

    with ctx.userdata._bind_authenticated_actor("player_2", 4, validate):
        with pytest.raises(RuntimeError, match="stale"):
            await choose(ctx, seams)
    seams[3].set_player_specialization.assert_not_awaited()


async def test_guest_can_record_when_host_has_three_moments():
    ctx = party_context()
    mutations = MagicMock(save_story_moment=AsyncMock())
    activities = MagicMock(
        count_session_story_moments=AsyncMock(side_effect=lambda _, pid: 0 if pid == "player_2" else 3)
    )
    with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_: None):
        result = json.loads(
            await _record_story_moment_impl(ctx, "combat", "Victory", mutations=mutations, activities=activities)
        )
    assert result["recorded"] is True
    activities.count_session_story_moments.assert_awaited_once_with(ctx.userdata.session_id, "player_2")
    assert mutations.save_story_moment.await_args.kwargs["player_id"] == "player_2"


async def test_host_at_three_gets_narratable_tool_error():
    ctx = party_context()
    mutations = MagicMock(save_story_moment=AsyncMock())
    activities = MagicMock(count_session_story_moments=AsyncMock(return_value=3))
    with pytest.raises(ToolError, match="per player in this session"):
        await _record_story_moment_impl(ctx, "combat", "Again", mutations=mutations, activities=activities)
    mutations.save_story_moment.assert_not_awaited()


async def test_guest_moment_revoked_before_save_refuses():
    ctx = party_context()
    mutations = MagicMock(save_story_moment=AsyncMock())
    activities = MagicMock(count_session_story_moments=AsyncMock(return_value=0))
    calls = 0

    def validate(*_):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("stale")

    with ctx.userdata._bind_authenticated_actor("player_2", 4, validate):
        with pytest.raises(RuntimeError, match="stale"):
            await _record_story_moment_impl(ctx, "combat", "Victory", mutations=mutations, activities=activities)
    mutations.save_story_moment.assert_not_awaited()


async def test_story_moment_count_sql_filters_player_and_session():
    conn = MagicMock(fetchrow=AsyncMock(return_value={"cnt": 2}))
    assert await count_session_story_moments("session-1", "player_2", conn=conn) == 2
    sql, session_id, player_id = conn.fetchrow.await_args.args
    assert "session_id = $1" in sql and "player_id = $2" in sql
    assert (session_id, player_id) == ("session-1", "player_2")


async def test_guest_hud_tap_resolves_guest_fork():
    ctx = party_context()
    lifecycle = MagicMock(
        current_generation=MagicMock(return_value=4),
        is_authorized=MagicMock(return_value=True),
        require_authorized=MagicMock(),
    )
    ctx.userdata.multiplayer_owner = SimpleNamespace(lifecycle=lifecycle)
    seams = choice_seams()
    session = MagicMock()
    task = None

    def generate_reply(**_):
        nonlocal task
        task = asyncio.create_task(choose(ctx, seams))

    session.generate_reply.side_effect = generate_reply
    handler = SpecializationTapHandler(room=MagicMock(), session=session, userdata=ctx.userdata)
    assert handler._handle(
        {"type": "specialization_choice_tap", "milestone_id": "warrior_identity", "specialization_id": "battle_master"},
        "player_2",
    )
    assert json.loads(await task)["player_id"] == "player_2"
    seams[3].set_player_specialization.assert_awaited_once_with("player_2", "battle_master", conn=seams[1])
