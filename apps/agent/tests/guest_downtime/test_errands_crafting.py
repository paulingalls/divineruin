import json

import pytest
from sample_fixtures import make_db_mod

from crafting_tools import _rent_workspace_impl, _start_crafting_project_impl
from errand_tools import _dispatch_companion_errand_impl, _resolve_companion_errand_impl

from . import (
    guest_context,
    module,
    player_by_id,
    pricing,
    revocable_context,
    revoke_after,
    smith_queries,
    transaction_probe,
)


@pytest.mark.asyncio
async def test_guest_dispatch_uses_own_companion_and_slot():
    context, actor = guest_context()
    queries = module(get_player=None)
    queries.get_player.side_effect = player_by_id
    content = module(
        get_errand_template={
            "valid_destinations": ["millhaven"],
            "blocked_companions": [],
            "duration_min_seconds": 100,
            "duration_max_seconds": 100,
        },
        get_location={"danger_level": 0},
    )
    activity = module(count_active_by_slot=None)
    activity.count_active_by_slot.side_effect = lambda player_id: {"companion": 0 if player_id == "player_2" else 1}
    mutations = module(create_async_activity="guest_errand")
    with actor:
        result = json.loads(
            await _dispatch_companion_errand_impl(
                context,
                "companion_kael",
                "scout",
                "millhaven",
                queries_mod=queries,
                content_mod=content,
                activity_mod=activity,
                mutations_mod=mutations,
            )
        )
    assert result["activity_id"] == "guest_errand"
    assert mutations.create_async_activity.await_args.args[0] == "player_2"


@pytest.mark.asyncio
async def test_guest_resolves_own_errand_and_cached_result():
    context, actor = guest_context()
    activity = module(
        get_activity={
            "player_id": "player_2",
            "status": "in_progress",
            "resolve_at": None,
            "parameters": {"errand_type": "scout"},
            "outcome": None,
        }
    )
    queries = module(get_player=None)
    queries.get_player.side_effect = player_by_id
    mutations = module(update_activity=None)
    relation = module(cached_effective_rank=0, apply_errand_affinity=None)

    async def outcome(*_):
        return {"tier": "success", "relationship_change": 1}

    with actor:
        result = json.loads(
            await _resolve_companion_errand_impl(
                context,
                "guest_errand",
                db_mod=make_db_mod()[0],
                activity_mod=activity,
                queries_mod=queries,
                mutations_mod=mutations,
                companion_rel_mod=relation,
                resolve_fn=outcome,
            )
        )
    assert result["tier"] == "success"
    assert relation.apply_errand_affinity.await_args.args[0] == "player_2"
    assert mutations.update_activity.await_args.args[0] == "guest_errand"


@pytest.mark.asyncio
async def test_guest_rents_workspace_with_own_gold_and_disposition():
    context, actor = guest_context()
    queries = smith_queries("friendly")
    mutations = module(update_player_gold=None, create_workspace_rental="guest_rental")
    with actor:
        result = json.loads(
            await _rent_workspace_impl(
                context,
                "forge_laboratory",
                "grimjaw",
                2,
                db_mod=make_db_mod()[0],
                queries_mod=queries,
                mutations_mod=mutations,
                pricing_mod=pricing(),
                content_mod=module(
                    get_npc=None,
                    get_location={
                        "id": "accord_guild_hall",
                        "settlement_tier": "city",
                        "tags": ["forge", "laboratory"],
                    },
                ),
            )
        )
    assert result["workspace_type"] == "forge_laboratory"
    assert mutations.update_player_gold.await_args.args[0] == "player_2"
    assert [call.args[0] for call in mutations.create_workspace_rental.await_args_list] == ["player_2", "player_2"]


