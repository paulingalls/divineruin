import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_db_mod

from errand_tools import _resolve_companion_errand_impl
from training_tools import _initiate_training_cycle_impl, _resolve_training_midpoint_impl

from . import (
    guest_context,
    module,
    revocable_context,
    revoke_after,
    transaction_probe,
)


@pytest.mark.asyncio
async def test_guest_training_begin_owns_cycle_and_host_cycle_does_not_block():
    context, actor = guest_context()
    training = MagicMock(
        get_player_active_training_activities=AsyncMock(
            side_effect=lambda player_id, **_: [{"state": "in_progress"}] if player_id == "player_1" else []
        ),
        create_training_activity=AsyncMock(return_value="guest_cycle"),
    )
    content = MagicMock(
        get_training_program=AsyncMock(
            return_value={"id": "combat_basics", "name": "Combat Basics", "training_activity_type": "technique_base"}
        )
    )
    db_mod, _ = make_db_mod()
    with actor:
        result = json.loads(
            await _initiate_training_cycle_impl(
                context,
                "combat_basics",
                db_mod=db_mod,
                db_training_mod=training,
                db_content_mod=content,
            )
        )
    assert result["activity_id"] == "guest_cycle"
    assert training.create_training_activity.await_args.kwargs["player_id"] == "player_2"


@pytest.mark.asyncio
async def test_guest_training_resolve_owns_row():
    context, actor = guest_context()
    training = module(
        get_training_activity={
            "id": "cycle",
            "player_id": "player_2",
            "state": "awaiting_decision",
            "activity_type": "technique_base",
        },
        update_training_activity=None,
    )
    with actor:
        result = json.loads(
            await _resolve_training_midpoint_impl(
                context,
                "cycle",
                "focus",
                db_mod=make_db_mod()[0],
                db_training_mod=training,
                rules_mod=lambda *_: SimpleNamespace(
                    state="running_second_half", second_half_seconds=3600, micro_bonus=1, completes_at=datetime.now(UTC)
                ),
            )
        )
    assert result["activity_id"] == "cycle"
    training.update_training_activity.assert_awaited_once()


@pytest.mark.asyncio
async def test_guest_cannot_resolve_host_training_or_errand():
    context, actor = guest_context()
    training = module(
        get_training_activity={"player_id": "player_1", "state": "awaiting_decision"}, update_training_activity=None
    )
    activity = module(get_activity={"player_id": "player_1", "outcome": {"tier": "success"}})
    with actor:
        with pytest.raises(ToolError, match="does not belong"):
            await _resolve_training_midpoint_impl(
                context, "host_cycle", "focus", db_mod=make_db_mod()[0], db_training_mod=training
            )
        with pytest.raises(ToolError, match="does not belong"):
            await _resolve_companion_errand_impl(context, "host_errand", db_mod=make_db_mod()[0], activity_mod=activity)
    training.update_training_activity.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_training_create_activity():
    context, actor, revocation = revocable_context()
    training = MagicMock(
        get_player_active_training_activities=AsyncMock(
            side_effect=lambda player_id, **_: [{"state": "in_progress"}] if player_id == "player_1" else []
        ),
        create_training_activity=AsyncMock(return_value="guest_cycle"),
    )
    content = MagicMock(
        get_training_program=AsyncMock(
            return_value={"id": "combat_basics", "name": "Combat Basics", "training_activity_type": "technique_base"}
        )
    )
    revoke_after(training.get_player_active_training_activities, revocation)
    tx_db, tx_state = transaction_probe()
    db_mod = tx_db
    result = None
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        result = json.loads(
            await _initiate_training_cycle_impl(
                context,
                "combat_basics",
                db_mod=db_mod,
                db_training_mod=training,
                db_content_mod=content,
            )
        )
    training.create_training_activity.assert_not_awaited()
    assert tx_state["rolled_back"]
    assert not tx_state["committed"]
    assert result is None


@pytest.mark.asyncio
async def test_stale_training_update_activity():
    context, actor, revocation = revocable_context()
    training = module(
        get_training_activity={
            "id": "cycle",
            "player_id": "player_2",
            "state": "awaiting_decision",
            "activity_type": "technique_base",
        },
        update_training_activity=None,
    )
    revoke_after(training.get_training_activity, revocation)
    tx_db, tx_state = transaction_probe()
    result = None
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        result = json.loads(
            await _resolve_training_midpoint_impl(
                context,
                "cycle",
                "focus",
                db_mod=tx_db,
                db_training_mod=training,
                rules_mod=lambda *_: SimpleNamespace(
                    state="running_second_half", second_half_seconds=3600, micro_bonus=1, completes_at=datetime.now(UTC)
                ),
            )
        )
    training.update_training_activity.assert_not_awaited()
    assert tx_state["rolled_back"]
    assert not tx_state["committed"]
    assert result is None
