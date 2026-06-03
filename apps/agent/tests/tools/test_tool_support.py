"""Tests for tool_support helpers: knowledge filtering, time conditions, DC stripping, id validation."""

import pytest
from livekit.agents.llm import ToolError

from tool_support import _strip_hidden_dcs, _validate_id, apply_time_conditions, filter_knowledge


class TestFilterKnowledge:
    def test_free_always_included(self):
        knowledge = {"free": ["fact one", "fact two"]}
        assert filter_knowledge(knowledge, "hostile") == ["fact one", "fact two"]
        assert filter_knowledge(knowledge, "neutral") == ["fact one", "fact two"]
        assert filter_knowledge(knowledge, "trusted") == ["fact one", "fact two"]

    def test_friendly_gate_requires_friendly(self):
        knowledge = {
            "free": ["public"],
            "disposition >= friendly": ["secret-ish"],
        }
        assert filter_knowledge(knowledge, "hostile") == ["public"]
        assert filter_knowledge(knowledge, "wary") == ["public"]
        assert filter_knowledge(knowledge, "neutral") == ["public"]
        assert filter_knowledge(knowledge, "friendly") == ["public", "secret-ish"]
        assert filter_knowledge(knowledge, "trusted") == ["public", "secret-ish"]

    def test_trusted_gate_requires_trusted(self):
        knowledge = {
            "free": ["public"],
            "disposition >= friendly": ["mid"],
            "disposition >= trusted": ["deep secret"],
        }
        assert filter_knowledge(knowledge, "friendly") == ["public", "mid"]
        assert filter_knowledge(knowledge, "trusted") == ["public", "mid", "deep secret"]

    def test_quest_triggered_skipped(self):
        knowledge = {
            "free": ["public"],
            "quest_triggered": {
                "quest": "greyvale_anomaly",
                "stage": 4,
                "reveals": "something secret",
            },
        }
        result = filter_knowledge(knowledge, "trusted")
        assert result == ["public"]

    def test_empty_knowledge(self):
        assert filter_knowledge({}, "neutral") == []

    def test_unknown_disposition_defaults_neutral(self):
        knowledge = {
            "free": ["public"],
            "disposition >= friendly": ["secret"],
        }
        assert filter_knowledge(knowledge, "unknown_tier") == ["public"]

    def test_cautious_treated_as_neutral(self):
        knowledge = {
            "free": ["public"],
            "disposition >= friendly": ["secret"],
        }
        assert filter_knowledge(knowledge, "cautious") == ["public"]

    def test_all_tiers_hostile(self):
        knowledge = {
            "free": ["public"],
            "disposition >= friendly": ["mid"],
            "disposition >= trusted": ["deep"],
        }
        result = filter_knowledge(knowledge, "hostile")
        assert result == ["public"]


class TestApplyTimeConditions:
    def test_daytime_passthrough(self):
        location = {
            "description": "Sunny market",
            "atmosphere": "busy",
            "conditions": {
                "time_night": {
                    "description_override": "Dark market",
                    "atmosphere": "quiet",
                }
            },
        }
        result = apply_time_conditions(location, "day")
        assert result["description"] == "Sunny market"
        assert result["atmosphere"] == "busy"

    def test_nighttime_overrides(self):
        location = {
            "description": "Sunny market",
            "atmosphere": "busy",
            "conditions": {
                "time_night": {
                    "description_override": "Dark market",
                    "atmosphere": "quiet",
                }
            },
        }
        result = apply_time_conditions(location, "night")
        assert result["description"] == "Dark market"
        assert result["atmosphere"] == "quiet"

    def test_no_conditions(self):
        location = {"description": "A field", "atmosphere": "calm"}
        result = apply_time_conditions(location, "night")
        assert result["description"] == "A field"

    def test_does_not_mutate_original(self):
        location = {
            "description": "Original",
            "atmosphere": "original",
            "conditions": {
                "time_night": {
                    "description_override": "Changed",
                    "atmosphere": "changed",
                }
            },
        }
        apply_time_conditions(location, "night")
        assert location["description"] == "Original"


class TestStripHiddenDCs:
    def test_strips_dc_and_discover_skill(self):
        location = {
            "hidden_elements": [
                {
                    "id": "secret_door",
                    "discover_skill": "perception",
                    "dc": 15,
                    "description": "A hidden passage",
                }
            ]
        }
        result = _strip_hidden_dcs(location)
        elem = result["hidden_elements"][0]
        assert elem == {"id": "secret_door", "description": "A hidden passage"}
        assert "dc" not in elem
        assert "discover_skill" not in elem

    def test_no_hidden_elements(self):
        location = {"description": "A room"}
        result = _strip_hidden_dcs(location)
        assert result == location


class TestValidateId:
    def test_valid_id(self):
        assert _validate_id("accord_guild_hall", "location_id") is None

    def test_valid_id_with_hyphens(self):
        assert _validate_id("npc-123", "npc_id") is None

    def test_empty_id(self):
        with pytest.raises(ToolError, match="Invalid location_id"):
            _validate_id("", "location_id")

    def test_too_long_id(self):
        with pytest.raises(ToolError, match="Invalid location_id"):
            _validate_id("a" * 129, "location_id")

    def test_special_characters_rejected(self):
        with pytest.raises(ToolError, match="Invalid location_id"):
            _validate_id("id; DROP TABLE", "location_id")

    def test_path_traversal_rejected(self):
        with pytest.raises(ToolError, match="Invalid location_id"):
            _validate_id("../etc/passwd", "location_id")
