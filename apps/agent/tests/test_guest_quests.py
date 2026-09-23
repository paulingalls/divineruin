import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import GUILD_PLAYER, make_context, make_db_mod, make_mock_room, published_events

import event_types as E
from quest_tools import _update_quest_impl
from quest_world_effects import _apply_world_effects
from session_summary import generate_session_summary


async def named_recap(sd, player_id):
    with (
        patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=None),
        patch("db_activity_queries.get_session_story_moments", new_callable=AsyncMock, return_value=[]),
    ):
        return await generate_session_summary(sd, None, player_id=player_id)


def quest_case(stages, progress=None):
    ctx = make_context(room=make_mock_room(), party_member_ids=["player_2"])
    db_mod, conn = make_db_mod()
    rows = {pid: {"current_stage": stage} for pid, stage in (progress or {}).items()}
    quest = {"name": "Guest Quest", "stages": stages}
    content = MagicMock(get_quest=AsyncMock(return_value=quest), get_item=AsyncMock(return_value=None))
    queries = MagicMock(
        get_player_quest=AsyncMock(side_effect=lambda pid, *_args, **_kw: rows.get(pid)),
        get_player=AsyncMock(side_effect=lambda pid, **_kw: {**GUILD_PLAYER, "player_id": pid}),
    )
    mutations = MagicMock(
        set_player_quest=AsyncMock(side_effect=lambda pid, _qid, data, **_kw: rows.__setitem__(pid, data)),
        add_inventory_item=AsyncMock(),
        update_player_xp=AsyncMock(),
        set_player_flag=AsyncMock(),
    )
    return ctx, db_mod, conn, rows, content, queries, mutations


async def advance(case, stage, **extra):
    ctx, db_mod, _, _, content, queries, mutations = case
    return json.loads(
        await _update_quest_impl(
            ctx,
            "guest_quest",
            stage,
            db_mod=db_mod,
            content=content,
            queries=queries,
            mutations=mutations,
            **extra,
        )
    )


@pytest.mark.asyncio
async def test_guest_advances_after_host_rewardless_stage():
    case = quest_case([{"on_complete": {}}, {"on_complete": {}}])
    with case[0].userdata._bind_authenticated_actor("player_1", 1, lambda *_: None):
        await advance(case, 0)
        await advance(case, 1)
    with case[0].userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        result = await advance(case, 2)
    assert result["completed"]
    assert case[3]["player_1"]["current_stage"] == 2
    assert "player_2" not in case[3]


@pytest.mark.asyncio
async def test_guest_item_only_completion_pays_and_marks_both_once():
    case = quest_case(
        [{"on_complete": {"rewards": [{"item": "relic"}, {"item": "relic", "quantity": 2}]}}],
        {"player_1": 0, "player_2": 0},
    )
    case[4].get_item.return_value = {"name": "Sun Relic"}
    with case[0].userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        result = await advance(case, 1)
    assert result["completed"]
    assert [call.args[:3] for call in case[6].add_inventory_item.await_args_list] == [
        ("player_1", "relic", 1),
        ("player_2", "relic", 1),
        ("player_1", "relic", 2),
        ("player_2", "relic", 2),
    ]
    assert result["rewards_applied"] == [
        {"type": "item", "item_id": "relic", "quantity": 1},
        {"type": "item", "item_id": "relic", "quantity": 2},
    ]
    assert case[0].userdata.player_summary_metrics["player_1"]["items_found"] == ["Sun Relic"]
    assert case[0].userdata.player_summary_metrics["player_2"]["items_found"] == ["Sun Relic"]
    assert case[0].userdata.session_items_found == ["Sun Relic"]
    assert (await named_recap(case[0].userdata, "player_1"))["items_found"] == ["Sun Relic"]
    assert (await named_recap(case[0].userdata, "player_2"))["items_found"] == ["Sun Relic"]
    assert {call.args[0] for call in case[6].set_player_quest.await_args_list} == {"player_1", "player_2"}
    with case[0].userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        with pytest.raises(ToolError, match="backward"):
            await advance(case, 1)
    assert case[6].add_inventory_item.await_count == 4


