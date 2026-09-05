"""The world-effect disposition target vocabulary: runtime resolution + authoring-time validation.

Extracted from test_world_effects.py (467 lines against the 500 hard cap, constraint 2) when
story-013 collapsed three independent copies of the same shorthand map onto one symbol.

The `companion` shorthand is the reason this file exists. At runtime it resolves to the
player's ASSIGNED companion, never to a literal; at authoring time it cannot be resolved at
all, so validation is set membership (does any companion exist?), not identity.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from quest_tools import _apply_world_effects
from session_data import CompanionState, SessionData
from world_effect_targets import EFFECT_NPC_MAP, is_valid_disposition_target

CONTENT_DIR = Path(__file__).parent.parent.parent.parent / "content"


def _load_ids(filename: str) -> set[str]:
    return {entity["id"] for entity in json.loads((CONTENT_DIR / filename).read_text())}


def _mocks():
    queries = MagicMock()
    queries.get_npc_disposition = AsyncMock(return_value="neutral")
    mutations = MagicMock()
    mutations.set_npc_disposition = AsyncMock()
    content = MagicMock()
    content.get_npc = AsyncMock(return_value={"default_disposition": "neutral"})
    return mutations, queries, content


class TestCompanionShorthandResolvesPerPlayer:
    """AC2. No content row produces a `companion_disposition` effect (debt filed at C3) — these
    unit tests ARE the pin, and the card says so."""

    @pytest.mark.asyncio
    async def test_companion_disposition_lands_on_the_assigned_companion_not_kael(self):
        mutations, queries, content = _mocks()
        session = SessionData(player_id="p1", location_id="accord_market_square")
        session.companion = CompanionState(id="companion_sable", name="Sable")
        pending: list[tuple[str, dict]] = []

        await _apply_world_effects(
            ["companion_disposition +3"],
            session,
            pending,
            mutations=mutations,
            queries=queries,
            content=content,
        )

        mutations.set_npc_disposition.assert_called_once()
        assert mutations.set_npc_disposition.call_args[0][0] == "companion_sable"

    @pytest.mark.asyncio
    async def test_companion_disposition_with_no_bound_companion_writes_nothing(self):
        mutations, queries, content = _mocks()
        session = SessionData(player_id="p1", location_id="accord_market_square")
        pending: list[tuple[str, dict]] = []

        await _apply_world_effects(
            ["companion_disposition +3"],
            session,
            pending,
            mutations=mutations,
            queries=queries,
            content=content,
        )

        mutations.set_npc_disposition.assert_not_called()
        assert pending == []


class TestEffectNpcMap:
    def test_static_shorthands_resolve(self):
        assert EFFECT_NPC_MAP["torin"] == "guildmaster_torin"
        assert EFFECT_NPC_MAP["yanna"] == "elder_yanna"
        assert EFFECT_NPC_MAP["emris"] == "scholar_emris"

    def test_companion_is_absent_from_the_static_map(self):
        """It is per-player at runtime; a static entry is exactly the defect story-013 removed."""
        assert "companion" not in EFFECT_NPC_MAP


class TestIsValidDispositionTarget:
    def test_companion_shorthand_is_valid_whenever_any_companion_exists(self):
        npc_ids, companion_ids = _load_ids("npcs.json"), _load_ids("companions.json")
        assert is_valid_disposition_target("companion", npc_ids, companion_ids)
        assert not is_valid_disposition_target("companion", npc_ids, set())

    def test_rejects_an_unknown_target(self):
        npc_ids, companion_ids = _load_ids("npcs.json"), _load_ids("companions.json")
        assert is_valid_disposition_target("torin", npc_ids, companion_ids)
        assert is_valid_disposition_target("companion_kael", npc_ids, companion_ids)
        assert not is_valid_disposition_target("guildmaster_toren", npc_ids, companion_ids)
        assert not is_valid_disposition_target("nobody", npc_ids, companion_ids)
