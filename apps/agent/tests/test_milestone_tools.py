"""Unit tests for apply_milestone_grant (milestone_tools.py).

The shared grant-write primitive that award_xp's auto-grant loop (_award_xp_core)
calls at the L10/15/20 leveling chokepoint: writes a milestone's combat flag into
players.data.flags when present, no-op for a narrative-only (flag=None) grant.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from milestone_tools import apply_milestone_grant
from milestones import Grant, Milestone, MilestoneKind


def _milestone(kind: MilestoneKind, grant: Grant | None) -> Milestone:
    return Milestone("warrior_power", "warrior", "power", 10, kind, False, (), grant, "cue")


class TestApplyMilestoneGrant:
    """Direct unit tests for the shared grant-write primitive, called by award_xp's
    auto-grant loop (_award_xp_core)."""

    @pytest.mark.asyncio
    async def test_flag_grant_writes_flag_and_returns_true(self):
        flags = MagicMock()
        flags.set_player_flag = AsyncMock()
        conn = MagicMock()
        milestone = _milestone("auto_grant", Grant("Extra Attack", "strikes twice", "extra_attack"))
        wrote = await apply_milestone_grant(milestone, "player_1", conn=conn, flags_mod=flags)
        assert wrote is True
        flags.set_player_flag.assert_awaited_once_with("player_1", "extra_attack", True, conn=conn)

    @pytest.mark.asyncio
    async def test_narrative_only_grant_is_noop_and_returns_false(self):
        flags = MagicMock()
        flags.set_player_flag = AsyncMock()
        milestone = _milestone("auto_grant", Grant("Indomitable", "reroll a save", None))
        wrote = await apply_milestone_grant(milestone, "player_1", conn=MagicMock(), flags_mod=flags)
        assert wrote is False
        flags.set_player_flag.assert_not_called()

    @pytest.mark.asyncio
    async def test_null_grant_is_noop_and_returns_false(self):
        flags = MagicMock()
        flags.set_player_flag = AsyncMock()
        milestone = _milestone("specialization_fork", None)
        wrote = await apply_milestone_grant(milestone, "player_1", conn=MagicMock(), flags_mod=flags)
        assert wrote is False
        flags.set_player_flag.assert_not_called()