@pytest.mark.asyncio
async def test_quest_commit_failure_records_no_items():
    case = quest_case([{"on_complete": {"rewards": [{"item": "relic"}]}}], {"player_1": 0, "player_2": 0})
    case[4].get_item.return_value = {"name": "Sun Relic"}

    @asynccontextmanager
    async def failed_transaction():
        yield case[2]
        raise RuntimeError("commit failed")

    case[1].transaction = failed_transaction
    with case[0].userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        with pytest.raises(RuntimeError, match="commit failed"):
            await advance(case, 1)
    assert case[6].add_inventory_item.await_count == 2
    assert case[0].userdata.session_items_found == []
    for pid in ("player_1", "player_2"):
        assert case[0].userdata.player_summary_metrics.get(pid, {}).get("items_found", []) == []
        assert (await named_recap(case[0].userdata, pid))["items_found"] == []


@pytest.mark.asyncio
async def test_guest_completion_pays_xp_favor_and_items_to_both():
    case = quest_case(
        [
            {
                "on_complete": {
                    "xp": 200,
                    "favor": 5,
                    "rewards": [{"item": "relic"}],
                }
            }
        ],
        {"player_1": 0, "player_2": 0},
    )
    activities = MagicMock(
        get_divine_favor=AsyncMock(
            side_effect=lambda pid, **_kw: {
                "patron": "kaelen" if pid == "player_1" else "solwyn",
                "level": 10,
                "max": 100,
                "last_whisper_level": 0,
            }
        )
    )
    divine = MagicMock(update_divine_favor=AsyncMock())
    with case[0].userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        result = await advance(case, 1, activities=activities, divine_mutations=divine)
    assert {call.args[0] for call in case[6].update_player_xp.await_args_list} == {"player_1", "player_2"}
    metrics = case[0].userdata.player_summary_metrics
    assert metrics["player_1"]["xp_earned"] == metrics["player_2"]["xp_earned"] > 0
    assert all(metrics[pid]["quest_progress"] for pid in ("player_1", "player_2"))
    assert {call.args[0] for call in divine.update_divine_favor.await_args_list} == {"player_1", "player_2"}
    assert {call.args[0] for call in case[6].add_inventory_item.await_args_list} == {"player_1", "player_2"}
    assert {reward["type"] for reward in result["rewards_applied"]} == {"xp", "favor", "item"}


@pytest.mark.asyncio
async def test_guest_quest_xp_counts_host_grant_when_guest_was_already_paid():
    case = quest_case([{"on_complete": {"xp": 100}}], {"player_1": 0, "player_2": 1})
    with case[0].userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        result = await advance(case, 1)
    assert not any(reward["type"] == "xp" for reward in result["rewards_applied"])
    assert [call.args[0] for call in case[6].update_player_xp.await_args_list] == ["player_1"]
    assert case[0].userdata.session_xp_earned > 0


@pytest.mark.asyncio
async def test_item_reward_skips_member_already_ahead():
    case = quest_case(
        [{"on_complete": {"rewards": [{"item": "relic"}]}}, {"on_complete": {}}], {"player_1": 0, "player_2": 2}
    )
    with case[0].userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        result = await advance(case, 1)
    assert {call.args[0] for call in case[6].add_inventory_item.await_args_list} == {"player_1"}
    assert [call.args[0] for call in case[6].set_player_quest.await_args_list] == ["player_1"]
    assert result["rewards_applied"] == []


@pytest.mark.asyncio
async def test_guest_corruption_effect_changes_each_members_own_level():
    case = quest_case([{"on_complete": {"world_effects": ["greyvale_corruption +1"]}}], {"player_1": 0, "player_2": 0})
    case[0].userdata.member_state("player_1").corruption_level = 2
    case[0].userdata.member_state("player_2").corruption_level = 0
    case[0].userdata.event_bus = MagicMock()
    with case[0].userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        await advance(case, 1)
    assert case[0].userdata.member_state("player_1").corruption_level == 3
    assert case[0].userdata.member_state("player_2").corruption_level == 1
    events = [e.payload for e in published_events(case[0]) if e.event_type == E.HOLLOW_CORRUPTION_CHANGED]
    assert len(events) == 2
    assert {e["player_id"]: (e["previous"], e["level"]) for e in events} == {"player_1": (2, 3), "player_2": (0, 1)}


