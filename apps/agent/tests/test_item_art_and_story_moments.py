"""Tests for item art URLs and story moment tool (Milestone 10.4)."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from db import _compute_item_image_url
from session_data import SessionData
from tools import record_story_moment

# --- _compute_item_image_url ---


class TestComputeItemImageUrl:
    def test_returns_none_without_art_template(self):
        item = {"id": "rations_basic", "name": "Trail Rations"}
        assert _compute_item_image_url(item) is None

    def test_returns_none_with_empty_art_template(self):
        item = {"id": "test", "art_template": {}}
        assert _compute_item_image_url(item) is None

    def test_returns_none_with_non_dict_art_template(self):
        item = {"id": "test", "art_template": "not a dict"}
        assert _compute_item_image_url(item) is None

    def test_returns_url_with_valid_art_template(self):
        item = {
            "id": "shortsword_basic",
            "art_template": {
                "template_id": "item_weapon",
                "vars": {"weapon_type": "shortsword"},
            },
        }
        url = _compute_item_image_url(item)
        assert url is not None
        assert url.startswith("/api/assets/images/img_")

    def test_returns_url_for_quest_item(self):
        item = {
            "id": "veythar_sealed_artifact",
            "art_template": {
                "template_id": "item_quest",
                "vars": {
                    "item_description": "a sealed stone tablet",
                    "item_features": "chisel marks and runes",
                },
            },
        }
        url = _compute_item_image_url(item)
        assert url is not None
        assert "/api/assets/images/img_" in url

    def test_returns_url_for_corrupted_item(self):
        item = {
            "id": "hollow_bone",
            "art_template": {
                "template_id": "item_corrupted_artifact",
                "vars": {
                    "item_description": "a bone fragment",
                    "item_features": "crystalline growth",
                },
            },
        }
        url = _compute_item_image_url(item)
        assert url is not None

    def test_deterministic_same_inputs(self):
        item = {
            "art_template": {
                "template_id": "item_weapon",
                "vars": {"weapon_type": "shortsword"},
            },
        }
        url1 = _compute_item_image_url(item)
        url2 = _compute_item_image_url(item)
        assert url1 == url2

    def test_different_vars_produce_different_urls(self):
        item1 = {
            "art_template": {
                "template_id": "item_weapon",
                "vars": {"weapon_type": "shortsword"},
            },
        }
        item2 = {
            "art_template": {
                "template_id": "item_weapon",
                "vars": {"weapon_type": "longsword"},
            },
        }
        assert _compute_item_image_url(item1) != _compute_item_image_url(item2)


# --- record_story_moment ---


_mock_conn = MagicMock(name="mock_txn_conn")


@asynccontextmanager
async def _mock_transaction():
    yield _mock_conn


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None, session_id="session_abc"):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    ctx.userdata.session_id = session_id
    return ctx


class TestRecordStoryMoment:
    async def test_invalid_moment_key(self):
        ctx = _make_context()
        result = json.loads(await record_story_moment._func(ctx, moment_key="invalid", description="test"))
        assert "error" in result

    @patch("tools.db.save_story_moment", new_callable=AsyncMock)
    @patch("tools.db.count_session_story_moments", new_callable=AsyncMock)
    async def test_records_combat_moment(self, mock_count, mock_save):
        mock_count.return_value = 0
        ctx = _make_context()
        result = json.loads(
            await record_story_moment._func(
                ctx, moment_key="combat", description="The player struck down the hollow spider."
            )
        )
        assert result["recorded"] is True
        assert result["moment_key"] == "combat"
        assert result["image_url"].startswith("/api/assets/images/img_")
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args
        assert call_kwargs[1]["template_id"] == "story_combat" or call_kwargs[0][4] == "story_combat"

    @patch("tools.db.save_story_moment", new_callable=AsyncMock)
    @patch("tools.db.count_session_story_moments", new_callable=AsyncMock)
    async def test_records_hollow_encounter(self, mock_count, mock_save):
        mock_count.return_value = 1
        ctx = _make_context()
        result = json.loads(
            await record_story_moment._func(ctx, moment_key="hollow_encounter", description="Teal light spread.")
        )
        assert result["recorded"] is True
        assert result["moment_key"] == "hollow_encounter"

    @patch("tools.db.save_story_moment", new_callable=AsyncMock)
    @patch("tools.db.count_session_story_moments", new_callable=AsyncMock)
    async def test_records_god_contact(self, mock_count, mock_save):
        mock_count.return_value = 2
        ctx = _make_context()
        result = json.loads(
            await record_story_moment._func(ctx, moment_key="god_contact", description="Veythar's voice echoed.")
        )
        assert result["recorded"] is True

    @patch("tools.db.count_session_story_moments", new_callable=AsyncMock)
    async def test_enforces_max_per_session(self, mock_count):
        mock_count.return_value = 3
        ctx = _make_context()
        result = json.loads(await record_story_moment._func(ctx, moment_key="combat", description="Another fight."))
        assert "error" in result
        assert "3" in result["error"]

    async def test_description_too_long(self):
        ctx = _make_context()
        result = json.loads(await record_story_moment._func(ctx, moment_key="combat", description="x" * 600))
        assert "error" in result


# --- add_to_inventory sends full inventory + item_acquired ---


def _make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


SAMPLE_ITEM_WITH_ART = {
    "id": "shortsword_basic",
    "name": "Shortsword",
    "type": "weapon",
    "description": "A simple blade.",
    "rarity": "common",
    "art_template": {
        "template_id": "item_weapon",
        "vars": {"weapon_type": "shortsword"},
    },
}

SAMPLE_ITEM_NO_ART = {
    "id": "rations_basic",
    "name": "Trail Rations",
    "type": "consumable",
    "description": "Dried meat.",
    "rarity": "common",
}

SAMPLE_INVENTORY = [
    {
        "id": "shortsword_basic",
        "name": "Shortsword",
        "slot_info": {"quantity": 1, "equipped": True},
        "image_url": "/api/assets/images/img_abc123",
    }
]


@patch("tools.db.transaction", _mock_transaction)
class TestAddToInventorySendsFullInventory:
    @patch("tools.db.get_player_inventory", new_callable=AsyncMock)
    @patch("tools.db.add_inventory_item", new_callable=AsyncMock)
    @patch("tools.db.get_item", new_callable=AsyncMock)
    async def test_sends_full_inventory_array(self, mock_item, mock_add, mock_inv):
        from tools import add_to_inventory

        mock_item.return_value = SAMPLE_ITEM_NO_ART
        mock_inv.return_value = SAMPLE_INVENTORY
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await add_to_inventory._func(ctx, item_id="rations_basic", quantity=1, source="bought")

        # Should have been called twice: inventory_updated + item_acquired
        assert room.local_participant.publish_data.call_count == 2

        # First call: inventory_updated with full array
        first_call = json.loads(room.local_participant.publish_data.call_args_list[0][0][0])
        assert first_call["type"] == "inventory_updated"
        assert "inventory" in first_call
        assert isinstance(first_call["inventory"], list)

        # Second call: item_acquired
        second_call = json.loads(room.local_participant.publish_data.call_args_list[1][0][0])
        assert second_call["type"] == "item_acquired"
        assert second_call["name"] == "Trail Rations"

    @patch("tools.db.get_player_inventory", new_callable=AsyncMock)
    @patch("tools.db.add_inventory_item", new_callable=AsyncMock)
    @patch("tools.db.get_item", new_callable=AsyncMock)
    async def test_item_acquired_includes_image_url(self, mock_item, mock_add, mock_inv):
        from tools import add_to_inventory

        mock_item.return_value = SAMPLE_ITEM_WITH_ART
        mock_inv.return_value = SAMPLE_INVENTORY
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await add_to_inventory._func(ctx, item_id="shortsword_basic", quantity=1, source="looted")

        second_call = json.loads(room.local_participant.publish_data.call_args_list[1][0][0])
        assert second_call["type"] == "item_acquired"
        assert "image_url" in second_call
        assert second_call["image_url"].startswith("/api/assets/images/img_")

    @patch("tools.db.get_player_inventory", new_callable=AsyncMock)
    @patch("tools.db.add_inventory_item", new_callable=AsyncMock)
    @patch("tools.db.get_item", new_callable=AsyncMock)
    async def test_item_acquired_omits_image_url_when_no_art(self, mock_item, mock_add, mock_inv):
        from tools import add_to_inventory

        mock_item.return_value = SAMPLE_ITEM_NO_ART
        mock_inv.return_value = SAMPLE_INVENTORY
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await add_to_inventory._func(ctx, item_id="rations_basic", quantity=1, source="bought")

        second_call = json.loads(room.local_participant.publish_data.call_args_list[1][0][0])
        assert second_call["type"] == "item_acquired"
        assert "image_url" not in second_call
