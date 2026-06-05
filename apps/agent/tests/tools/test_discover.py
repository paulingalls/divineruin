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
from tools._helpers import _make_context

LOCATION_WITH_HIDDEN = {
    "id": "test_location",
    "name": "Test Location",
    "description": "A room.",
    "atmosphere": "plain",
    "key_features": [],
    "hidden_elements": [
        {
            "id": "secret_door",
            "discover_skill": "perception",
            "dc": 12,
            "description": "A hidden passage behind the bookshelf",
        }
    ],
    "exits": {},
    "tags": [],
    "conditions": {},
}

LOCATION_TWO_SECRETS = {
    **LOCATION_WITH_HIDDEN,
    "hidden_elements": [
        {"id": "hard_secret", "discover_skill": "perception", "dc": 15, "description": "A hard find"},
        {"id": "easy_secret", "discover_skill": "perception", "dc": 10, "description": "An easy find"},
    ],
}

# M6: an element bound to a visible target via attaches_to surfaces ONLY when that
# target is examined; an unannotated element is the room-wide skill-match fallback.
LOCATION_ATTACHED = {
    **LOCATION_WITH_HIDDEN,
    "hidden_elements": [
        {
            "id": "door_seal",
            "discover_skill": "arcana",
            "dc": 10,
            "description": "A ward-seal on the inner door",
            "attaches_to": "inner_door",
        }
    ],
}

LOCATION_MIXED = {
    **LOCATION_WITH_HIDDEN,
    "hidden_elements": [
        {
            "id": "door_seal",
            "discover_skill": "perception",
            "dc": 10,
            "description": "A ward-seal on the inner door",
            "attaches_to": "inner_door",
        },
        {
            "id": "loose_brick",
            "discover_skill": "perception",
            "dc": 10,
            "description": "A loose brick in the wall",
        },
    ],
}

# M6 (story-004 follow-up): attaches_to is a short token ("arch") but the warm layer
# advertises the key_feature as prose ("a cracked stone arch to the north"). Matching is
# asymmetric whole-word containment — attaches_to must appear as a whole word IN the
# examined target, so the player examines via the advertised prose; mid-word substrings
# (e.g. "arch" in "search") must NOT match.
LOCATION_ARCH = {
    **LOCATION_WITH_HIDDEN,
    "hidden_elements": [
        {
            "id": "arch_seal",
            "discover_skill": "perception",
            "dc": 10,
            "description": "A seal behind the arch",
            "attaches_to": "arch",
        }
    ],
}

DISCOVER_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 16,
        "charisma": 8,
    },
    "proficiencies": ["perception", "athletics"],
    "hp": {"current": 25, "max": 25},
    "ac": 14,
    "equipment": {},
}


def _make_discover_mocks(location=LOCATION_WITH_HIDDEN, player=DISCOVER_PLAYER):
    mock_content = MagicMock()
    mock_content.get_location = AsyncMock(return_value=location)
    mock_queries = MagicMock()
    mock_queries.get_player = AsyncMock(return_value=player)
    mock_mutations = MagicMock()
    mock_mutations.set_player_flag = AsyncMock()
    return mock_content, mock_queries, mock_mutations


def _roll(total):
    from dice import DiceResult

    return DiceResult(notation="d20", rolls=[total], dropped=[], total=total)


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
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_successful_discovery_emits_hidden_revealed(self, mock_event):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        revealed = [c for c in mock_event.call_args_list if c[0][1] == E.HIDDEN_REVEALED]
        assert len(revealed) == 1
        assert revealed[0][0][2]["element_id"] == "secret_door"

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_failed_discovery_emits_no_reveal(self, mock_event):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(3)):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        revealed = [c for c in mock_event.call_args_list if c[0][1] == E.HIDDEN_REVEALED]
        assert revealed == []

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
