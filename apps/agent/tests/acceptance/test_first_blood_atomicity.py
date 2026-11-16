"""A failed combat-end transaction cannot leave First Blood paid or remembered."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.first_blood_walk import FirstBloodWalk
from livekit.agents.llm import ToolError

import db_mutations
import db_queries


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.mark.parametrize("route", ["end_combat", "resolve_phase"])
def test_first_blood_rollback_and_retry(harness, route):
    async def check():
        with patch("check_resolution.dice_roll", side_effect=lambda *_, **__: _d20(20)):
            arc = await FirstBloodWalk().start(harness, route)
            await arc.prepare()
            before = await arc.snapshot()
            original = db_mutations.delete_combat_state
            reached = []

            async def fail_after_delete(combat_id, *, conn=None):
                await original(combat_id, conn=conn)
                marker = await db_queries.get_player_quest(arc.player, "greyvale_anomaly", conn=conn)
                assert marker is not None and marker["current_stage"] == 3
                player = await db_queries.get_player(arc.player, conn=conn)
                assert player is not None and player["xp"] == arc.initial_xp + 150 + arc.combat_xp
                reached.append(combat_id)
                raise ToolError("injected terminal rollback")

            with patch.object(db_mutations, "delete_combat_state", side_effect=fail_after_delete):
                args = {"outcome": "victory"} if route == "end_combat" else {}
                output = await arc.command(route, args, error=True)
                assert "injected terminal rollback" in output
            assert reached == [arc.combat_id]
            assert await arc.snapshot() == before
            result = await arc.end()
            await arc.rewarded(result)
            await arc.replay_refused()

    harness.run_sync(check())
