import json
import random
from unittest.mock import MagicMock

import pytest
from sample_fixtures import make_db_mod

from experimentation_tools import _experiment_with_materials_impl

from . import (
    guest_context,
    module,
    player_by_id,
    revocable_context,
    revoke_after,
    transaction_probe,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("match", [True, False], ids=["success", "no_match"])
async def test_guest_experiment_consumes_own_materials_and_records_result(match):
    context, actor = guest_context()
    context.userdata.event_bus = MagicMock()
    queries = module(
        get_player=None, get_player_materials=None, get_player_known_recipe_ids=[], get_player_inventory=[]
    )
    queries.get_player.side_effect = lambda player_id, **_: {
        **player_by_id(player_id),
        "attributes": {"intelligence": 20},
        "proficiencies": ["arcana"],
    }
    queries.get_player_materials.side_effect = lambda player_id, **_: (
        {"iron_ingot": 2} if player_id == "player_2" else {}
    )
    recipe = {
        "id": "iron_sword",
        "output_item": "iron_sword",
        "crafting_dc": 1,
        "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False}],
    }
    mutations = module(consume_player_materials=None, add_player_known_recipe=True)
    failed = module(has_failed_experiment=False, record_failed_experiment=None)
    with actor:
        result = json.loads(
            await _experiment_with_materials_impl(
                context,
                {"iron_ingot": 2},
                "iron_sword" if match else "unknown_sword",
                db_mod=make_db_mod()[0],
                queries_mod=queries,
                mutations_mod=mutations,
                recipes_mod=module(list_recipes=[recipe]),
                materials_mod=module(
                    get_materials_catalog={"iron_ingot": {"id": "iron_ingot", "category": "metal", "tier": 1}}
                ),
                exp_db_mod=failed,
                rng=random.Random(7),
            )
        )
    assert mutations.consume_player_materials.await_args.args[0] == "player_2"
    event = context.userdata.event_bus.publish.call_args.args[0]
    assert event.event_type == "inventory_updated"
    assert event.payload == {"player_id": "player_2", "inventory": []}
    if match:
        assert result["outcome"] == "success"
        assert mutations.add_player_known_recipe.await_args.args[0] == "player_2"
    else:
        assert result["outcome"] == "no_match"
        assert failed.record_failed_experiment.await_args.args[0] == "player_2"


@pytest.mark.asyncio
async def test_stale_experiment_add_known_recipe():
    context, actor, revocation = revocable_context()
    queries = module(get_player=None, get_player_materials=None, get_player_known_recipe_ids=[])
    queries.get_player.side_effect = lambda player_id, **_: {
        **player_by_id(player_id),
        "attributes": {"intelligence": 20},
        "proficiencies": ["arcana"],
    }
    queries.get_player_materials.side_effect = lambda player_id, **_: (
        {"iron_ingot": 2} if player_id == "player_2" else {}
    )
    recipe = {
        "id": "iron_sword",
        "output_item": "iron_sword",
        "crafting_dc": 1,
        "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False}],
    }
    mutations = module(consume_player_materials=None, add_player_known_recipe=True)
    failed = module(has_failed_experiment=False, record_failed_experiment=None)
    match = True
    revoke_after(mutations.consume_player_materials, revocation)
    tx_db, tx_state = transaction_probe()
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        await _experiment_with_materials_impl(
            context,
            {"iron_ingot": 2},
            "iron_sword" if match else "unknown_sword",
            db_mod=tx_db,
            queries_mod=queries,
            mutations_mod=mutations,
            recipes_mod=module(list_recipes=[recipe]),
            materials_mod=module(
                get_materials_catalog={"iron_ingot": {"id": "iron_ingot", "category": "metal", "tier": 1}}
            ),
            exp_db_mod=failed,
            rng=random.Random(7),
        )
    mutations.add_player_known_recipe.assert_not_awaited()
    assert tx_state["rolled_back"]
    assert not tx_state["committed"]
    mutations.consume_player_materials.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_experiment_record_failure():
    context, actor, revocation = revocable_context()
    queries = module(get_player=None, get_player_materials=None, get_player_known_recipe_ids=[])
    queries.get_player.side_effect = lambda player_id, **_: {
        **player_by_id(player_id),
        "attributes": {"intelligence": 20},
        "proficiencies": ["arcana"],
    }
    queries.get_player_materials.side_effect = lambda player_id, **_: (
        {"iron_ingot": 2} if player_id == "player_2" else {}
    )
    recipe = {
        "id": "iron_sword",
        "output_item": "iron_sword",
        "crafting_dc": 1,
        "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False}],
    }
    mutations = module(consume_player_materials=None, add_player_known_recipe=True)
    failed = module(has_failed_experiment=False, record_failed_experiment=None)
    match = False
    revoke_after(mutations.consume_player_materials, revocation)
    tx_db, tx_state = transaction_probe()
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        await _experiment_with_materials_impl(
            context,
            {"iron_ingot": 2},
            "iron_sword" if match else "unknown_sword",
            db_mod=tx_db,
            queries_mod=queries,
            mutations_mod=mutations,
            recipes_mod=module(list_recipes=[recipe]),
            materials_mod=module(
                get_materials_catalog={"iron_ingot": {"id": "iron_ingot", "category": "metal", "tier": 1}}
            ),
            exp_db_mod=failed,
            rng=random.Random(7),
        )
    failed.record_failed_experiment.assert_not_awaited()
    assert tx_state["rolled_back"]
    assert not tx_state["committed"]
    mutations.consume_player_materials.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_experiment_failed_roll_consume():
    context, actor, revocation = revocable_context()
    queries = module(get_player=None, get_player_materials=None, get_player_known_recipe_ids=[])
    queries.get_player.side_effect = lambda player_id, **_: {
        **player_by_id(player_id),
        "attributes": {"intelligence": 20},
        "proficiencies": ["arcana"],
    }
    queries.get_player_materials.side_effect = lambda player_id, **_: (
        {"iron_ingot": 2} if player_id == "player_2" else {}
    )
    recipe = {
        "id": "iron_sword",
        "output_item": "iron_sword",
        "crafting_dc": 100,
        "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False}],
    }
    mutations = module(consume_player_materials=None, add_player_known_recipe=True)
    failed = module(has_failed_experiment=False, record_failed_experiment=None)
    match = True
    revoke_after(queries.get_player_known_recipe_ids, revocation)
    tx_db, tx_state = transaction_probe()
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        await _experiment_with_materials_impl(
            context,
            {"iron_ingot": 2},
            "iron_sword" if match else "unknown_sword",
            db_mod=tx_db,
            queries_mod=queries,
            mutations_mod=mutations,
            recipes_mod=module(list_recipes=[recipe]),
            materials_mod=module(
                get_materials_catalog={"iron_ingot": {"id": "iron_ingot", "category": "metal", "tier": 1}}
            ),
            exp_db_mod=failed,
            rng=random.Random(7),
        )
    mutations.consume_player_materials.assert_not_awaited()
    assert tx_state["rolled_back"]
    assert not tx_state["committed"]
