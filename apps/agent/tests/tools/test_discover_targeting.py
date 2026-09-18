import json
from unittest.mock import AsyncMock, patch

import pytest

from check_discovery import _check_discover_impl
from tools._discover_fixtures import (
    LOCATION_ARCH,
    LOCATION_ATTACHED,
    LOCATION_MIXED,
    LOCATION_TWO_SECRETS,
    _make_discover_mocks,
    _roll,
)
from tools._helpers import _make_context


class TestCheckDiscover:
    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_attached_element_surfaces_on_its_target(self, mock_event):
        # Examining the target an element is attaches_to'd to surfaces that element.
        content, queries, mutations = _make_discover_mocks(location=LOCATION_ATTACHED)
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "arcana", "inner_door", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["outcome"] == "discovered"
        assert result["element_id"] == "door_seal"

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_attached_element_not_surfaced_on_other_target(self, mock_event):
        # An attaches_to'd element does NOT surface when a DIFFERENT target is examined,
        # and there is no unannotated fallback — so the search finds nothing.
        content, queries, mutations = _make_discover_mocks(location=LOCATION_ATTACHED)
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "arcana", "bookshelf", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["outcome"] == "not_found"
        mock_event.assert_not_called()

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_attaches_to_match_is_case_insensitive(self, mock_event):
        content, queries, mutations = _make_discover_mocks(location=LOCATION_ATTACHED)
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "arcana", "  Inner_Door  ", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["element_id"] == "door_seal"

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_mixed_examine_attached_target_prefers_attached(self, mock_event):
        # With an attached + an unannotated element, examining the attached target surfaces
        # the attached element (not the unannotated one).
        content, queries, mutations = _make_discover_mocks(location=LOCATION_MIXED)
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "inner_door", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["element_id"] == "door_seal"

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_mixed_examine_other_target_falls_back_to_unannotated(self, mock_event):
        # Examining a target nothing is attached to falls back to the unannotated element,
        # never the element attached to a different target.
        content, queries, mutations = _make_discover_mocks(location=LOCATION_MIXED)
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "the wall", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["element_id"] == "loose_brick"

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_prose_target_matches_token_attaches_to(self, mock_event):
        # The player examines the feature using the advertised key_feature prose; the bare
        # attaches_to token ("arch") is a whole word within it, so the element surfaces.
        content, queries, mutations = _make_discover_mocks(location=LOCATION_ARCH)
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            result = json.loads(
                await _check_discover_impl(
                    ctx,
                    "perception",
                    "the cracked stone arch to the north",
                    content=content,
                    queries=queries,
                    mutations=mutations,
                )
            )
        assert result["outcome"] == "discovered"
        assert result["element_id"] == "arch_seal"

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_token_attaches_to_no_midword_false_match(self, mock_event):
        # "arch" must match as a WORD, not a mid-word substring of "search" — otherwise an
        # unrelated examine would wrongly surface (and burn) the attached element.
        content, queries, mutations = _make_discover_mocks(location=LOCATION_ARCH)
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "search the alcove", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["outcome"] == "not_found"
        mock_event.assert_not_called()

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_multi_element_tiebreak_lowest_dc(self, mock_event):
        # Two perception secrets in the room — the lowest-DC one surfaces first.
        content, queries, mutations = _make_discover_mocks(location=LOCATION_TWO_SECRETS)
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(12)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["outcome"] == "discovered"
        assert result["element_id"] == "easy_secret"
        mutations.set_player_flag.assert_called_once_with("player_1", "easy_secret.discovered", True)

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_higher_dc_secret_reachable_after_lowest_exhausted(self, mock_event):
        # Failing the lowest-DC secret exhausts it for the session; the next search reaches
        # the higher-DC one instead of re-rolling the easy one.
        content, queries, mutations = _make_discover_mocks(location=LOCATION_TWO_SECRETS)
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", side_effect=[_roll(1), _roll(20)]):
            first = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
                )
            )
            second = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
                )
            )
        assert first["outcome"] == "not_found"  # easy_secret (DC 10) failed
        assert second["outcome"] == "discovered"
        assert second["element_id"] == "hard_secret"  # now reachable
