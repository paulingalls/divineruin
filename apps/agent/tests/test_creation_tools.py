"""Tests for character creation tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from creation_data import CLASSES, DEITIES, RACES
from creation_tools import finalize_character, push_creation_cards, set_creation_choice
from session_data import CreationState, SessionData


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


class TestPushCreationCards:
    async def test_race_returns_six_cards(self):
        ctx = _make_context()
        result = json.loads(await push_creation_cards._func(ctx, category="race"))
        assert result["count"] == 6
        assert result["category"] == "race"
        ids = {o["id"] for o in result["options"]}
        assert ids == set(RACES.keys())

    async def test_class_returns_all_cards(self):
        ctx = _make_context()
        result = json.loads(await push_creation_cards._func(ctx, category="class"))
        assert result["count"] == len(CLASSES)
        assert result["category"] == "class"
        ids = {o["id"] for o in result["options"]}
        assert ids == set(CLASSES.keys())

    async def test_deity_returns_all_plus_none(self):
        ctx = _make_context()
        result = json.loads(await push_creation_cards._func(ctx, category="deity"))
        assert result["count"] == len(DEITIES)
        ids = {o["id"] for o in result["options"]}
        assert "none" in ids
        assert "kaelen" in ids

    async def test_invalid_category_returns_error(self):
        ctx = _make_context()
        result = json.loads(await push_creation_cards._func(ctx, category="invalid"))
        assert "error" in result

    async def test_race_cards_have_descriptions(self):
        ctx = _make_context()
        result = json.loads(await push_creation_cards._func(ctx, category="race"))
        for option in result["options"]:
            assert "description" in option
            assert len(option["description"]) > 10

    async def test_push_cards_does_not_advance_phase(self):
        """Phase should only advance via set_creation_choice, not push_creation_cards."""
        ctx = _make_context(CreationState(phase="prologue"))
        await push_creation_cards._func(ctx, category="race")
        assert ctx.userdata.creation_state.phase == "prologue"


class TestSetCreationChoice:
    async def test_set_race_valid(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="race", value="draethar"))
        assert result["confirmed"] == "race"
        assert result["value"] == "draethar"
        assert ctx.userdata.creation_state.race == "draethar"

    async def test_set_race_invalid(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="race", value="invalid_race"))
        assert "error" in result
        assert ctx.userdata.creation_state.race is None

    async def test_set_class_valid(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="class", value="warrior"))
        assert result["confirmed"] == "class"
        assert ctx.userdata.creation_state.class_choice == "warrior"

    async def test_set_class_invalid(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="class", value="invalid_class"))
        assert "error" in result

    async def test_set_deity_valid(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="deity", value="kaelen"))
        assert result["confirmed"] == "deity"
        assert ctx.userdata.creation_state.deity == "kaelen"

    async def test_set_deity_none(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="deity", value="none"))
        assert result["confirmed"] == "deity"
        assert ctx.userdata.creation_state.deity == "none"

    async def test_set_deity_invalid(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="deity", value="fake_god"))
        assert "error" in result

    async def test_set_name(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="name", value="Aric"))
        assert result["confirmed"] == "name"
        assert ctx.userdata.creation_state.name == "Aric"

    async def test_set_name_strips_whitespace(self):
        ctx = _make_context()
        await set_creation_choice._func(ctx, category="name", value="  Aric  ")
        assert ctx.userdata.creation_state.name == "Aric"

    async def test_set_empty_name_rejected(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="name", value=""))
        assert "error" in result

    async def test_set_backstory(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="backstory", value="Born in the Accord."))
        assert result["confirmed"] == "backstory"
        assert ctx.userdata.creation_state.backstory == "Born in the Accord."

    async def test_invalid_category(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="invalid", value="test"))
        assert "error" in result

    async def test_not_in_creation_mode(self):
        ctx = _make_context()
        ctx.userdata.creation_state = None
        result = json.loads(await set_creation_choice._func(ctx, category="race", value="human"))
        assert "error" in result

    async def test_phase_advances_on_race(self):
        ctx = _make_context(CreationState(phase="awakening"))
        await set_creation_choice._func(ctx, category="race", value="human")
        assert ctx.userdata.creation_state.phase == "calling"

    async def test_phase_advances_on_class(self):
        ctx = _make_context(CreationState(phase="calling"))
        await set_creation_choice._func(ctx, category="class", value="warrior")
        assert ctx.userdata.creation_state.phase == "devotion"

    async def test_phase_advances_on_deity(self):
        ctx = _make_context(CreationState(phase="devotion"))
        await set_creation_choice._func(ctx, category="deity", value="kaelen")
        assert ctx.userdata.creation_state.phase == "identity"

    async def test_progress_tracking(self):
        ctx = _make_context()
        await set_creation_choice._func(ctx, category="race", value="human")
        await set_creation_choice._func(ctx, category="class", value="warrior")
        result = json.loads(await set_creation_choice._func(ctx, category="deity", value="kaelen"))
        progress = result["progress"]
        assert progress["race"] == "human"
        assert progress["class"] == "warrior"
        assert progress["deity"] == "kaelen"
        assert progress["name"] is None

    async def test_guidance_shows_remaining(self):
        ctx = _make_context()
        result = json.loads(await set_creation_choice._func(ctx, category="race", value="human"))
        assert "class" in result["guidance"]


class TestFinalizeCharacter:
    async def test_missing_race_returns_error(self):
        ctx = _make_context(CreationState(class_choice="warrior", name="Aric"))
        result = json.loads(await finalize_character._func(ctx))
        assert "error" in result
        assert "race" in result["error"]

    async def test_missing_class_returns_error(self):
        ctx = _make_context(CreationState(race="human", name="Aric"))
        result = json.loads(await finalize_character._func(ctx))
        assert "error" in result
        assert "class" in result["error"]

    async def test_missing_name_returns_error(self):
        ctx = _make_context(CreationState(race="human", class_choice="warrior"))
        result = json.loads(await finalize_character._func(ctx))
        assert "error" in result
        assert "name" in result["error"]

    async def test_not_in_creation_mode(self):
        ctx = _make_context()
        ctx.userdata.creation_state = None
        result = json.loads(await finalize_character._func(ctx))
        assert "error" in result

    @patch("creation_tools.db")
    async def test_successful_finalize(self, mock_db):
        mock_db.create_player = AsyncMock()
        mock_db.get_session_init_payload = AsyncMock(
            return_value={
                "character": {"name": "Aric"},
                "location": None,
                "quests": [],
                "inventory": [],
                "map_progress": [],
                "world_state": {"time": "evening"},
            }
        )

        cs = CreationState(
            phase="identity",
            race="human",
            class_choice="warrior",
            deity="kaelen",
            name="Aric",
            backstory="A wandering sellsword.",
        )
        ctx = _make_context(cs)
        result = json.loads(await finalize_character._func(ctx))

        assert "character" in result
        assert result["character"]["name"] == "Aric"
        assert result["character"]["race"] == "Human"
        assert result["character"]["class"] == "Warrior"
        assert cs.phase == "complete"
        mock_db.create_player.assert_awaited_once()

    @patch("creation_tools.db")
    async def test_finalize_with_deferred_deity(self, mock_db):
        mock_db.create_player = AsyncMock()
        mock_db.get_session_init_payload = AsyncMock(
            return_value={
                "character": {"name": "Aric"},
                "location": None,
                "quests": [],
                "inventory": [],
                "map_progress": [],
                "world_state": {"time": "evening"},
            }
        )

        cs = CreationState(
            phase="identity",
            race="elari",
            class_choice="mage",
            deity=None,
            name="Aric",
            backstory="Seeker of truth.",
        )
        ctx = _make_context(cs)
        result = json.loads(await finalize_character._func(ctx))

        assert "character" in result
        assert cs.phase == "complete"

    @patch("creation_tools.db")
    async def test_finalize_calls_create_player(self, mock_db):
        mock_db.create_player = AsyncMock()
        mock_db.get_session_init_payload = AsyncMock(
            return_value={
                "character": {},
                "location": None,
                "quests": [],
                "inventory": [],
                "map_progress": [],
                "world_state": {},
            }
        )

        cs = CreationState(
            race="draethar",
            class_choice="guardian",
            deity="valdris",
            name="Thane",
            backstory="Protector of the weak.",
        )
        ctx = _make_context(cs)
        await finalize_character._func(ctx)

        mock_db.create_player.assert_awaited_once()
        call_args = mock_db.create_player.call_args
        player_id = call_args[0][0]
        data = call_args[0][2]
        assert player_id == "test_player"
        assert data["name"] == "Thane"
        assert data["race"] == "draethar"
        assert data["class"] == "guardian"
        assert data["deity"] == "valdris"

    @patch("creation_tools.db")
    async def test_finalize_updates_session_location(self, mock_db):
        mock_db.create_player = AsyncMock()
        mock_db.get_session_init_payload = AsyncMock(
            return_value={
                "character": {},
                "location": None,
                "quests": [],
                "inventory": [],
                "map_progress": [],
                "world_state": {},
            }
        )

        cs = CreationState(
            race="human",
            class_choice="warrior",
            deity=None,
            name="Aric",
            backstory="Test.",
        )
        ctx = _make_context(cs)
        await finalize_character._func(ctx)

        assert ctx.userdata.location_id != ""

    @patch("creation_tools.db")
    async def test_finalize_db_error(self, mock_db):
        mock_db.create_player = AsyncMock(side_effect=Exception("DB down"))

        cs = CreationState(
            race="human",
            class_choice="warrior",
            name="Aric",
        )
        ctx = _make_context(cs)
        result = json.loads(await finalize_character._func(ctx))
        assert "error" in result


class TestFullCreationFlow:
    """End-to-end flow through the creation tools."""

    @patch("creation_tools.db")
    async def test_complete_flow(self, mock_db):
        mock_db.create_player = AsyncMock()
        mock_db.get_session_init_payload = AsyncMock(
            return_value={
                "character": {"name": "Aric"},
                "location": None,
                "quests": [],
                "inventory": [],
                "map_progress": [],
                "world_state": {"time": "evening"},
            }
        )

        cs = CreationState()
        ctx = _make_context(cs)

        # Push race cards
        result = json.loads(await push_creation_cards._func(ctx, category="race"))
        assert result["count"] == 6

        # Choose race
        result = json.loads(await set_creation_choice._func(ctx, category="race", value="elari"))
        assert result["confirmed"] == "race"

        # Push class cards
        result = json.loads(await push_creation_cards._func(ctx, category="class"))
        assert result["count"] == len(CLASSES)

        # Choose class
        result = json.loads(await set_creation_choice._func(ctx, category="class", value="mage"))
        assert result["confirmed"] == "class"

        # Push deity cards
        result = json.loads(await push_creation_cards._func(ctx, category="deity"))
        assert result["count"] == len(DEITIES)

        # Choose deity
        result = json.loads(await set_creation_choice._func(ctx, category="deity", value="veythar"))
        assert result["confirmed"] == "deity"

        # Set name
        result = json.loads(await set_creation_choice._func(ctx, category="name", value="Seraphina"))
        assert cs.name == "Seraphina"

        # Set backstory
        result = json.loads(
            await set_creation_choice._func(ctx, category="backstory", value="A scholar of the diaspora.")
        )
        assert cs.backstory == "A scholar of the diaspora."

        # Finalize
        result = json.loads(await finalize_character._func(ctx))
        assert "character" in result
        assert cs.phase == "complete"
        assert not ctx.userdata.in_creation

        mock_db.create_player.assert_awaited_once()
        data = mock_db.create_player.call_args[0][2]
        assert data["name"] == "Seraphina"
        assert data["race"] == "elari"
        assert data["class"] == "mage"
        assert data["deity"] == "veythar"

    @patch("creation_tools.db")
    async def test_each_race_with_representative_class(self, mock_db):
        mock_db.create_player = AsyncMock()
        mock_db.get_session_init_payload = AsyncMock(
            return_value={
                "character": {},
                "location": None,
                "quests": [],
                "inventory": [],
                "map_progress": [],
                "world_state": {},
            }
        )

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
            await set_creation_choice._func(ctx, category="race", value=race_id)
            await set_creation_choice._func(ctx, category="class", value=class_id)
            await set_creation_choice._func(ctx, category="deity", value="none")
            await set_creation_choice._func(ctx, category="name", value="TestChar")
            await set_creation_choice._func(ctx, category="backstory", value="Test.")
            result = json.loads(await finalize_character._func(ctx))
            assert "character" in result, f"Failed for {race_id}/{class_id}: {result}"
            assert cs.phase == "complete"
