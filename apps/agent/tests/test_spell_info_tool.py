"""The get_spell_info tool, read against the real seeded catalog."""

import json

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

from spell_info_tools import _get_spell_info_impl


class TestGetSpellInfo:
    async def test_returns_full_catalog_data(self):
        ctx = make_context()
        raw = await _get_spell_info_impl(ctx, "arcane_bolt")
        info = json.loads(raw)
        assert info["id"] == "arcane_bolt"
        assert info["name"]
        assert info["source"] == "arcane"
        assert info["spell_tier"] == "cantrip"
        assert info["focus_cost"] == 0
        # carries the full M3.3 schema
        for key in ("mechanics", "narration_cue", "audio_cue", "resonance_by_source", "concentration"):
            assert key in info

    async def test_unknown_spell_raises_toolerror(self):
        ctx = make_context()
        with pytest.raises(ToolError):
            await _get_spell_info_impl(ctx, "no_such_spell")
