"""Tests for the character creation flow tools.

finalize_character — stat generation, persistence and phase completion — plus the
end-to-end flow through every creation tool. Split from the choice-collection tests
(test_creation_tools_choices.py) and the asset-id / image-url tests
(test_creation_tools_assets.py) to stay under the 500-line cap.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _creation_grant_fixtures import stub_creation_companion_grant  # noqa: F401  (autouse)
from livekit.agents.llm import ToolError

import event_types as E
from creation_classes import CLASSES
from creation_deities import DEITIES
from creation_prompts import CREATION_SYSTEM_PROMPT
from creation_tools import finalize_character, push_creation_cards, push_creation_music, set_creation_choice
from event_bus import EventBus
from hp_scaling import calculate_max_hp
from rules_engine import attribute_modifier
from session_data import CreationState, SessionData

# _func bypasses SDK Literal validation — use Any-typed refs so Pyright accepts
# values outside the Literal (e.g. "race", "invalid") that the underlying code handles.
_push_cards: Any = push_creation_cards._func
_set_choice: Any = set_creation_choice._func
_finalize: Any = finalize_character._func


def _make_context(creation_state: CreationState | None = None) -> MagicMock:
    """Build a mock RunContext with SessionData containing a creation state."""
    sd = SessionData(
        player_id="test_player",
        location_id="",
        room=None,
        creation_state=creation_state or CreationState(),
    )
    ctx = MagicMock()
    ctx.userdata = sd
    return ctx


class TestFinalizeCharacter:
    async def test_missing_race_returns_error(self):
        ctx = _make_context(CreationState(class_choice="warrior", name="Aric"))
        with pytest.raises(ToolError, match="race"):
            await _finalize(ctx)

    async def test_missing_class_returns_error(self):
        ctx = _make_context(CreationState(race="human", name="Aric"))
        with pytest.raises(ToolError, match="class"):
            await _finalize(ctx)

    async def test_missing_name_returns_error(self):
        ctx = _make_context(CreationState(race="human", class_choice="warrior"))
        with pytest.raises(ToolError, match="name"):
            await _finalize(ctx)

    async def test_not_in_creation_mode(self):
        ctx = _make_context()
        ctx.userdata.creation_state = None
        with pytest.raises(ToolError):
            await _finalize(ctx)

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_successful_finalize(self, mock_create_player, mock_get_payload):
        mock_get_payload.return_value = {
            "character": {"name": "Aric"},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {"time": "evening"},
        }

        cs = CreationState(
            phase="identity",
            race="human",
            class_choice="warrior",
            deity="kaelen",
            name="Aric",
            backstory="A wandering sellsword.",
        )
        ctx = _make_context(cs)
        agent, json_str = await _finalize(ctx)
        result = json.loads(json_str)

        from onboarding_agent import OnboardingAgent

        assert isinstance(agent, OnboardingAgent)
        assert "character" in result
        assert result["character"]["name"] == "Aric"
        assert result["character"]["race"] == "Human"
        assert result["character"]["class"] == "Warrior"
        assert cs.phase == "complete"
        assert ctx.userdata.onboarding_beat == 1
        mock_create_player.assert_awaited_once()

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_finalize_with_deferred_deity(self, mock_create_player, mock_get_payload):
        mock_get_payload.return_value = {
            "character": {"name": "Aric"},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {"time": "evening"},
        }

        cs = CreationState(
            phase="identity",
            race="elari",
            class_choice="mage",
            deity=None,
            name="Aric",
            backstory="Seeker of truth.",
        )
        ctx = _make_context(cs)
        agent, json_str = await _finalize(ctx)
        result = json.loads(json_str)

        from onboarding_agent import OnboardingAgent

        assert isinstance(agent, OnboardingAgent)
        assert "character" in result
        assert cs.phase == "complete"

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_finalize_calls_create_player(self, mock_create_player, mock_get_payload):
        mock_get_payload.return_value = {
            "character": {},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {},
        }

        cs = CreationState(
            race="draethar",
            class_choice="guardian",
            deity="valdris",
            name="Thane",
            backstory="Protector of the weak.",
        )
        ctx = _make_context(cs)
        _agent, _json_str = await _finalize(ctx)

        mock_create_player.assert_awaited_once()
        call_args = mock_create_player.call_args
        player_id = call_args[0][0]
        data = call_args[0][2]
        assert player_id == "test_player"
        assert data["name"] == "Thane"
        assert data["race"] == "draethar"
        assert data["class"] == "guardian"
        assert data["deity"] == "valdris"

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_finalize_starting_hp_from_chassis(self, mock_create_player, mock_get_payload):
        # story-004: a finalized character's starting HP derives end-to-end from
        # the chassis (hp_base), not the legacy ClassData.hit_die. Warrior diverges
        # (hp_base 12 vs the old hit_die 10), so this would fail under the old path.
        mock_get_payload.return_value = {
            "character": {},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {},
        }

        cs = CreationState(
            race="human",
            class_choice="warrior",
            deity=None,
            name="Aric",
            backstory="Test.",
        )
        ctx = _make_context(cs)
        await _finalize(ctx)

        data = mock_create_player.call_args[0][2]
        con_mod = attribute_modifier(data["attributes"]["constitution"])
        expected = calculate_max_hp("warrior", 1, con_mod)
        assert data["hp"]["current"] == expected
        assert data["hp"]["max"] == expected

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_finalize_updates_session_location(self, mock_create_player, mock_get_payload):
        mock_get_payload.return_value = {
            "character": {},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {},
        }

        cs = CreationState(
            race="human",
            class_choice="warrior",
            deity=None,
            name="Aric",
            backstory="Test.",
        )
        ctx = _make_context(cs)
        _agent, _json_str = await _finalize(ctx)

        assert ctx.userdata.location_id != ""

    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock, side_effect=Exception("DB down"))
    async def test_finalize_db_error(self, mock_create_player):
        cs = CreationState(
            race="human",
            class_choice="warrior",
            name="Aric",
        )
        ctx = _make_context(cs)
        with pytest.raises(ToolError):
            await _finalize(ctx)


class TestPushCreationMusic:
    """push_creation_music emits the mood as a deterministic Resolve, not an LLM tool."""

    async def test_emits_set_music_state_on_event_bus(self):
        bus = EventBus()

        await push_creation_music("wonder", None, bus)

        event = await bus.get(timeout=1.0)
        assert event is not None
        assert event.event_type == E.SET_MUSIC_STATE
        assert event.payload == {"music_state": "wonder"}


class TestCreationPromptDropsMusicTools:
    """The creation prompt no longer instructs the LLM to call audio tools (M27)."""

    def test_no_play_sound_or_set_music_state_bullets(self):
        assert "play_sound" not in CREATION_SYSTEM_PROMPT
        assert "set_music_state" not in CREATION_SYSTEM_PROMPT


class TestFullCreationFlow:
    """End-to-end flow through the creation tools."""

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_complete_flow(self, mock_create_player, mock_get_payload):
        mock_get_payload.return_value = {
            "character": {"name": "Aric"},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {"time": "evening"},
        }

        cs = CreationState()
        ctx = _make_context(cs)

        # Push race cards
        result = json.loads(await _push_cards(ctx, category="race"))
        assert result["count"] == 6

        # Choose race
        result = json.loads(await _set_choice(ctx, category="race", value="elari"))
        assert result["confirmed"] == "race"

        # Push class cards
        result = json.loads(await _push_cards(ctx, category="class"))
        assert result["count"] == len(CLASSES)

        # Choose class
        result = json.loads(await _set_choice(ctx, category="class", value="mage"))
        assert result["confirmed"] == "class"

        # Push deity cards
        result = json.loads(await _push_cards(ctx, category="deity"))
        assert result["count"] == len(DEITIES)

        # Choose deity
        result = json.loads(await _set_choice(ctx, category="deity", value="veythar"))
        assert result["confirmed"] == "deity"

        # Set name
        result = json.loads(await _set_choice(ctx, category="name", value="Seraphina"))
        assert cs.name == "Seraphina"

        # Set backstory
        result = json.loads(await _set_choice(ctx, category="backstory", value="A scholar of the diaspora."))
        assert cs.backstory == "A scholar of the diaspora."

        # Finalize
        agent, json_str = await _finalize(ctx)
        result = json.loads(json_str)
        from onboarding_agent import OnboardingAgent

        assert isinstance(agent, OnboardingAgent)
        assert "character" in result
        assert cs.phase == "complete"
        assert not ctx.userdata.in_creation
        assert ctx.userdata.onboarding_beat == 1

        mock_create_player.assert_awaited_once()
        data = mock_create_player.call_args[0][2]
        assert data["name"] == "Seraphina"
        assert data["race"] == "elari"
        assert data["class"] == "mage"
        assert data["deity"] == "veythar"

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_each_race_with_representative_class(self, mock_create_player, mock_get_payload):
        mock_get_payload.return_value = {
            "character": {},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {},
        }

        combos = [
            ("draethar", "warrior"),
            ("elari", "mage"),
            ("korath", "guardian"),
            ("vaelti", "rogue"),
            ("thessyn", "bard"),
            ("human", "diplomat"),
        ]

        for race_id, class_id in combos:
            cs = CreationState()
            ctx = _make_context(cs)
            await _set_choice(ctx, category="race", value=race_id)
            await _set_choice(ctx, category="class", value=class_id)
            await _set_choice(ctx, category="deity", value="none")
            await _set_choice(ctx, category="name", value="TestChar")
            await _set_choice(ctx, category="backstory", value="Test.")
            _agent, json_str = await _finalize(ctx)
            result = json.loads(json_str)
            assert "character" in result, f"Failed for {race_id}/{class_id}: {result}"
            assert cs.phase == "complete"
