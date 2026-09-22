import json
from functools import partial
from types import SimpleNamespace

import pytest

from crafting_tools import _query_available_workspaces_impl
from query_tools import _query_info_impl
from training_tools import _query_training_programs_impl

from . import guest_context, module, player_by_id


@pytest.mark.asyncio
async def test_query_info_training_uses_guest_eligibility_progress_and_cycle():
    context, actor = guest_context()
    queries = module(get_player=None)
    queries.get_player.side_effect = player_by_id
    library = module(get_known=[], list_learning_progress=None)
    library.list_learning_progress.side_effect = lambda player_id: (
        [{"spell_id": "guest_spell", "cycles_completed": 1}] if player_id == "player_2" else []
    )
    training = module(get_player_active_training_activities=None)
    training.get_player_active_training_activities.side_effect = lambda player_id: (
        [
            {
                "id": "guest_cycle",
                "activity_type": "technique_base",
                "state": "running_first_half",
                "data": {"program_id": "combat_basics"},
            }
        ]
        if player_id == "player_2"
        else []
    )
    handler = SimpleNamespace(
        _query_training_programs_impl=partial(
            _query_training_programs_impl,
            queries_mod=queries,
            character_spells_mod=library,
            db_training_mod=training,
            db_content_mod=module(
                list_training_programs=[{"id": "combat_basics", "training_activity_type": "technique_base"}]
            ),
        )
    )
    with actor:
        result = json.loads(await _query_info_impl(context, "training_programs", training_mod=handler))
    assert result["spell_learning_progress"][0]["spell_id"] == "guest_spell"
    assert result["active_training"][0]["id"] == "guest_cycle"
    training.get_player_active_training_activities.assert_awaited_once_with("player_2")


@pytest.mark.asyncio
async def test_query_info_workspaces_uses_guest_access_and_quote():
    context, actor = guest_context()
    queries = module(
        get_inventory_item=None,
        get_accessible_workspaces=None,
        get_npcs_at_location=[{"id": "grimjaw"}],
        get_npc_disposition=None,
    )
    queries.get_inventory_item.side_effect = lambda player_id, *_, **__: (
        {"quantity": 1} if player_id == "player_2" else None
    )
    queries.get_accessible_workspaces.side_effect = lambda player_id, *_, **__: (
        {"field", "laboratory"} if player_id == "player_2" else {"field"}
    )
    queries.get_npc_disposition.side_effect = lambda _npc, player_id, **_: (
        "trusted" if player_id == "player_2" else "neutral"
    )
    crafting = SimpleNamespace(
        _query_available_workspaces_impl=partial(
            _query_available_workspaces_impl,
            queries_mod=queries,
            content_mod=module(
                get_location={"id": "accord_guild_hall", "settlement_tier": "city", "tags": ["forge", "laboratory"]},
                get_npc=None,
            ),
            pricing_mod=module(get_economy_pricing={"disposition_multipliers": {"friendly": 0.8, "trusted": 0.6}}),
        )
    )
    with actor:
        result = json.loads(await _query_info_impl(context, "workspaces", "grimjaw", crafting_mod=crafting))
    assert result["accessible"] == ["field", "laboratory"]
    assert result["disposition"] == "trusted"
