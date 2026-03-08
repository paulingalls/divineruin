"""Tests for Milestone 8.3 — Session lifecycle and persistence."""

import json
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from session_data import SessionData

# --- Shared test helpers ---

_mock_conn = MagicMock(name="mock_txn_conn")


@asynccontextmanager
async def _mock_transaction():
    yield _mock_conn


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx


def _make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "xp": 0,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "constitution"],
    "equipment": {
        "main_hand": {
            "name": "Longsword",
            "damage": "1d8",
            "damage_type": "slashing",
            "properties": [],
        }
    },
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}

SAMPLE_ITEM = {
    "id": "health_potion",
    "name": "Health Potion",
    "type": "consumable",
    "description": "A glowing red vial.",
    "rarity": "common",
}

SAMPLE_LOCATION = {
    "id": "accord_guild_hall",
    "name": "Guild Hall",
    "description": "Heavy oak doors open onto a hall.",
    "atmosphere": "busy, purposeful",
    "key_features": ["the main counter"],
    "hidden_elements": [],
    "exits": {
        "south": {"destination": "accord_market_square"},
    },
    "tags": ["guild"],
    "conditions": {},
}

SAMPLE_DESTINATION = {
    "id": "accord_market_square",
    "name": "Market Square",
    "description": "A bustling open-air market.",
    "atmosphere": "noisy, chaotic",
    "ambient_sounds": "market_bustle",
    "key_features": ["merchant stalls"],
    "hidden_elements": [],
    "exits": {"north": {"destination": "accord_guild_hall"}},
    "tags": ["market"],
    "conditions": {},
}

SAMPLE_QUEST = {
    "id": "greyvale_anomaly",
    "name": "The Greyvale Anomaly",
    "stages": [
        {"id": 0, "objective": "Investigate the strange lights near Greyvale.", "on_complete": {"xp": 50}},
        {"id": 1, "objective": "Find the source of the anomaly.", "on_complete": {"xp": 100}},
    ],
}


# =============================================================================
# 8.3a — Session Metrics Tracking
# =============================================================================


class TestSessionMetricsFields:
    """SessionData has the new metric fields with correct defaults."""

    def test_default_metrics(self):
        sd = SessionData(player_id="p1", location_id="loc1")
        assert sd.session_xp_earned == 0
        assert sd.session_items_found == []
        assert sd.session_quests_progressed == []
        assert sd.session_locations_visited == []
        assert sd.ending_requested is False
        assert sd.player_disconnected is False
        assert sd.disconnect_time == 0.0


