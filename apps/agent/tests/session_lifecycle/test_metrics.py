"""Tests for session-metric fields, accumulation across tools, and lifecycle integration."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import mock_txn
from session_lifecycle._helpers import _make_context

from session_data import SessionData

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


class TestMetricsAccumulation:
    """Mutation tools increment session metrics."""

    @pytest.mark.asyncio
    async def test_award_xp_tracks_metric(self):
        from progression_tools import _award_xp_impl

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)

        ctx = _make_context()
        await _award_xp_impl(
            ctx, amount=50, reason="defeated goblin", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries
        )
        assert ctx.userdata.session_xp_earned == 50
        # Award again
        await _award_xp_impl(
            ctx, amount=30, reason="found treasure", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries
        )
        assert ctx.userdata.session_xp_earned == 80

    @pytest.mark.asyncio
    async def test_add_to_inventory_tracks_metric(self):
        from inventory_tools import _add_to_inventory_impl

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
        mock_mutations = MagicMock()
        mock_mutations.add_inventory_item = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player_inventory = AsyncMock(return_value=[SAMPLE_ITEM])
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=SAMPLE_ITEM)

        ctx = _make_context()
        await _add_to_inventory_impl(
            ctx,
            item_id="health_potion",
            quantity=2,
            source="looted",
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert ctx.userdata.session_items_found == ["Health Potion"]

    @pytest.mark.asyncio
    async def test_update_quest_tracks_metric(self):
        from quest_tools import _update_quest_impl

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
        mock_mutations = MagicMock()
        mock_mutations.set_player_quest = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player_quest = AsyncMock(return_value=None)
        mock_content = MagicMock()
        mock_content.get_quest = AsyncMock(return_value=SAMPLE_QUEST)

        ctx = _make_context()
        await _update_quest_impl(
            ctx,
            quest_id="greyvale_anomaly",
            new_stage_id=0,
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert ctx.userdata.session_quests_progressed == ["greyvale_anomaly"]

    @pytest.mark.asyncio
    async def test_move_player_tracks_metric(self):
        from movement_tools import _move_player_impl

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
        mock_db.extract_exit_connections = MagicMock(return_value=[])
        mock_mutations = MagicMock()
        mock_mutations.update_player_location = AsyncMock()
        mock_mutations.upsert_map_progress = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_queries.get_npcs_at_location = AsyncMock(return_value=[])
        mock_queries.get_npc_dispositions = AsyncMock(return_value={})
        mock_queries.get_targets_at_location = AsyncMock(return_value=[])
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(side_effect=[SAMPLE_LOCATION, SAMPLE_DESTINATION])

        ctx = _make_context()
        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            await _move_player_impl(
                ctx,
                destination_id="accord_market_square",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )
        assert ctx.userdata.session_locations_visited == ["accord_market_square"]


class TestSessionLifecycleIntegration:
    """Integration tests for session lifecycle features working together."""

    @pytest.mark.asyncio
    async def test_metrics_accumulate_across_tools(self):
        """Session metrics accumulate across multiple tool calls."""
        from inventory_tools import _add_to_inventory_impl
        from progression_tools import _award_xp_impl

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        mock_mutations.add_inventory_item = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_queries.get_player_inventory = AsyncMock(return_value=[SAMPLE_ITEM])
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=SAMPLE_ITEM)

        ctx = _make_context()

        await _award_xp_impl(
            ctx, amount=50, reason="combat", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries
        )
        await _add_to_inventory_impl(
            ctx,
            item_id="health_potion",
            quantity=1,
            source="loot",
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        await _award_xp_impl(
            ctx, amount=25, reason="exploration", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries
        )

        assert ctx.userdata.session_xp_earned == 75
        assert ctx.userdata.session_items_found == ["Health Potion"]

    @pytest.mark.asyncio
    async def test_end_session_then_summary_uses_metrics(self):
        """end_session captures metrics, then summary uses them."""
        from session_summary import generate_session_summary
        from session_tools import end_session

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
