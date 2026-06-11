"""Tests for CompanionState/SessionData, the Kael entity, prompt layers, and voice config."""

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from session_data import (
    MAX_COMPANION_MEMORIES,
    CompanionState,
    SessionData,
)


class TestCompanionState:
    def test_default_values(self):
        cs = CompanionState(id="companion_kael", name="Kael")
        assert cs.is_present is True
        assert cs.is_conscious is True
        assert cs.emotional_state == "steady"
        assert cs.session_count == 0
        assert cs.affinity == 0
        assert cs.session_memories == []
        assert cs.last_speech_time == 0.0

    def test_serialization(self):
        cs = CompanionState(id="companion_kael", name="Kael", emotional_state="alert")
        d = asdict(cs)
        assert d["id"] == "companion_kael"
        assert d["name"] == "Kael"
        assert d["emotional_state"] == "alert"
        assert d["is_conscious"] is True


class TestSessionDataCompanion:
    def test_has_companion_true(self):
        sd = SessionData(player_id="p1", location_id="loc")
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        assert sd.has_companion is True

    def test_has_companion_false_when_none(self):
        sd = SessionData(player_id="p1", location_id="loc")
        assert sd.has_companion is False

    def test_has_companion_false_when_not_present(self):
        sd = SessionData(player_id="p1", location_id="loc")
        sd.companion = CompanionState(id="companion_kael", name="Kael", is_present=False)
        assert sd.has_companion is False

    def test_record_companion_memory(self):
        sd = SessionData(player_id="p1", location_id="loc")
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        sd.record_companion_memory("Traveled to Millhaven")
        assert "Traveled to Millhaven" in sd.companion.session_memories

    def test_record_companion_memory_caps_at_max(self):
        sd = SessionData(player_id="p1", location_id="loc")
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        for i in range(MAX_COMPANION_MEMORIES + 5):
            sd.record_companion_memory(f"Memory {i}")
        assert len(sd.companion.session_memories) == MAX_COMPANION_MEMORIES
        assert sd.companion.session_memories[0] == "Memory 5"

    def test_record_companion_memory_no_companion(self):
        sd = SessionData(player_id="p1", location_id="loc")
        sd.record_companion_memory("Should not crash")
        # No error raised


class TestKaelEntity:
    def test_kael_entity_valid_schema(self):
        # Kael is a dedicated Companion in companions.json (story-004 moved him out of npcs.json).
        # parents[4] = repo root (this file is nested under tests/companion/).
        companions_path = Path(__file__).resolve().parents[4] / "content" / "companions.json"
        with open(companions_path) as f:
            companions = json.load(f)
        kael = next(c for c in companions if c["id"] == "companion_kael")

        assert kael["name"] == "Kael"
        assert kael["default_disposition"] == "friendly"
        assert kael["voice_id"] == "COMPANION_KAEL"

        # Has 3 knowledge tiers
        knowledge = kael["knowledge"]
        assert "free" in knowledge
        assert "disposition >= friendly" in knowledge
        assert "disposition >= trusted" in knowledge
        assert len(knowledge["free"]) >= 2

        # Combat identity is the typed profile (scaling_rules + attacks), not an npcs combat_stats block.
        assert "scaling_rules" in kael
        assert len(kael["attacks"]) >= 2

        # Personality
        assert len(kael["personality"]) >= 3
        assert "speech_style" in kael
        assert len(kael["mannerisms"]) >= 2


class TestCompanionPrompt:
    def test_system_prompt_includes_companion_when_present(self):
        from system_prompts import build_system_prompt

        companion = CompanionState(id="companion_kael", name="Kael")
        prompt = build_system_prompt("accord_guild_hall", companion=companion)
        assert "Companion" in prompt
        assert "COMPANION_KAEL" in prompt
        assert "warm baritone" in prompt

    def test_system_prompt_excludes_companion_when_none(self):
        from system_prompts import build_system_prompt

        prompt = build_system_prompt("accord_guild_hall", companion=None)
        assert "Companion — Kael" not in prompt

    def test_system_prompt_excludes_companion_when_not_present(self):
        from system_prompts import build_system_prompt

        companion = CompanionState(id="companion_kael", name="Kael", is_present=False)
        prompt = build_system_prompt("accord_guild_hall", companion=companion)
        assert "Companion — Kael" not in prompt

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_warm_layer_includes_companion(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        from warm_prompts import build_warm_layer

        mock_loc.return_value = {
            "id": "test_loc",
            "name": "Test Location",
            "description": "A test.",
            "atmosphere": "calm",
            "exits": {},
        }
        mock_npcs.return_value = []
        mock_quests.return_value = []

        companion = CompanionState(
            id="companion_kael",
            name="Kael",
            emotional_state="alert",
            session_count=6,  # floor rank 3 -> "trusted"
            session_memories=["Traveled to Millhaven", "Fought goblins"],
        )

        result = await build_warm_layer("test_loc", "p1", "evening", companion=companion)
        assert "COMPANION — Kael" in result
        assert "alert" in result
        assert "Relationship tier: trusted" in result
        assert "Traveled to Millhaven" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_warm_layer_shows_unconscious(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        from warm_prompts import build_warm_layer

        mock_loc.return_value = {
            "id": "test_loc",
            "name": "Test",
            "description": "A test.",
            "atmosphere": "calm",
            "exits": {},
        }
        mock_npcs.return_value = []
        mock_quests.return_value = []

        companion = CompanionState(id="companion_kael", name="Kael", is_conscious=False)

        result = await build_warm_layer("test_loc", "p1", "evening", companion=companion)
        assert "Conscious: no" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_warm_layer_no_companion_section_when_none(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        from warm_prompts import build_warm_layer

        mock_loc.return_value = {
            "id": "test_loc",
            "name": "Test",
            "description": "A test.",
            "atmosphere": "calm",
            "exits": {},
        }
        mock_npcs.return_value = []
        mock_quests.return_value = []

        result = await build_warm_layer("test_loc", "p1", "evening", companion=None)
        assert "COMPANION" not in result


class TestKaelVoiceRateOffset:
    def test_kael_rate_offset(self):
        from voices import get_voice_config

        cfg = get_voice_config("COMPANION_KAEL", "neutral")
        # neutral rate = 0.95, offset = -0.05 -> 0.90
        assert cfg.speaking_rate == pytest.approx(0.90)
        assert cfg.inworld_markup == ""  # neutral has no markup
