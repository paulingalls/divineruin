"""Content validation for M4.6a social resistance tags (story-003).

Every NPC's authored `resistance_tags` must be canonical personality tags
(social_resolution.RESISTANCE_TAGS) so they actually gate a Tier-3 argument in the
resolver instead of silently no-opping. parse_npc_row fail-louds at load; these tests
lock that guard plus the real content/npcs.json catalog.
"""

import pytest
from npcs_config_fixture import load_fixture_config

from npcs import parse_npc_row
from role_archetypes import DISPOSITIONS
from social_resolution import RESISTANCE_TAGS


def _base_npc(**overrides) -> dict:
    """A minimal valid NPC row; override single fields per test."""
    npc = {
        "name": "Test NPC",
        "role": "tester",
        "role_archetype": "scholar_sage",
        "speech_style": "plain",
        "voice_id": "TEST_VOICE",
        "faction": "none",
        "personality": ["pragmatic"],
        "knowledge": {"free": []},
        "schedule": {},
        "default_disposition": "neutral",
    }
    npc.update(overrides)
    return npc


class TestResistanceTagParsing:
    def test_canonical_tags_accepted(self):
        parse_npc_row("npc_ok", _base_npc(resistance_tags=["pragmatic", "greedy"]))

    def test_absent_resistance_tags_ok(self):
        # The field is optional — an NPC with no social profile still parses.
        parse_npc_row("npc_bare", _base_npc())

    def test_empty_resistance_tags_ok(self):
        parse_npc_row("npc_empty", _base_npc(resistance_tags=[]))

    def test_unknown_tag_fails_loud(self):
        with pytest.raises(ValueError, match="bogus"):
            parse_npc_row("npc_bad", _base_npc(resistance_tags=["pragmatic", "bogus"]))

    def test_non_list_resistance_tags_fails_loud(self):
        with pytest.raises(ValueError):
            parse_npc_row("npc_str", _base_npc(resistance_tags="pragmatic"))


class TestNpcCatalogResistanceTags:
    def test_real_catalog_loads_and_tags_are_canonical(self):
        catalog = load_fixture_config()
        for npc_id, npc in catalog.items():
            assert "resistance_tags" in npc, f"{npc_id} missing resistance_tags"
            tags = npc["resistance_tags"]
            assert isinstance(tags, list), f"{npc_id} resistance_tags not a list"
            for tag in tags:
                assert tag in RESISTANCE_TAGS, f"{npc_id} has non-canonical tag {tag!r}"
            assert npc["default_disposition"] in DISPOSITIONS

    def test_catalog_exercises_the_full_resistance_surface(self):
        # Every canonical personality tag is used by at least one NPC, so the resolver's
        # whole Tier-3 vulnerable/resistant surface has live content behind it.
        seen = {tag for npc in load_fixture_config().values() for tag in npc.get("resistance_tags", [])}
        assert seen == set(RESISTANCE_TAGS), f"uncovered tags: {set(RESISTANCE_TAGS) - seen}"
