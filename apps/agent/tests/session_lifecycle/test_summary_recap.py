"""Tests for session-summary generation, recap, and reconnect instructions."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from session_data import SessionData


@pytest.mark.asyncio
async def test_rejoined_player_second_goodbye_replaces_same_session_summary():
    from db_mutations import save_session_summary

    conn = AsyncMock()
    await save_session_summary("guest", "room-session", {"summary": "first"}, conn=conn)
    await save_session_summary("guest", "room-session", {"summary": "second"}, conn=conn)
    assert conn.execute.await_count == 2
    for call in conn.execute.await_args_list:
        assert "ON CONFLICT (player_id, session_id) DO UPDATE" in call.args[0]
        assert call.args[1:3] == ("guest", "room-session")


@pytest.mark.asyncio
async def test_personal_story_moment_query_filters_player_in_database():
    from db_activity_queries import get_session_story_moments

    conn = AsyncMock()
    conn.fetch.return_value = []
    await get_session_story_moments("room-session", "guest", conn=conn)
    assert "player_id = $2" in conn.fetch.await_args.args[0]
    assert conn.fetch.await_args.args[1:] == ("room-session", "guest")


@pytest.mark.asyncio
async def test_last_member_after_host_handoff_recaps_only_their_own_earnings():
    from session_end import run_session_end

    sd = SessionData(player_id="host", location_id="hall")
    sd.party.members.append(SessionData(player_id="p2", location_id="hall").party.primary)
    sd.session_xp_earned = 500
    sd.session_items_found = ["Host sword"]
    sd.record_player_metric("p2", "xp_earned", 25)
    sd.handoff_primary("host")
    with (
        patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=None),
        patch("db_activity_queries.get_session_story_moments", new_callable=AsyncMock, return_value=[]),
        patch("session_end.publish_game_event", new_callable=AsyncMock),
        patch("session_end.db_mutations.save_session_summary", new_callable=AsyncMock) as save,
    ):
        await run_session_end(sd)
    assert save.await_args is not None
    player_id, _session_id, payload = save.await_args.args
    assert player_id == "p2"
    assert (payload["xp_earned"], payload["items_found"]) == (25, [])


class TestSessionSummary:
    """Test session_summary.py generation and fallback."""

    @pytest.mark.asyncio
    async def test_personal_summary_uses_only_that_players_metrics_and_moments(self):
        from session_summary import generate_session_summary

        sd = SessionData(player_id="host", location_id="loc1")
        sd.session_xp_earned = 100
        sd.session_items_found = ["Host sword"]
        sd.session_quests_progressed = ["host quest"]
        sd.session_locations_visited = ["host stop"]
        sd.record_player_metric("guest", "xp_earned", 25)
        sd.record_player_metric("guest", "items_found", "Guest key")
        sd.record_player_metric("guest", "quest_progress", "guest quest")
        sd.record_player_metric("guest", "locations_visited", "guest stop")
        with (
            patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=None) as llm,
            patch("db_activity_queries.get_session_story_moments", new_callable=AsyncMock, return_value=[]) as moments,
        ):
            result = await generate_session_summary(sd, None, player_id="guest")
        assert result["xp_earned"] == 25
        assert result["items_found"] == ["Guest key"]
        assert result["quest_progress"] == ["guest quest"]
        assert result["locations_visited"] == ["guest stop"]
        assert llm.await_args is not None
        assert llm.await_args.kwargs["xp_earned"] == 25
        moments.assert_awaited_once_with(sd.session_id, "guest")

    @pytest.mark.asyncio
    async def test_generates_structured_summary(self):
        from session_summary import generate_session_summary

        sd = SessionData(player_id="p1", location_id="loc1")
        sd.session_xp_earned = 100
        sd.session_items_found = ["Sword"]
        sd.session_quests_progressed = ["quest1"]
        sd.session_locations_visited = ["loc1", "loc2"]

        llm_response = {
            "summary": "You ventured into the ruins and found a sword.",
            "key_events": ["Found a sword", "Fought goblins"],
            "decisions": ["Spared the goblin chief"],
            "next_hooks": ["The ruins hold deeper secrets"],
        }

        with patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=llm_response):
            result = await generate_session_summary(sd, None, time.time() - 600)

        assert result["summary"] == "You ventured into the ruins and found a sword."
        assert result["key_events"] == ["Found a sword", "Fought goblins"]
        assert result["decisions"] == ["Spared the goblin chief"]
        assert result["next_hooks"] == ["The ruins hold deeper secrets"]
        assert result["xp_earned"] == 100
        assert result["items_found"] == ["Sword"]

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self):
        from session_summary import generate_session_summary

        sd = SessionData(player_id="p1", location_id="loc1")
        sd.record_event("Defeated a goblin")
        sd.record_event("Found a key")

        with patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=None):
            result = await generate_session_summary(sd, None, time.time() - 300)

        assert "Defeated a goblin" in result["summary"]
        assert "Found a key" in result["summary"]
        assert result["key_events"] == ["Defeated a goblin", "Found a key"]
        assert result["decisions"] == []
        assert result["next_hooks"] == []

    @pytest.mark.asyncio
    async def test_reads_transcript_file(self, tmp_path):
        from session_summary import generate_session_summary

        transcript = tmp_path / "session.log"
        transcript.write_text("Line 1\nLine 2\nLine 3\n")

        sd = SessionData(player_id="p1", location_id="loc1")

        llm_response = {
            "summary": "A brief adventure.",
            "key_events": ["Something happened"],
            "decisions": [],
            "next_hooks": [],
        }

        with patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=llm_response) as mock_llm:
            await generate_session_summary(sd, str(transcript), time.time() - 60)
            # Verify transcript content was passed to LLM
            call_kwargs = mock_llm.call_args[1]
            assert "Line 1" in call_kwargs["transcript_tail"]


class TestRecapInstruction:
    """Test _build_recap_instruction uses structured summary data."""

    def test_builds_recap_from_full_summary(self):
        from agent import _build_recap_instruction

        summary = {
            "summary": "You explored the ruins.",
            "key_events": ["Found a sword", "Fought goblins"],
            "decisions": ["Spared the chief"],
            "next_hooks": ["Deeper ruins await"],
        }
        recap = _build_recap_instruction(summary)
        assert "You explored the ruins." in recap
        assert "Found a sword" in recap
        assert "Deeper ruins await" in recap
        assert "Spared the chief" in recap

    def test_empty_summary_returns_empty(self):
        from agent import _build_recap_instruction

        assert _build_recap_instruction(None) == ""
        assert _build_recap_instruction({}) == ""

    def test_partial_summary(self):
        from agent import _build_recap_instruction

        summary = {"summary": "A brief venture."}
        recap = _build_recap_instruction(summary)
        assert "A brief venture." in recap
        assert "Key events" not in recap


class TestReconnectInstruction:
    """Test _build_reconnect_instruction includes location and companion."""

    def test_includes_location(self):
        from participant_lifecycle import _build_reconnect_instruction
        from session_data import SessionData

        sd = SessionData(player_id="p1", location_id="accord_guild_hall")
        sd.cached_location_name = "Guild Hall"
        instruction = _build_reconnect_instruction(sd)
        assert "Guild Hall" in instruction

    def test_includes_companion(self):
        from participant_lifecycle import _build_reconnect_instruction
        from session_data import CompanionState, SessionData

        sd = SessionData(player_id="p1", location_id="accord_guild_hall")
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        instruction = _build_reconnect_instruction(sd)
        assert "Kael" in instruction

    def test_includes_combat_state(self):
        from participant_lifecycle import _build_reconnect_instruction
        from session_data import CombatState, SessionData

        sd = SessionData(player_id="p1", location_id="greyvale_south_road")
        sd.combat_state = CombatState(
            combat_id="c1",
            participants=[],
            initiative_order=[],
            location_id="greyvale_south_road",
        )
        instruction = _build_reconnect_instruction(sd)
        assert "combat" in instruction.lower()

    def test_minimal_session_data(self):
        from participant_lifecycle import _build_reconnect_instruction
        from session_data import SessionData

        sd = SessionData(player_id="p1", location_id="unknown")
        instruction = _build_reconnect_instruction(sd)
        assert "reconnected" in instruction.lower()