@pytest.mark.asyncio
async def test_guest_corruption_decrease_clamps_each_member_at_floor():
    case = quest_case([{"on_complete": {"world_effects": ["greyvale_corruption -1"]}}], {"player_1": 0, "player_2": 0})
    case[0].userdata.member_state("player_1").corruption_level = 0
    case[0].userdata.member_state("player_2").corruption_level = 2
    with case[0].userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        await advance(case, 1)
    assert [case[0].userdata.member_state(pid).corruption_level for pid in ("player_1", "player_2")] == [0, 1]


@pytest.mark.asyncio
async def test_corruption_stays_unchanged_when_quest_write_fails():
    case = quest_case([{"on_complete": {"world_effects": ["greyvale_corruption -1"]}}], {"player_1": 0, "player_2": 0})
    case[0].userdata.member_state("player_1").corruption_level = 3
    case[0].userdata.member_state("player_2").corruption_level = 1
    case[6].set_player_quest.side_effect = RuntimeError("write failed")
    with case[0].userdata._bind_authenticated_actor("player_2", 1, lambda *_: None):
        with pytest.raises(RuntimeError, match="write failed"):
            await advance(case, 1)
    assert [case[0].userdata.member_state(pid).corruption_level for pid in ("player_1", "player_2")] == [3, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("speaker", ["player_1", "player_2"])
async def test_quest_standing_effects_reach_each_member(speaker):
    case = quest_case([{"on_complete": {}}], {"player_1": 0, "player_2": 0})
    ctx, _, conn, _, content, queries, mutations = case
    content.get_faction = AsyncMock(return_value={"id": "thornwatch"})
    content.get_npc = AsyncMock(return_value={"default_disposition": "neutral"})
    queries.get_npc_disposition = AsyncMock(return_value="neutral")
    mutations.set_npc_disposition = AsyncMock()
    events = []
    reputation = MagicMock(adjust_player_faction_reputation=AsyncMock(return_value=-5))
    with ctx.userdata._bind_authenticated_actor(speaker, 1, lambda *_: None):
        await _apply_world_effects(
            ["torin_disposition +1", "thornwatch_reputation killed_faction_member"],
            ctx.userdata,
            events,
            conn=conn,
            content=content,
            queries=queries,
            mutations=mutations,
            reputation_mutations=reputation,
        )
    assert [call.args[0] for call in reputation.adjust_player_faction_reputation.await_args_list] == [
        "player_1",
        "player_2",
    ]
    assert [call.args[1] for call in mutations.set_npc_disposition.await_args_list] == ["player_1", "player_2"]
    assert all(call.kwargs["conn"] is conn for call in reputation.adjust_player_faction_reputation.await_args_list)


def revoked_after(allowed_checks):
    calls = 0

    def validate(*_):
        nonlocal calls
        calls += 1
        if calls > allowed_checks:
            raise RuntimeError("stale")

    return validate


@pytest.mark.asyncio
async def test_guest_revoked_before_quest_locks_takes_none():
    case = quest_case([{"on_complete": {"rewards": [{"item": "relic"}]}}], {"player_1": 0, "player_2": 0})
    with case[0].userdata._bind_authenticated_actor("player_2", 1, revoked_after(1)):
        with pytest.raises(RuntimeError, match="stale"):
            await advance(case, 1)
    case[5].get_player_quest.assert_not_awaited()
    case[6].add_inventory_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_guest_revoked_before_quest_marker_writes_none():
    case = quest_case([{"on_complete": {"rewards": [{"item": "relic"}]}}], {"player_1": 0, "player_2": 0})
    with case[0].userdata._bind_authenticated_actor("player_2", 1, revoked_after(2)):
        with pytest.raises(RuntimeError, match="stale"):
            await advance(case, 1)
    case[6].set_player_quest.assert_not_awaited()
