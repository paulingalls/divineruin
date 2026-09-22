from unittest.mock import AsyncMock, patch

import pytest

from check_discovery import _check_discover_impl
from tools._discover_fixtures import _make_discover_mocks, _roll
from tools._helpers import _make_context


class TestDiscoverLockoutOrdering:
    """story-014: the in-memory anti-grind lockout must be added AFTER the persist succeeds, not
    before the roll — so a transient DB error that rolls back the discovery flag leaves the element
    re-attemptable this session. A failed attempt (no persist, no error) still locks out (the
    existing test_reworded_target_cannot_regrind guards that preservation)."""

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_persist_failure_leaves_element_reattemptable(self, _evt):
        # A successful roll whose discovery-flag persist raises: the in-memory lockout must NOT be
        # set, so the secret can be re-attempted once the DB recovers (no until-next-session lockout).
        content, queries, mutations = _make_discover_mocks()
        mutations.set_player_flag = AsyncMock(side_effect=RuntimeError("db down"))
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):  # >= dc 12 -> success -> persist
            with pytest.raises(RuntimeError):
                await _check_discover_impl(
                    ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
                )
        assert "player_1:perception:secret_door" not in ctx.userdata.attempted_discoveries

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_successful_persist_locks_out_element(self, _evt):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        assert "player_1:perception:secret_door" in ctx.userdata.attempted_discoveries
