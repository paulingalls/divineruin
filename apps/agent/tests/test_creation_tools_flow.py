from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError

import event_types as E
from creation_classes import CLASSES
from creation_prompts import CREATION_SYSTEM_PROMPT
from creation_races import RACES
from creation_rules import calculate_ac, get_starting_equipment
from creation_tools import finalize_character, push_creation_music
from event_bus import EventBus
from hp_scaling import calculate_max_hp
from rules_engine import attribute_modifier, calculate_max_pools
from session_data import CreationState, SessionData

ATTRIBUTES = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
CATEGORY_CASES = (
    (("warrior", "guardian", "skirmisher"), (16, 13, 14, 8, 12, 10), "strength"),
    (("mage", "artificer", "seeker"), (8, 14, 13, 16, 12, 10), "intelligence"),
    (("druid", "beastcaller", "warden"), (13, 12, 14, 10, 16, 8), "wisdom"),
    (("cleric", "paladin", "oracle"), (12, 10, 14, 8, 16, 13), "wisdom"),
    (("rogue", "spy", "whisper"), (8, 16, 13, 12, 10, 14), "dexterity"),
    (("bard", "diplomat", "marshal"), (8, 14, 12, 10, 13, 16), "charisma"),
)
RACIAL_BONUSES = {
    "draethar": {"strength": 2, "constitution": 1},
    "elari": {"intelligence": 2, "wisdom": 1},
    "korath": {"constitution": 2, "strength": 1},
    "vaelti": {"dexterity": 2, "wisdom": 1},
    "human": dict.fromkeys(ATTRIBUTES, 1),
    "thessyn": {"dexterity": 1, "charisma": 1},
}
ADAPTIVE_PRIMARIES = {
    "guardian": "constitution",
    "skirmisher": "dexterity",
    "paladin": "strength",
    "spy": "charisma",
    "whisper": "charisma",
}
# Numeric anchors check the shared formula oracle, including medium armor's cap.
HUMAN_ANCHORS = {
    "warrior": (14, 15, 11, None),
    "mage": (10, 12, None, 12),
    "druid": (12, 13, 6, 12),
    "cleric": (12, 14, 6, 12),
    "rogue": (10, 14, 12, None),
    "bard": (9, 13, 6, 8),
    "guardian": (14, 16, 11, None),
}
FINALIZATION_CASES = [(cls, scores, primary) for classes, scores, primary in CATEGORY_CASES for cls in classes]
assert len(FINALIZATION_CASES) == 18 and {case[0] for case in FINALIZATION_CASES} == set(CLASSES)
assert len(RACIAL_BONUSES) == 6 and set(RACIAL_BONUSES) == set(RACES)


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
    async def test_not_in_creation_mode(self):
        ctx = _make_context()
        ctx.userdata.creation_state = None
        with pytest.raises(ToolError):
            await _finalize(ctx)

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_finalize_initializes_patron_clock(self, mock_create_player, mock_get_payload):
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
        await _finalize(ctx)
        stored = mock_create_player.call_args.args[2]
        served = datetime.fromisoformat(stored["divine_favor"]["last_served_at"])
        assert served.tzinfo is not None
        assert abs((datetime.now(UTC) - served).total_seconds()) < 60

    @pytest.mark.parametrize("class_id,scores,primary", FINALIZATION_CASES, ids=[c[0] for c in FINALIZATION_CASES])
    @pytest.mark.parametrize("race_id", RACIAL_BONUSES)
    @patch("creation_tools.character_spells.record_learned", new_callable=AsyncMock)
    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_finalize_starting_attributes_and_chassis(
        self,
        mock_create_player,
        mock_get_payload,
        mock_record_learned,
        class_id: str,
        scores,
        primary: str,
        race_id: str,
    ):
        mock_get_payload.return_value = {
            "character": {},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {},
        }
        expected = dict(zip(ATTRIBUTES, scores, strict=True))
        bonuses = RACIAL_BONUSES[race_id].copy()
        if race_id == "thessyn":
            adaptive = ADAPTIVE_PRIMARIES.get(class_id, primary)
            bonuses[adaptive] = bonuses.get(adaptive, 0) + 1
        expected = {key: value + bonuses.get(key, 0) for key, value in expected.items()}
        cs = CreationState(race=race_id, class_choice=class_id, deity="none", name="Aric", backstory="Test.")
        await _finalize(_make_context(cs))
        data = mock_create_player.call_args.args[2]
        assert data["attributes"] == expected
        assert data["level"] == 1
        hp = calculate_max_hp(class_id, 1, attribute_modifier(expected["constitution"]))
        ac = calculate_ac(get_starting_equipment(class_id), expected["dexterity"])
        maxima = calculate_max_pools(class_id, 1, {key: attribute_modifier(value) for key, value in expected.items()})
        assert data["hp"] == {"current": hp, "max": hp}
        assert data["ac"] == ac
        for pool in ("stamina", "focus"):
            maximum = getattr(maxima, pool)
            if maximum is None:
                assert pool not in data
            else:
                assert data[pool] == {"current": maximum, "max": maximum}
        if race_id == "human" and class_id in HUMAN_ANCHORS:
            assert (hp, ac, maxima.stamina, maxima.focus) == HUMAN_ANCHORS[class_id]
        if (race_id, class_id) == ("vaelti", "artificer"):
            assert (hp, ac, maxima.stamina, maxima.focus) == (9, 15, None, 12)

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
        assert cs.deity is None


class TestPushCreationMusic:
    async def test_emits_set_music_state_on_event_bus(self):
        bus = EventBus()

        await push_creation_music("wonder", None, bus)

        event = await bus.get(timeout=1.0)
        assert event is not None
        assert event.event_type == E.SET_MUSIC_STATE
        assert event.payload == {"music_state": "wonder"}


class TestCreationPromptDropsMusicTools:
    def test_no_play_sound_or_set_music_state_bullets(self):
        assert "play_sound" not in CREATION_SYSTEM_PROMPT
        assert "set_music_state" not in CREATION_SYSTEM_PROMPT