@pytest.mark.asyncio
async def test_guest_crafts_from_own_recipe_materials_and_slot():
    context, actor = guest_context()
    queries = module(
        get_player=None,
        get_inventory_item=None,
        get_player_known_recipe_ids=None,
        get_accessible_workspaces=None,
        get_player_materials=None,
    )
    queries.get_player.side_effect = player_by_id
    queries.get_player_known_recipe_ids.side_effect = lambda player_id, **_: (
        {"iron_sword"} if player_id == "player_2" else set()
    )
    queries.get_accessible_workspaces.side_effect = lambda player_id, *_, **__: (
        {"field", "forge"} if player_id == "player_2" else {"field"}
    )
    queries.get_player_materials.side_effect = lambda player_id, **_: (
        {"iron_ingot": 2} if player_id == "player_2" else {}
    )
    activity = module(lock_player_slot_rows=None, count_active_by_slot=None)
    activity.count_active_by_slot.side_effect = lambda player_id, **_: {
        "crafting": 0 if player_id == "player_2" else 1,
        "training": 0,
    }
    mutations = module(consume_player_materials=None, create_async_activity="guest_craft")
    recipe = {
        "id": "iron_sword",
        "name": "Iron Sword",
        "tier": "trained",
        "workspace_required": "forge",
        "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False}],
        "tainted_materials": False,
        "output_item": "iron_sword",
        "crafting_dc": 12,
        "async_cycles": 0,
    }
    with actor:
        result = json.loads(
            await _start_crafting_project_impl(
                context,
                "iron_sword",
                db_mod=make_db_mod()[0],
                queries_mod=queries,
                mutations_mod=mutations,
                activity_mod=activity,
                recipes_mod=module(get_recipe=recipe),
                materials_mod=module(
                    get_materials_catalog={"iron_ingot": {"id": "iron_ingot", "category": "metal", "tier": 1}}
                ),
            )
        )
    assert result["activity_id"] == "guest_craft"
    assert mutations.consume_player_materials.await_args.args[0] == "player_2"
    assert mutations.create_async_activity.await_args.args[0] == "player_2"


@pytest.mark.asyncio
async def test_revoked_guest_cannot_receive_cached_errand_result():
    context, actor, revocation = revocable_context()
    activity = module(get_activity={"player_id": "player_2", "outcome": {"tier": "success"}})
    revoke_after(activity.get_activity, revocation)
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        await _resolve_companion_errand_impl(context, "guest_errand", db_mod=make_db_mod()[0], activity_mod=activity)


@pytest.mark.asyncio
async def test_stale_errand_create_activity():
    context, actor, revocation = revocable_context()
    queries = module(get_player=None)
    queries.get_player.side_effect = player_by_id
    content = module(
        get_errand_template={
            "valid_destinations": ["millhaven"],
            "blocked_companions": [],
            "duration_min_seconds": 100,
            "duration_max_seconds": 100,
        },
        get_location={"danger_level": 0},
    )
    activity = module(count_active_by_slot=None)
    activity.count_active_by_slot.side_effect = lambda player_id: {"companion": 0 if player_id == "player_2" else 1}
    mutations = module(create_async_activity="guest_errand")
    revoke_after(activity.count_active_by_slot, revocation)
    result = None
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        result = json.loads(
            await _dispatch_companion_errand_impl(
                context,
                "companion_kael",
                "scout",
                "millhaven",
                queries_mod=queries,
                content_mod=content,
                activity_mod=activity,
                mutations_mod=mutations,
            )
        )
    mutations.create_async_activity.assert_not_awaited()
    assert result is None


