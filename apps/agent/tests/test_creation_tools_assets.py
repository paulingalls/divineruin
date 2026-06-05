"""Tests for creation-card asset ids and image URLs.

compute_asset_id (deterministic, TS-parity hash) and the image_url stamped onto
every creation card. Split from the creation flow tests
(test_creation_tools_flow.py) to stay under the 500-line cap; the image_url
tests need the same card-push machinery, so _make_context and the _push_cards
ref are duplicated here.
"""

import hashlib
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import event_types as E
from asset_utils import compute_asset_id
from creation_tools import push_creation_cards
from session_data import CreationState, SessionData

# _func bypasses SDK Literal validation — use an Any-typed ref so Pyright accepts
# values outside the Literal that the underlying code handles.
_push_cards: Any = push_creation_cards._func


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


class TestComputeAssetId:
    def test_deterministic(self):
        """Same inputs produce same output."""
        a = compute_asset_id("npc_portrait", {"description": "a guard", "features": "tall"})
        b = compute_asset_id("npc_portrait", {"description": "a guard", "features": "tall"})
        assert a == b

    def test_different_vars_produce_different_ids(self):
        a = compute_asset_id("npc_portrait", {"description": "a guard", "features": "tall"})
        b = compute_asset_id("npc_portrait", {"description": "a mage", "features": "thin"})
        assert a != b

    def test_format(self):
        result = compute_asset_id("test", {"key": "val"})
        assert result.startswith("img_")
        assert len(result) == 4 + 16  # "img_" + 16 hex chars

    def test_matches_typescript_algorithm(self):
        """Verify Python output matches the TypeScript computeAssetId logic."""
        template_id = "npc_portrait"
        vars = {"description": "a guard", "features": "tall"}
        sorted_entries = sorted(vars.items())
        payload = template_id + json.dumps(sorted_entries)
        expected_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
        expected = f"img_{expected_hash}"
        assert compute_asset_id(template_id, vars) == expected

    def test_key_order_independent(self):
        """Vars with different insertion order but same content produce same ID."""
        a = compute_asset_id("t", {"b": "2", "a": "1"})
        b = compute_asset_id("t", {"a": "1", "b": "2"})
        assert a == b


class TestCreationCardsImageUrl:
    async def test_race_cards_have_image_url(self):
        ctx = _make_context()
        await _push_cards(ctx, category="race")
        # Verify function doesn't error out — actual image_url content tested below
        # The unit test for the actual image_url content relies on compute_asset_id tests

    async def test_class_cards_have_image_url(self):
        ctx = _make_context()
        await _push_cards(ctx, category="class")

    async def test_deity_cards_have_image_url(self):
        ctx = _make_context()
        await _push_cards(ctx, category="deity")

    @pytest.mark.parametrize("category", ["race", "class", "deity"])
    @patch("creation_tools.publish_game_event", new_callable=AsyncMock)
    async def test_card_payloads_contain_image_url(self, mock_publish, category):
        ctx = _make_context()
        await _push_cards(ctx, category=category)
        cards_call = [c for c in mock_publish.call_args_list if c[0][1] == E.CREATION_CARDS]
        assert len(cards_call) > 0
        cards = cards_call[0][0][2]["cards"]
        for card in cards:
            assert "image_url" in card, f"Card {card['id']} missing image_url"
            assert card["image_url"].startswith(f"/api/assets/images/{category}_")
