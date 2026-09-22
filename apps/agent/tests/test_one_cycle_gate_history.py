"""One-cycle gates see running work beyond the public history limit."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import db
import db_training
from mentor_variant_tools import _learn_variant_impl
from training_tools import _initiate_training_cycle_impl


@pytest.fixture
async def player_with_long_history(dev_db_pool):
    player_id = f"test_player_{uuid.uuid4().hex}"
    await dev_db_pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)",
        player_id,
        json.dumps({"player_id": player_id, "name": "Historian", "class": "warrior", "level": 5}),
    )
    try:
        first = datetime(2020, 1, 1, tzinfo=UTC)
        for index in range(51):
            await dev_db_pool.execute(
                """INSERT INTO training_activities
                   (id, player_id, activity_type, state, data, created_at)
                   VALUES ($1, $2, 'technique_base', $3, '{}'::jsonb, $4)""",
                f"history_{uuid.uuid4().hex}",
                player_id,
                "complete" if index < 50 else "running_first_half",
                first + timedelta(seconds=index),
            )
        yield player_id
    finally:
        await dev_db_pool.execute("DELETE FROM training_activities WHERE player_id = $1", player_id)
        await dev_db_pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def activity_count(pool, player_id):
    return await pool.fetchval("SELECT count(*) FROM training_activities WHERE player_id = $1", player_id)


@pytest.mark.asyncio
async def test_training_gate_refuses_running_cycle_beyond_fifty_completed(player_with_long_history, dev_db_pool):
    player_id = player_with_long_history
    content = SimpleNamespace(
        get_training_program=AsyncMock(
            return_value={"id": "combat_basics", "name": "Combat Basics", "training_activity_type": "technique_base"}
        )
    )
    with pytest.raises(ToolError, match="already in progress"):
        await _initiate_training_cycle_impl(
            make_context(player_id=player_id),
            "combat_basics",
            db_mod=db,
            db_training_mod=db_training,
            db_content_mod=content,
        )
    assert await activity_count(dev_db_pool, player_id) == 51


@pytest.mark.asyncio
async def test_variant_gate_refuses_running_cycle_beyond_fifty_completed(player_with_long_history, dev_db_pool):
    player_id = player_with_long_history
    variant = SimpleNamespace(
        ability_id="warrior_cleaving_blow", mentor_id="guildmaster_torin", cultural_attribution="Drathian"
    )
    with pytest.raises(ToolError, match="already in progress"):
        await _learn_variant_impl(
            make_context(player_id=player_id),
            "cleaving_drathian",
            db_mod=db,
            db_training_mod=db_training,
            variants_mod=SimpleNamespace(get_mentor_variant=lambda _: variant),
            requirements_mod=SimpleNamespace(
                check_mentor_requirements=AsyncMock(return_value=SimpleNamespace(met=True))
            ),
            preconditions_mod=SimpleNamespace(require_npc_present=AsyncMock()),
            content_mod=SimpleNamespace(get_npc=AsyncMock(return_value={"mentor": {"training_cycles": 3}})),
            progress_mod=SimpleNamespace(is_unlocked=AsyncMock(return_value=False), seed_progress=AsyncMock()),
            persistence_mod=SimpleNamespace(owns_elective=AsyncMock(return_value=True)),
        )
    assert await activity_count(dev_db_pool, player_id) == 51


@pytest.mark.asyncio
async def test_warm_layer_surfaces_running_cycle_beyond_fifty_completed(player_with_long_history):
    from unittest.mock import patch

    from background_process import BackgroundProcess
    from session_data import SessionData

    player_id = player_with_long_history
    session = SessionData(player_id=player_id, location_id="accord_guild_hall")
    process = BackgroundProcess(session=SimpleNamespace(), session_data=session)
    with (
        patch("background_process.db_queries.get_active_player_quests", new_callable=AsyncMock, return_value=[]),
        patch("background_process.db_content_queries.get_location", new_callable=AsyncMock, return_value=None),
        patch("background_process.db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=[]),
        patch("background_process.build_warm_layer", new_callable=AsyncMock, return_value="warm") as build,
        patch.object(process, "_apply_warm", new_callable=AsyncMock),
    ):
        await process._rebuild_warm_layer()
    active = build.await_args.kwargs["training"]
    assert len(active) == 1
    assert active[0]["state"] == "running_first_half"
    assert active[0]["player_id"] == player_id