@pytest.mark.asyncio
async def test_stale_errand_update_activity():
    context, actor, revocation = revocable_context()
    activity = module(
        get_activity={
            "player_id": "player_2",
            "status": "in_progress",
            "resolve_at": None,
            "parameters": {"errand_type": "scout"},
            "outcome": None,
        }
    )
    queries = module(get_player=None)
    queries.get_player.side_effect = player_by_id
    mutations = module(update_activity=None)
    relation = module(cached_effective_rank=0, apply_errand_affinity=None)

    async def outcome(*_):
        return {"tier": "success", "relationship_change": 1}

    revoke_after(relation.apply_errand_affinity, revocation)
    tx_db, tx_state = transaction_probe()
    result = None
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        result = json.loads(
            await _resolve_companion_errand_impl(
                context,
                "guest_errand",
                db_mod=tx_db,
                activity_mod=activity,
                queries_mod=queries,
                mutations_mod=mutations,
                companion_rel_mod=relation,
                resolve_fn=outcome,
            )
        )
    mutations.update_activity.assert_not_awaited()
    assert tx_state["rolled_back"]
    assert not tx_state["committed"]
    relation.apply_errand_affinity.assert_awaited_once()
    assert result is None


@pytest.mark.asyncio
async def test_stale_workspace_last_rental():
    context, actor, revocation = revocable_context()
    queries = smith_queries("friendly")
    mutations = module(update_player_gold=None, create_workspace_rental="guest_rental")
    revoke_after(mutations.update_player_gold, revocation)
    tx_db, tx_state = transaction_probe()
    result = None
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        result = json.loads(
            await _rent_workspace_impl(
                context,
                "forge_laboratory",
                "grimjaw",
                2,
                db_mod=tx_db,
                queries_mod=queries,
                mutations_mod=mutations,
                pricing_mod=pricing(),
                content_mod=module(
                    get_npc=None,
                    get_location={
                        "id": "accord_guild_hall",
                        "settlement_tier": "city",
                        "tags": ["forge", "laboratory"],
                    },
                ),
            )
        )
    assert mutations.create_workspace_rental.await_count == 2
    assert tx_state["rolled_back"]
    assert not tx_state["committed"]
    assert result is None


@pytest.mark.asyncio
async def test_stale_crafting_create_activity():
    context, actor, revocation = revocable_context()
    queries = module(
        get_player=None,
        get_inventory_item=None,
        get_player_known_recipe_ids=None,
        get_accessible_workspaces=None,
        get_player_materials=None,
    )
    queries.get_player.side_effect = player_by_id
    queries.get_player_known_recipe_ids.side_effect = lambda player_id, **_: (
        {"iron_sword"} if player_id == "player_2" else set()
    )
    queries.get_accessible_workspaces.side_effect = lambda player_id, *_, **__: (
        {"field", "forge"} if player_id == "player_2" else {"field"}
    )
    queries.get_player_materials.side_effect = lambda player_id, **_: (
        {"iron_ingot": 2} if player_id == "player_2" else {}
    )
    activity = module(lock_player_slot_rows=None, count_active_by_slot=None)
    activity.count_active_by_slot.side_effect = lambda player_id, **_: {
        "crafting": 0 if player_id == "player_2" else 1,
        "training": 0,
    }
    mutations = module(consume_player_materials=None, create_async_activity="guest_craft")
    recipe = {
        "id": "iron_sword",
        "name": "Iron Sword",
        "tier": "trained",
        "workspace_required": "forge",
        "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False}],
        "tainted_materials": False,
        "output_item": "iron_sword",
        "crafting_dc": 12,
        "async_cycles": 0,
    }
    revoke_after(mutations.consume_player_materials, revocation)
    tx_db, tx_state = transaction_probe()
    result = None
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        result = json.loads(
            await _start_crafting_project_impl(
                context,
                "iron_sword",
                db_mod=tx_db,
                queries_mod=queries,
                mutations_mod=mutations,
                activity_mod=activity,
                recipes_mod=module(get_recipe=recipe),
                materials_mod=module(
                    get_materials_catalog={"iron_ingot": {"id": "iron_ingot", "category": "metal", "tier": 1}}
                ),
            )
        )
    mutations.create_async_activity.assert_not_awaited()
    assert tx_state["rolled_back"]
    assert not tx_state["committed"]
    mutations.consume_player_materials.assert_awaited_once()
    assert result is None
