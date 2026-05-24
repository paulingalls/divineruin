"""Tests for item art URLs and story moment tool (Milestone 10.4)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import mock_txn

import event_types as E
from db import _compute_item_image_url
from session_data import SessionData

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


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None, session_id="session_abc"):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    ctx.userdata.session_id = session_id
    return ctx


class TestRecordStoryMoment:
    async def test_invalid_moment_key(self):
        from session_tools import record_story_moment

        ctx = _make_context()
        with pytest.raises(ToolError, match="Invalid moment_key"):
            await record_story_moment._func(ctx, moment_key="invalid", description="test")

    async def test_records_combat_moment(self):
        from session_tools import _record_story_moment_impl

        mock_mutations = MagicMock()
        mock_mutations.save_story_moment = AsyncMock()
        mock_activities = MagicMock()
        mock_activities.count_session_story_moments = AsyncMock(return_value=0)

        ctx = _make_context()
        result = json.loads(
            await _record_story_moment_impl(
                ctx,
                moment_key="combat",
                description="The player struck down the hollow spider.",
                mutations=mock_mutations,
                activities=mock_activities,
            )
        )
        assert result["recorded"] is True
        assert result["moment_key"] == "combat"
        assert result["image_url"].startswith("/api/assets/images/story_")
        mock_mutations.save_story_moment.assert_called_once()
        call_kwargs = mock_mutations.save_story_moment.call_args
        assert call_kwargs[1]["template_id"] == "story_combat" or call_kwargs[0][4] == "story_combat"

    async def test_records_hollow_encounter(self):
        from session_tools import _record_story_moment_impl

        mock_mutations = MagicMock()
        mock_mutations.save_story_moment = AsyncMock()
        mock_activities = MagicMock()
        mock_activities.count_session_story_moments = AsyncMock(return_value=1)

        ctx = _make_context()
        result = json.loads(
            await _record_story_moment_impl(
                ctx,
                moment_key="hollow_encounter",
                description="Teal light spread.",
                mutations=mock_mutations,
                activities=mock_activities,
            )
        )
        assert result["recorded"] is True
        assert result["moment_key"] == "hollow_encounter"

    async def test_records_god_contact(self):
        from session_tools import _record_story_moment_impl

        mock_mutations = MagicMock()
        mock_mutations.save_story_moment = AsyncMock()
        mock_activities = MagicMock()
        mock_activities.count_session_story_moments = AsyncMock(return_value=2)

        ctx = _make_context()
        result = json.loads(
            await _record_story_moment_impl(
                ctx,
                moment_key="god_contact",
                description="Veythar's voice echoed.",
                mutations=mock_mutations,
                activities=mock_activities,
            )
        )
        assert result["recorded"] is True

    async def test_enforces_max_per_session(self):
        from session_tools import _record_story_moment_impl

        mock_mutations = MagicMock()
        mock_activities = MagicMock()
        mock_activities.count_session_story_moments = AsyncMock(return_value=3)

        ctx = _make_context()
        with pytest.raises(ToolError, match="Maximum 3 story moments"):
            await _record_story_moment_impl(
                ctx,
                moment_key="combat",
                description="Another fight.",
                mutations=mock_mutations,
                activities=mock_activities,
            )

    async def test_description_too_long(self):
        from session_tools import record_story_moment

        ctx = _make_context()
        with pytest.raises(ToolError, match="exceeds maximum length"):
            await record_story_moment._func(ctx, moment_key="combat", description="x" * 600)


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


class TestAddToInventorySendsFullInventory:
    async def test_sends_full_inventory_array(self):
        from inventory_tools import _add_to_inventory_impl

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
        mock_db._compute_item_image_url = _compute_item_image_url
        mock_mutations = MagicMock()
        mock_mutations.add_inventory_item = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player_inventory = AsyncMock(return_value=SAMPLE_INVENTORY)
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=SAMPLE_ITEM_NO_ART)

        room = _make_mock_room()
        ctx = _make_context(room=room)
        await _add_to_inventory_impl(
            ctx,
            item_id="rations_basic",
            quantity=1,
            source="bought",
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )

        # Should have been called twice: inventory_updated + item_acquired
        assert room.local_participant.publish_data.call_count == 2

        # First call: inventory_updated with full array
        first_call = json.loads(room.local_participant.publish_data.call_args_list[0][0][0])
        assert first_call["type"] == E.INVENTORY_UPDATED
        assert "inventory" in first_call
        assert isinstance(first_call["inventory"], list)

        # Second call: item_acquired
        second_call = json.loads(room.local_participant.publish_data.call_args_list[1][0][0])
        assert second_call["type"] == E.ITEM_ACQUIRED
        assert second_call["name"] == "Trail Rations"

    async def test_item_acquired_includes_image_url(self):
        from inventory_tools import _add_to_inventory_impl

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
        mock_db._compute_item_image_url = _compute_item_image_url
        mock_mutations = MagicMock()
        mock_mutations.add_inventory_item = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player_inventory = AsyncMock(return_value=SAMPLE_INVENTORY)
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=SAMPLE_ITEM_WITH_ART)

        room = _make_mock_room()
        ctx = _make_context(room=room)
        await _add_to_inventory_impl(
            ctx,
            item_id="shortsword_basic",
            quantity=1,
            source="looted",
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )

        second_call = json.loads(room.local_participant.publish_data.call_args_list[1][0][0])
        assert second_call["type"] == E.ITEM_ACQUIRED
        assert "image_url" in second_call
        assert second_call["image_url"].startswith("/api/assets/images/img_")

    async def test_item_acquired_omits_image_url_when_no_art(self):
        from inventory_tools import _add_to_inventory_impl

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
        mock_db._compute_item_image_url = _compute_item_image_url
        mock_mutations = MagicMock()
        mock_mutations.add_inventory_item = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player_inventory = AsyncMock(return_value=SAMPLE_INVENTORY)
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=SAMPLE_ITEM_NO_ART)

        room = _make_mock_room()
        ctx = _make_context(room=room)
        await _add_to_inventory_impl(
            ctx,
            item_id="rations_basic",
            quantity=1,
            source="bought",
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )

        second_call = json.loads(room.local_participant.publish_data.call_args_list[1][0][0])
        assert second_call["type"] == E.ITEM_ACQUIRED
        assert "image_url" not in second_call
