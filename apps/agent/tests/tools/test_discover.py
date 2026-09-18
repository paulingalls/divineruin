"""Tests for check(mode="discover") — §7 skill/target discovery.

check(skill, target) takes a VISIBLE target; the hidden element's id is the Resolve's
OUTPUT on success, never an input. M5 scopes the location's hidden_elements room-wide by
matching discover_skill (the §7 fallback). Covers success/failure, skill-scoping,
the element-keyed anti-grind gate (skill:element_id), the dc-less event, and the
lowest-DC tie-break.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError

import event_types as E
from check_discovery import _check_discover_impl
from tools._discover_fixtures import DISCOVER_PLAYER, _make_discover_mocks, _roll
from tools._helpers import _make_context


class TestCheckDiscover:
    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_successful_discovery(self, mock_event):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["outcome"] == "discovered"
        assert "hidden passage" in result["description"]
        # The element id surfaces in the RESPONSE only (an output, never an input).
        assert result["element_id"] == "secret_door"
        assert result["target"] == "bookshelf"
        mutations.set_player_flag.assert_called_once_with("player_1", "secret_door.discovered", True)

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_dice_roll_carries_dramatic_verdict(self, mock_event):
        # Discover-mode DICE_ROLL must surface the resolver's dramatic verdict (nat-20),
        # matching the skill/save emission contract (story-005/006). A nat-20 here is
        # dramatic with context "natural_20"; the client overlay gates on the flag.
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(20)):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        dice_payload = next(
            call.args[2] for call in mock_event.call_args_list if call.args[2].get("roll_type") == "skill_check"
        )
        assert dice_payload["dramatic"] is True
        assert dice_payload["context"] == "natural_20"

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_routine_discover_roll_not_dramatic(self, mock_event):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        dice_payload = next(
            call.args[2] for call in mock_event.call_args_list if call.args[2].get("roll_type") == "skill_check"
        )
        assert dice_payload["dramatic"] is False
        assert dice_payload["context"] == ""

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_failed_discovery(self, mock_event):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(3)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["outcome"] == "not_found"
        assert "description" not in result
        mutations.set_player_flag.assert_not_called()

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_no_matching_skill_returns_not_found(self, mock_event):
        # A skill with no scoped hidden element is a valid "found nothing", not an error.
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        result = json.loads(
            await _check_discover_impl(
                ctx, "arcana", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        )
        assert result["outcome"] == "not_found"
        mock_event.assert_not_called()

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_no_candidate_search_is_retryable(self, mock_event):
        # A search that finds NO matching element never rolled, so it must not block a
        # retry — re-searching returns not_found again, not "Already searched".
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        first = json.loads(
            await _check_discover_impl(
                ctx, "arcana", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        )
        second = json.loads(
            await _check_discover_impl(
                ctx, "arcana", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        )
        assert first["outcome"] == "not_found"
        assert second["outcome"] == "not_found"
        mock_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_skill_raises(self):
        content, queries, _ = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with pytest.raises(ToolError, match="skill"):
            await _check_discover_impl(ctx, "flying", "bookshelf", content=content, queries=queries)

    @pytest.mark.asyncio
    async def test_location_not_found(self):
        content = MagicMock()
        content.get_location = AsyncMock(return_value=None)
        ctx = _make_context(location_id="nowhere")
        with pytest.raises(ToolError, match="not found"):
            await _check_discover_impl(ctx, "perception", "bookshelf", content=content)

    @pytest.mark.asyncio
    async def test_corrupt_conditions_fail_loud_as_toolerror(self):
        # M4.4 story-008 (concern 988e3e4f55ea): a corrupt stored conditions row surfaces as a
        # DM-narratable ToolError before the resolver hits get_condition_effects.
        corrupt_player = {**DISCOVER_PLAYER, "conditions": [{"type": "bogus"}]}
        content, queries, mutations = _make_discover_mocks(player=corrupt_player)
        ctx = _make_context(location_id="test_location")
        with pytest.raises(ToolError, match="corrupt stored conditions"):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_repeat_search_finds_nothing_new(self, mock_event):
        # A failed roll exhausts that secret for the session — re-searching the same target
        # finds nothing new (not_found), rather than re-rolling it.
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(3)):
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
        assert first["outcome"] == "not_found"
        assert second["outcome"] == "not_found"

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_reworded_target_cannot_regrind(self, mock_event):
        # The anti-grind gate keys on the element, not the free-text target: re-searching the
        # same secret under a different target wording must NOT earn a fresh roll at it.
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(3)) as mock_dice:
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
            first_roll_calls = mock_dice.call_count
            # Reword the target — the perception secret is already attempted, so no new roll.
            result = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "the shelf", content=content, queries=queries, mutations=mutations
                )
            )
            assert mock_dice.call_count == first_roll_calls  # no second roll
        assert result["outcome"] == "not_found"

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_already_discovered_flag_excludes_candidate(self, mock_event):
        # The permanent (cross-session) guard: an element already flagged discovered on the
        # player is excluded from the candidate pool, so re-searching finds nothing and never
        # re-rolls it.
        player = {**DISCOVER_PLAYER, "flags": {"secret_door.discovered": True}}
        content, queries, mutations = _make_discover_mocks(player=player)
        ctx = _make_context(location_id="test_location")
        result = json.loads(
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        )
        assert result["outcome"] == "not_found"
        mock_event.assert_not_called()

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_dice_roll_event_has_no_dc(self, mock_event):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        # The success path now publishes DICE_ROLL *and* HIDDEN_REVEALED — assert against
        # the DICE_ROLL event specifically, not whichever fired last.
        dice_calls = [c for c in mock_event.call_args_list if c[0][1] == E.DICE_ROLL]
        assert len(dice_calls) == 1
        assert "dc" not in dice_calls[0][0][2]

    @pytest.mark.asyncio
    @patch("check_discovery.publish_hidden_revealed", new_callable=AsyncMock)
    async def test_successful_discovery_emits_hidden_revealed(self, mock_reveal):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        mock_reveal.assert_awaited_once()
        assert mock_reveal.await_args.kwargs["element_id"] == "secret_door"

    @pytest.mark.asyncio
    @patch("check_discovery.publish_hidden_revealed", new_callable=AsyncMock)
    async def test_failed_discovery_emits_no_reveal(self, mock_reveal):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(3)):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        mock_reveal.assert_not_awaited()
