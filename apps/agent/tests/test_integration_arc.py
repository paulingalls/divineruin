"""Integration test for the full Greyvale quest arc progression (WU4)."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from session_data import SessionData
from tools import (
    LOCATION_CORRUPTION,
    _apply_world_effects,
    _check_exit_requirement,
)

# --- Helpers ---

_mock_conn = MagicMock(name="mock_txn_conn")


@asynccontextmanager
async def _mock_transaction():
    yield _mock_conn


def _make_session(**kwargs):
    defaults = dict(player_id="player_1", location_id="accord_market_square", room=None)
    defaults.update(kwargs)
    return SessionData(**defaults)


# Load the actual quest data
def _load_greyvale_quest():
    import json as j
    from pathlib import Path

    content = Path(__file__).parent.parent.parent.parent / "content" / "quests.json"
    quests = j.loads(content.read_text())
    return next(q for q in quests if q["id"] == "greyvale_anomaly")


class TestQuestArcProgression:
    """Test the full 5-stage quest progression with world effects."""

    @pytest.mark.asyncio
    async def test_stage_1_effects(self):
        """Stage 0→1: torin_disposition +1."""
        quest = _load_greyvale_quest()
        stage_0 = quest["stages"][0]
        effects = stage_0["on_complete"].get("world_effects", [])
        assert effects == ["torin_disposition +1"]

        session = _make_session()
        pending: list[tuple[str, dict]] = []

        with (
            patch("tools.db.get_npc_disposition", new_callable=AsyncMock, return_value="neutral"),
            patch("tools.db.set_npc_disposition", new_callable=AsyncMock) as mock_set,
            patch("tools.db.get_npc", new_callable=AsyncMock, return_value={"default_disposition": "neutral"}),
        ):
            await _apply_world_effects(effects, session, pending)

        mock_set.assert_called_once()
        disp_events = [e for e in pending if e[0] == "disposition_changed"]
        assert len(disp_events) == 1
        assert disp_events[0][1]["npc_id"] == "guildmaster_torin"

    @pytest.mark.asyncio
    async def test_stage_2_no_effects(self):
        """Stage 1→2: no world effects."""
        quest = _load_greyvale_quest()
        stage_1 = quest["stages"][1]
        effects = stage_1["on_complete"].get("world_effects", [])
        assert effects == []

    @pytest.mark.asyncio
    async def test_stage_3_effects(self):
        """Stage 2→3: millhaven_morale +2, yanna_disposition +2."""
        quest = _load_greyvale_quest()
        stage_2 = quest["stages"][2]
        effects = stage_2["on_complete"].get("world_effects", [])
        assert "millhaven_morale +2" in effects
        assert "yanna_disposition +2" in effects

        session = _make_session()
        pending: list[tuple[str, dict]] = []

        with (
            patch("tools.db.get_npc_disposition", new_callable=AsyncMock, return_value="wary"),
            patch("tools.db.set_npc_disposition", new_callable=AsyncMock) as mock_set,
            patch("tools.db.get_npc", new_callable=AsyncMock, return_value={"default_disposition": "wary"}),
        ):
            await _apply_world_effects(effects, session, pending)

        # yanna disposition should be set
        mock_set.assert_called_once()
        # morale event should be logged
        morale_events = [e for e in pending if e[0] == "world_event" and "morale" in e[1].get("event_id", "")]
        assert len(morale_events) == 1

    @pytest.mark.asyncio
    async def test_stage_4_effects(self):
        """Stage 3→4: greyvale_corruption +1, event:ruins_discovery_ripple."""
        quest = _load_greyvale_quest()
        stage_3 = quest["stages"][3]
        effects = stage_3["on_complete"].get("world_effects", [])
        assert "greyvale_corruption +1" in effects
        assert "event:ruins_discovery_ripple" in effects

        session = _make_session()
        session.corruption_level = 2
        pending: list[tuple[str, dict]] = []

        await _apply_world_effects(effects, session, pending)

        assert session.corruption_level == 3
        corruption_events = [e for e in pending if e[0] == "hollow_corruption_changed"]
        assert len(corruption_events) == 1
        world_events = [e for e in pending if e[0] == "world_event"]
        assert any(e[1]["event_id"] == "ruins_discovery_ripple" for e in world_events)

    @pytest.mark.asyncio
    async def test_stage_5_effects(self):
        """Stage 4→5: emris_disposition +4, event:faction_interest_triggered, event:god_whisper:player_patron."""
        quest = _load_greyvale_quest()
        stage_4 = quest["stages"][4]
        effects = stage_4["on_complete"].get("world_effects", [])
        assert "emris_disposition +4" in effects
        assert "event:faction_interest_triggered" in effects
        assert "event:god_whisper:player_patron" in effects

        session = _make_session()
        pending: list[tuple[str, dict]] = []

        with (
            patch("tools.db.get_npc_disposition", new_callable=AsyncMock, return_value="cautious"),
            patch("tools.db.set_npc_disposition", new_callable=AsyncMock) as mock_set,
            patch("tools.db.get_npc", new_callable=AsyncMock, return_value={"default_disposition": "cautious"}),
        ):
            await _apply_world_effects(effects, session, pending)

        mock_set.assert_called_once()
        world_events = [e for e in pending if e[0] == "world_event"]
        event_ids = {e[1]["event_id"] for e in world_events}
        assert "faction_interest_triggered" in event_ids
        assert "god_whisper:player_patron" in event_ids


class TestNavigationPath:
    """Verify the expected session 1-4 navigation path is valid."""

    def test_session_path_locations_exist(self):
        """All locations in the play path should exist in content."""
        from pathlib import Path

        locations = json.loads((Path(__file__).parent.parent.parent.parent / "content" / "locations.json").read_text())
        location_ids = {loc["id"] for loc in locations}

        path = [
            "accord_market_square",
            "accord_guild_hall",
            "greyvale_south_road",
            "millhaven",
            "greyvale_wilderness_north",
            "hollow_incursion_site",
            "greyvale_ruins_exterior",
            "greyvale_ruins_entrance",
        ]
        for loc_id in path:
            assert loc_id in location_ids, f"Path location '{loc_id}' not found in content"

    def test_corruption_levels_on_path(self):
        """Verify corruption escalation along the play path."""
        assert LOCATION_CORRUPTION.get("accord_market_square", 0) == 0
        assert LOCATION_CORRUPTION.get("millhaven", 0) == 0
        assert LOCATION_CORRUPTION.get("greyvale_wilderness_north", 0) == 1
        assert LOCATION_CORRUPTION.get("hollow_incursion_site", 0) == 2
        assert LOCATION_CORRUPTION.get("greyvale_ruins_entrance", 0) == 2
        assert LOCATION_CORRUPTION.get("greyvale_ruins_inner", 0) == 3


class TestExitRequirementsOnPath:
    @pytest.mark.asyncio
    @patch("tools.db.get_player_flag", new_callable=AsyncMock)
    async def test_ruins_inner_blocked_without_discovery(self, mock_flag):
        mock_flag.return_value = False
        result = await _check_exit_requirement("veythar_seal_mark.discovered", "player_1")
        assert result is False

    @pytest.mark.asyncio
    @patch("tools.db.get_player_flag", new_callable=AsyncMock)
    async def test_ruins_inner_open_with_discovery(self, mock_flag):
        mock_flag.return_value = True
        result = await _check_exit_requirement("veythar_seal_mark.discovered", "player_1")
        assert result is True