@patch("tools.db.transaction", _mock_transaction)
class TestMetricsAccumulation:
    """Mutation tools increment session metrics."""

    @pytest.mark.asyncio
    @patch("tools.db.update_player_xp", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_award_xp_tracks_metric(self, mock_player, mock_update):
        from tools import award_xp

        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        await award_xp._func(ctx, amount=50, reason="defeated goblin")
        assert ctx.userdata.session_xp_earned == 50
        # Award again
        await award_xp._func(ctx, amount=30, reason="found treasure")
        assert ctx.userdata.session_xp_earned == 80

    @pytest.mark.asyncio
    @patch("tools.db.get_player_inventory", new_callable=AsyncMock)
    @patch("tools.db.add_inventory_item", new_callable=AsyncMock)
    @patch("tools.db.get_item", new_callable=AsyncMock)
    async def test_add_to_inventory_tracks_metric(self, mock_item, mock_add, mock_inv):
        from tools import add_to_inventory

        mock_item.return_value = SAMPLE_ITEM
        mock_inv.return_value = [SAMPLE_ITEM]
        ctx = _make_context()
        await add_to_inventory._func(ctx, item_id="health_potion", quantity=2, source="looted")
        assert ctx.userdata.session_items_found == ["Health Potion"]

    @pytest.mark.asyncio
    @patch("tools.db.set_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_update_quest_tracks_metric(self, mock_quest, mock_pq, mock_set):
        from tools import update_quest

        mock_quest.return_value = SAMPLE_QUEST
        mock_pq.return_value = None
        ctx = _make_context()
        await update_quest._func(ctx, quest_id="greyvale_anomaly", new_stage_id=0)
        assert ctx.userdata.session_quests_progressed == ["greyvale_anomaly"]

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_targets_at_location", new_callable=AsyncMock)
    @patch("tools.db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("tools.db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("tools.db.update_player_location", new_callable=AsyncMock)
    @patch("tools.db.upsert_map_progress", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_move_player_tracks_metric(
        self, mock_loc, mock_upsert_map, mock_update, mock_npcs, mock_disp, mock_targets, mock_player
    ):
        from tools import move_player

        mock_loc.side_effect = [SAMPLE_LOCATION, SAMPLE_DESTINATION]
        mock_npcs.return_value = []
        mock_disp.return_value = {}
        mock_targets.return_value = []
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        await move_player._func(ctx, destination_id="accord_market_square")
        assert ctx.userdata.session_locations_visited == ["accord_market_square"]


# =============================================================================
# 8.3b — Rich LLM-Generated Session Summary
# =============================================================================


class TestSessionSummary:
    """Test session_summary.py generation and fallback."""

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


# =============================================================================
# 8.3c — Agent-Side Reconnection Handling
# =============================================================================


class TestBackgroundProcessPauseResume:
    """Test pause/resume on BackgroundProcess."""

    def test_pause_sets_flag(self):
        from background_process import BackgroundProcess

        bp = BackgroundProcess(
            agent=MagicMock(),
            session=MagicMock(),
            session_data=MagicMock(),
        )
        assert bp._paused is False
        bp.pause()
        assert bp._paused is True

    def test_resume_clears_flag(self):
        from background_process import BackgroundProcess

        bp = BackgroundProcess(
            agent=MagicMock(),
            session=MagicMock(),
            session_data=MagicMock(),
        )
        bp.pause()
        bp.resume()
        assert bp._paused is False


class TestDisconnectFlags:
    """Test disconnect/reconnect flags on SessionData."""

    def test_disconnect_sets_flags(self):
        sd = SessionData(player_id="p1", location_id="loc1")
        sd.player_disconnected = True
        sd.disconnect_time = time.time()
        assert sd.player_disconnected is True
        assert sd.disconnect_time > 0

    def test_reconnect_clears_flag(self):
        sd = SessionData(player_id="p1", location_id="loc1")
        sd.player_disconnected = True
        sd.player_disconnected = False
        assert sd.player_disconnected is False


# =============================================================================
# 8.3d — Narrative Session Ending
# =============================================================================


class TestEndSessionTool:
    """Test end_session tool."""

    @pytest.mark.asyncio
    async def test_sets_ending_requested(self):
        from tools import end_session

        ctx = _make_context()
        ctx.userdata.session_xp_earned = 100
        ctx.userdata.session_items_found = ["Sword"]
        result = json.loads(await end_session._func(ctx, reason="player wants to stop"))
        assert result["status"] == "ending"
        assert ctx.userdata.ending_requested is True

    @pytest.mark.asyncio
    async def test_returns_session_stats(self):
        from tools import end_session

        ctx = _make_context()
        ctx.userdata.session_xp_earned = 75
        ctx.userdata.session_items_found = ["Shield", "Potion"]
        ctx.userdata.session_quests_progressed = ["quest_1"]
        ctx.userdata.session_locations_visited = ["loc_a", "loc_b"]
        result = json.loads(await end_session._func(ctx, reason="goodbye"))
        stats = result["session_stats"]
        assert stats["xp_earned"] == 75
        assert stats["items_found"] == ["Shield", "Potion"]
        assert stats["quests_progressed"] == ["quest_1"]
        assert stats["locations_visited"] == ["loc_a", "loc_b"]

    @pytest.mark.asyncio
    async def test_includes_narrative_instruction(self):
        from tools import end_session

        ctx = _make_context()
        result = json.loads(await end_session._func(ctx, reason="need to go"))
        assert "instruction" in result
        assert "wrap-up" in result["instruction"].lower()


class TestSessionEndingPrompt:
    """Test that system prompt includes session ending instructions."""

    def test_system_prompt_contains_session_ending(self):
        from prompts import build_system_prompt

        prompt = build_system_prompt("test_location")
        assert "Session Ending" in prompt
        assert "end_session" in prompt

    def test_end_session_in_mutation_tools(self):
        from agent import MUTATION_TOOLS
        from tools import end_session

        assert end_session in MUTATION_TOOLS


# =============================================================================
# 8.3e — Graceful LLM Error Handling
# =============================================================================


class TestLLMErrorHandling:
    """Test llm_node retry and fallback."""

    @pytest.mark.asyncio
    async def test_fallback_on_repeated_failure(self):
        with patch("agent.build_system_prompt", return_value="prompt"):
            from agent import DungeonMasterAgent

            agent = DungeonMasterAgent()

        mock_chat_ctx = MagicMock()
        mock_tools = []
        mock_settings = MagicMock()

        call_count = 0

        async def _failing_llm_node(self_agent, ctx, tools, settings):
            nonlocal call_count
            call_count += 1
            raise Exception("API timeout")
            # Make this an async generator
            yield  # pragma: no cover

        with patch("agent.Agent.default") as mock_default:
            mock_default.llm_node = _failing_llm_node

            chunks = []
            async for chunk in agent.llm_node(mock_chat_ctx, mock_tools, mock_settings):
                chunks.append(chunk)

        assert call_count == 3  # initial + 2 retries
        assert len(chunks) == 1
        assert "threads of fate" in chunks[0].lower()

    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        with patch("agent.build_system_prompt", return_value="prompt"):
            from agent import DungeonMasterAgent

            agent = DungeonMasterAgent()

        mock_chat_ctx = MagicMock()
        mock_tools = []
        mock_settings = MagicMock()

        async def _success_llm_node(self_agent, ctx, tools, settings):
            yield "Hello adventurer"

        with patch("agent.Agent.default") as mock_default:
            mock_default.llm_node = _success_llm_node

            chunks = []
            async for chunk in agent.llm_node(mock_chat_ctx, mock_tools, mock_settings):
                chunks.append(chunk)

        assert chunks == ["Hello adventurer"]

    @pytest.mark.asyncio
    async def test_succeeds_after_retry(self):
        with patch("agent.build_system_prompt", return_value="prompt"):
            from agent import DungeonMasterAgent

            agent = DungeonMasterAgent()

        mock_chat_ctx = MagicMock()
        mock_tools = []
        mock_settings = MagicMock()

        call_count = 0

        async def _flaky_llm_node(self_agent, ctx, tools, settings):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Temporary error")
            yield "Recovered response"

        with patch("agent.Agent.default") as mock_default:
            mock_default.llm_node = _flaky_llm_node

            chunks = []
            async for chunk in agent.llm_node(mock_chat_ctx, mock_tools, mock_settings):
                chunks.append(chunk)

        assert call_count == 2
        assert chunks == ["Recovered response"]

    @pytest.mark.asyncio
    async def test_mid_stream_failure_does_not_retry(self):
        """If chunks were already yielded, don't retry (would produce garbled output)."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            from agent import DungeonMasterAgent

            agent = DungeonMasterAgent()

        mock_chat_ctx = MagicMock()
        mock_tools = []
        mock_settings = MagicMock()

        call_count = 0

        async def _mid_stream_fail(self_agent, ctx, tools, settings):
            nonlocal call_count
            call_count += 1
            yield "You see a"
            raise Exception("Connection reset")

        with patch("agent.Agent.default") as mock_default:
            mock_default.llm_node = _mid_stream_fail

            chunks = []
            async for chunk in agent.llm_node(mock_chat_ctx, mock_tools, mock_settings):
                chunks.append(chunk)

        assert call_count == 1  # No retry after partial yield
        assert chunks == ["You see a"]


# =============================================================================
# 8.3f — Integration Tests
# =============================================================================


class TestSessionLifecycleIntegration:
    """Integration tests for session lifecycle features working together."""

    @pytest.mark.asyncio
    @patch("tools.db.transaction", _mock_transaction)
    @patch("tools.db.update_player_xp", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_player_inventory", new_callable=AsyncMock)
    @patch("tools.db.add_inventory_item", new_callable=AsyncMock)
    @patch("tools.db.get_item", new_callable=AsyncMock)
    async def test_metrics_accumulate_across_tools(self, mock_item, mock_add, mock_inv, mock_player, mock_xp):
        """Session metrics accumulate across multiple tool calls."""
        from tools import add_to_inventory, award_xp

        mock_player.return_value = SAMPLE_PLAYER
        mock_item.return_value = SAMPLE_ITEM
        mock_inv.return_value = [SAMPLE_ITEM]
        ctx = _make_context()

        await award_xp._func(ctx, amount=50, reason="combat")
        await add_to_inventory._func(ctx, item_id="health_potion", quantity=1, source="loot")
        await award_xp._func(ctx, amount=25, reason="exploration")

        assert ctx.userdata.session_xp_earned == 75
        assert ctx.userdata.session_items_found == ["Health Potion"]

    @pytest.mark.asyncio
    async def test_end_session_then_summary_uses_metrics(self):
        """end_session captures metrics, then summary uses them."""
        from session_summary import generate_session_summary
        from tools import end_session

        ctx = _make_context()
        ctx.userdata.session_xp_earned = 200
        ctx.userdata.session_items_found = ["Magic Ring"]
        ctx.userdata.session_quests_progressed = ["main_quest"]

        result = json.loads(await end_session._func(ctx, reason="leaving"))
        assert result["session_stats"]["xp_earned"] == 200

        llm_response = {
            "summary": "An epic session.",
            "key_events": ["Found the ring"],
            "decisions": [],
            "next_hooks": ["The ring glows"],
        }
        with patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=llm_response):
            summary = await generate_session_summary(ctx.userdata, None, time.time() - 300)

        assert summary["xp_earned"] == 200
        assert summary["items_found"] == ["Magic Ring"]
        assert summary["key_events"] == ["Found the ring"]

    def test_cross_session_recap_reflects_saved_summary(self):
        """A saved summary's key_events and next_hooks appear in the next session's recap."""
        from agent import _build_recap_instruction

        saved_summary = {
            "summary": "You defeated the shadow beast in the ruins.",
            "key_events": ["Defeated shadow beast", "Found ancient scroll", "Met the hermit"],
            "decisions": ["Allied with the hermit"],
            "next_hooks": ["The scroll hints at a hidden temple"],
        }
        recap = _build_recap_instruction(saved_summary)
        assert "shadow beast" in recap.lower()
        assert "ancient scroll" in recap.lower()
        assert "hidden temple" in recap.lower()
        assert "Allied with the hermit" in recap


class TestTranscriptLogPath:
    """Test transcript.py log_path accessor."""

    def test_log_path_returns_path(self):
        from transcript import TranscriptLogger

        tl = TranscriptLogger(room=None, log_path="/tmp/test_session.log")
        assert tl.log_path == "/tmp/test_session.log"
        tl.close()

    def test_log_path_default(self):
        from transcript import TranscriptLogger

        tl = TranscriptLogger(room=None)
        assert tl.log_path is not None
        assert "session_" in tl.log_path
        tl.close()
