# fmt: off
import json
import random
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from crafting_tools import _query_available_workspaces_impl, _rent_workspace_impl, _start_crafting_project_impl
from errand_tools import _dispatch_companion_errand_impl, _resolve_companion_errand_impl
from experimentation_tools import _experiment_with_materials_impl
from mentor_variant_tools import _learn_variant_impl
from query_tools import _query_info_impl
from recipe_tools import _learn_recipe_impl
from repair_item import _repair_item_impl
from spell_tools import _learn_spell_impl
from training_tools import _initiate_training_cycle_impl, _query_training_programs_impl, _resolve_training_midpoint_impl


def guest_context(validator=lambda _player, _generation: None):
    context = make_context(party_member_ids=["player_2"])
    return context, context.userdata._bind_authenticated_actor("player_2", 1, validator)


def module(**methods):
    return SimpleNamespace(**{key: AsyncMock(return_value=value) for key, value in methods.items()})


def player_by_id(player_id, **_):
    return {"player_id": player_id, "class": "mage" if player_id == "player_2" else "warrior",
            "level": 5, "gold": 20 if player_id == "player_2" else 1,
            "skill_tiers": {"crafting": "master" if player_id == "player_2" else "untrained"}}


@pytest.mark.asyncio
async def test_guest_training_begin_owns_cycle_and_host_cycle_does_not_block():
    context, actor = guest_context()
    training = MagicMock(
        get_player_training_activities=AsyncMock(side_effect=lambda player_id, **_: (
            [{"state": "in_progress"}] if player_id == "player_1" else []
        )),
        create_training_activity=AsyncMock(return_value="guest_cycle"),
    )
    content = MagicMock(get_training_program=AsyncMock(return_value={
        "id": "combat_basics", "name": "Combat Basics", "training_activity_type": "technique_base"
    }))
    db_mod, _ = make_db_mod()
    with actor:
        result = json.loads(await _initiate_training_cycle_impl(
            context, "combat_basics", db_mod=db_mod, db_training_mod=training,
            db_content_mod=content,
        ))
    assert result["activity_id"] == "guest_cycle"
    assert training.create_training_activity.await_args.kwargs["player_id"] == "player_2"


@pytest.mark.asyncio
async def test_guest_training_resolve_owns_row():
    context, actor = guest_context()
    training = module(get_training_activity={
        "id": "cycle", "player_id": "player_2", "state": "awaiting_decision",
        "activity_type": "technique_base"}, update_training_activity=None)
    with actor:
        result = json.loads(await _resolve_training_midpoint_impl(
            context, "cycle", "focus", db_mod=make_db_mod()[0], db_training_mod=training,
            rules_mod=lambda *_: SimpleNamespace(state="running_second_half", second_half_seconds=3600,
                                                  micro_bonus=1, completes_at=datetime.now(UTC)),
        ))
    assert result["activity_id"] == "cycle"
    training.update_training_activity.assert_awaited_once()


@pytest.mark.asyncio
async def test_guest_dispatch_uses_own_companion_and_slot():
    context, actor = guest_context()
    queries = module(get_player=None)
    queries.get_player.side_effect = player_by_id
    content = module(get_errand_template={"valid_destinations": ["millhaven"], "blocked_companions": [],
                                          "duration_min_seconds": 100, "duration_max_seconds": 100},
                     get_location={"danger_level": 0})
    activity = module(count_active_by_slot=None)
    activity.count_active_by_slot.side_effect = lambda player_id: {
        "companion": 0 if player_id == "player_2" else 1}
    mutations = module(create_async_activity="guest_errand")
    with actor:
        result = json.loads(await _dispatch_companion_errand_impl(
            context, "companion_kael", "scout", "millhaven", queries_mod=queries,
            content_mod=content, activity_mod=activity, mutations_mod=mutations))
    assert result["activity_id"] == "guest_errand"
    assert mutations.create_async_activity.await_args.args[0] == "player_2"


@pytest.mark.asyncio
async def test_guest_resolves_own_errand_and_cached_result():
    context, actor = guest_context()
    activity = module(get_activity={"player_id": "player_2", "status": "in_progress",
                                    "resolve_at": None, "parameters": {"errand_type": "scout"}, "outcome": None})
    queries = module(get_player=None)
    queries.get_player.side_effect = player_by_id
    mutations = module(update_activity=None)
    relation = module(cached_effective_rank=0, apply_errand_affinity=None)
    async def outcome(*_):
        return {"tier": "success", "relationship_change": 1}
    with actor:
        result = json.loads(await _resolve_companion_errand_impl(
            context, "guest_errand", db_mod=make_db_mod()[0], activity_mod=activity,
            queries_mod=queries, mutations_mod=mutations, companion_rel_mod=relation,
            resolve_fn=outcome))
    assert result["tier"] == "success"
    assert relation.apply_errand_affinity.await_args.args[0] == "player_2"
    assert mutations.update_activity.await_args.args[0] == "guest_errand"


@pytest.mark.asyncio
async def test_guest_learns_recipe_from_own_slots():
    context, actor = guest_context()
    queries = module(get_player=None, count_player_known_recipes=None)
    queries.get_player.side_effect = player_by_id
    queries.count_player_known_recipes.side_effect = lambda player_id, **_: 0 if player_id == "player_2" else 8
    recipe = {"id": "iron_sword", "name": "Iron Sword", "tier": "trained"}
    slots = {"untrained": {"max_recipe_tier": "basic", "known_recipe_slots": 1},
             "master": {"max_recipe_tier": "master", "known_recipe_slots": None}}
    mutations = module(add_player_known_recipe=True)
    with actor:
        result = json.loads(await _learn_recipe_impl(
            context, "iron_sword", "npc_teaching", db_mod=make_db_mod()[0],
            queries_mod=queries, mutations_mod=mutations,
            recipes_mod=module(get_recipe=recipe), slots_mod=module(get_recipe_slots=slots)))
    assert result["learned"] == "iron_sword"
    assert mutations.add_player_known_recipe.await_args.args[0] == "player_2"


@pytest.mark.asyncio
async def test_guest_learns_spell_using_own_class():
    context, actor = guest_context()
    queries = module(get_player=None)
    queries.get_player.side_effect = player_by_id
    spells = SimpleNamespace(get_spell=lambda _: SimpleNamespace(
        id="arcane_missile", name="Arcane Missile", source="arcane", spell_tier="cantrip"))
    library = module(record_learned=None)
    with actor:
        result = json.loads(await _learn_spell_impl(
            context, "arcane_missile", "discovery", queries_mod=queries,
            spells_mod=spells, character_spells_mod=library))
    assert result["learned"] == "arcane_missile"
    assert library.record_learned.await_args.args[0] == "player_2"


@pytest.mark.asyncio
async def test_query_info_training_uses_guest_eligibility_progress_and_cycle():
    context, actor = guest_context()
    queries = module(get_player=None)
    queries.get_player.side_effect = player_by_id
    library = module(get_known=[], list_learning_progress=None)
    library.list_learning_progress.side_effect = lambda player_id: [
        {"spell_id": "guest_spell", "cycles_completed": 1}] if player_id == "player_2" else []
    training = module(get_player_training_activities=None)
    training.get_player_training_activities.side_effect = lambda player_id, state: [
        {"id": "guest_cycle", "activity_type": "technique_base", "state": state,
         "data": {"program_id": "combat_basics"}}] if player_id == "player_2" and state == "running_first_half" else []
    handler = SimpleNamespace(_query_training_programs_impl=partial(
        _query_training_programs_impl, queries_mod=queries, character_spells_mod=library,
        db_training_mod=training, db_content_mod=module(list_training_programs=[
            {"id": "combat_basics", "training_activity_type": "technique_base"}])))
    with actor:
        result = json.loads(await _query_info_impl(context, "training_programs", training_mod=handler))
    assert result["spell_learning_progress"][0]["spell_id"] == "guest_spell"
    assert result["active_training"][0]["id"] == "guest_cycle"
    assert {call.kwargs["state"] for call in training.get_player_training_activities.await_args_list} == {
        "initiated", "running_first_half", "awaiting_decision", "running_second_half"}


@pytest.mark.asyncio
async def test_query_info_workspaces_uses_guest_access_and_quote():
    context, actor = guest_context()
    queries = module(get_inventory_item=None, get_accessible_workspaces=None,
                     get_npcs_at_location=[{"id": "grimjaw"}], get_npc_disposition=None)
    queries.get_inventory_item.side_effect = lambda player_id, *_, **__: {"quantity": 1} if player_id == "player_2" else None
    queries.get_accessible_workspaces.side_effect = lambda player_id, *_, **__: {
        "field", "laboratory"} if player_id == "player_2" else {"field"}
    queries.get_npc_disposition.side_effect = lambda _npc, player_id, **_: "trusted" if player_id == "player_2" else "neutral"
    crafting = SimpleNamespace(_query_available_workspaces_impl=partial(
        _query_available_workspaces_impl, queries_mod=queries,
        content_mod=module(get_location={"id": "accord_guild_hall", "settlement_tier": "city",
                                             "tags": ["forge", "laboratory"]}, get_npc=None),
        pricing_mod=module(get_economy_pricing={"disposition_multipliers": {
            "friendly": 0.8, "trusted": 0.6}})))
    with actor:
        result = json.loads(await _query_info_impl(context, "workspaces", "grimjaw", crafting_mod=crafting))
    assert result["accessible"] == ["field", "laboratory"]
    assert result["disposition"] == "trusted"


def pricing():
    return module(get_economy_pricing={"disposition_multipliers": {"friendly": 0.8, "trusted": 0.6},
                                        "silver_per_gold": 10, "repair_cost_sp": {"common": 2}})


def smith_queries(guest_disposition="trusted"):
    queries = module(get_player=None, get_npcs_at_location=[{"id": "grimjaw"}],
                     get_npc_disposition=None)
    queries.get_player.side_effect = player_by_id
    queries.get_npc_disposition.side_effect = lambda _npc, player_id, **_: guest_disposition if player_id == "player_2" else "neutral"
    return queries


@pytest.mark.asyncio
async def test_guest_rents_workspace_with_own_gold_and_disposition():
    context, actor = guest_context()
    queries = smith_queries("friendly")
    mutations = module(update_player_gold=None, create_workspace_rental="guest_rental")
    with actor:
        result = json.loads(await _rent_workspace_impl(
            context, "forge_laboratory", "grimjaw", 2, db_mod=make_db_mod()[0], queries_mod=queries,
            mutations_mod=mutations, pricing_mod=pricing(),
            content_mod=module(get_npc=None, get_location={"id": "accord_guild_hall",
                                                        "settlement_tier": "city", "tags": ["forge", "laboratory"]})))
    assert result["workspace_type"] == "forge_laboratory"
    assert mutations.update_player_gold.await_args.args[0] == "player_2"
    assert [call.args[0] for call in mutations.create_workspace_rental.await_args_list] == ["player_2", "player_2"]


@pytest.mark.asyncio
async def test_guest_crafts_from_own_recipe_materials_and_slot():
    context, actor = guest_context()
    queries = module(get_player=None, get_inventory_item=None, get_player_known_recipe_ids=None,
                     get_accessible_workspaces=None, get_player_materials=None)
    queries.get_player.side_effect = player_by_id
    queries.get_player_known_recipe_ids.side_effect = lambda player_id, **_: {"iron_sword"} if player_id == "player_2" else set()
    queries.get_accessible_workspaces.side_effect = lambda player_id, *_, **__: {"field", "forge"} if player_id == "player_2" else {"field"}
    queries.get_player_materials.side_effect = lambda player_id, **_: {"iron_ingot": 2} if player_id == "player_2" else {}
    activity = module(lock_player_slot_rows=None, count_active_by_slot=None)
    activity.count_active_by_slot.side_effect = lambda player_id, **_: {
        "crafting": 0 if player_id == "player_2" else 1, "training": 0}
    mutations = module(consume_player_materials=None, create_async_activity="guest_craft")
    recipe = {"id": "iron_sword", "name": "Iron Sword", "tier": "trained", "workspace_required": "forge",
              "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False}],
              "tainted_materials": False, "output_item": "iron_sword", "crafting_dc": 12, "async_cycles": 0}
    with actor:
        result = json.loads(await _start_crafting_project_impl(
            context, "iron_sword", db_mod=make_db_mod()[0], queries_mod=queries,
            mutations_mod=mutations, activity_mod=activity,
            recipes_mod=module(get_recipe=recipe), materials_mod=module(get_materials_catalog={
                "iron_ingot": {"id": "iron_ingot", "category": "metal", "tier": 1}})))
    assert result["activity_id"] == "guest_craft"
    assert mutations.consume_player_materials.await_args.args[0] == "player_2"
    assert mutations.create_async_activity.await_args.args[0] == "player_2"


@pytest.mark.asyncio
@pytest.mark.parametrize("match", [True, False], ids=["success", "no_match"])
async def test_guest_experiment_consumes_own_materials_and_records_result(match):
    context, actor = guest_context()
    queries = module(get_player=None, get_player_materials=None, get_player_known_recipe_ids=[])
    queries.get_player.side_effect = lambda player_id, **_: {**player_by_id(player_id),
        "attributes": {"intelligence": 20}, "proficiencies": ["arcana"]}
    queries.get_player_materials.side_effect = lambda player_id, **_: {"iron_ingot": 2} if player_id == "player_2" else {}
    recipe = {"id": "iron_sword", "output_item": "iron_sword", "crafting_dc": 1,
              "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False}]}
    mutations = module(consume_player_materials=None, add_player_known_recipe=True)
    failed = module(has_failed_experiment=False, record_failed_experiment=None)
    with actor:
        result = json.loads(await _experiment_with_materials_impl(
            context, {"iron_ingot": 2}, "iron_sword" if match else "unknown_sword",
            db_mod=make_db_mod()[0], queries_mod=queries, mutations_mod=mutations,
            recipes_mod=module(list_recipes=[recipe]),
            materials_mod=module(get_materials_catalog={
                "iron_ingot": {"id": "iron_ingot", "category": "metal", "tier": 1}}),
            exp_db_mod=failed, rng=random.Random(7)))
    assert mutations.consume_player_materials.await_args.args[0] == "player_2"
    if match:
        assert result["outcome"] == "success"
        assert mutations.add_player_known_recipe.await_args.args[0] == "player_2"
    else:
        assert result["outcome"] == "no_match"
        assert failed.record_failed_experiment.await_args.args[0] == "player_2"


@pytest.mark.asyncio
async def test_guest_starts_mentor_variant_from_own_eligibility():
    context, actor = guest_context()
    variant = SimpleNamespace(ability_id="warrior_cleaving_blow", mentor_id="guildmaster_torin",
                              cultural_attribution="Drathian")
    requirements = module(check_mentor_requirements=None)
    requirements.check_mentor_requirements.side_effect = lambda player_id, *_: SimpleNamespace(
        met=player_id == "player_2", unmet=[])
    progress = module(is_unlocked=False, seed_progress=None)
    persistence = module(owns_elective=None)
    persistence.owns_elective.side_effect = lambda player_id, *_ , **__: player_id == "player_2"
    training = module(get_player_training_activities=[], create_training_activity="guest_variant_cycle")
    with actor:
        result = json.loads(await _learn_variant_impl(
            context, "cleaving_drathian", db_mod=make_db_mod()[0],
            variants_mod=SimpleNamespace(get_mentor_variant=lambda _: variant),
            requirements_mod=requirements, preconditions_mod=module(require_npc_present=None),
            content_mod=module(get_npc={"mentor": {"training_cycles": 3}}),
            progress_mod=progress, persistence_mod=persistence,
            abilities_mod=SimpleNamespace(get_ability=lambda _: SimpleNamespace(
                ability_type="elective", name="Cleaving Blow")), db_training_mod=training))
    assert result["activity_id"] == "guest_variant_cycle"
    assert progress.seed_progress.await_args.args[0] == "player_2"
    assert training.create_training_activity.await_args.kwargs["player_id"] == "player_2"


@pytest.mark.asyncio
async def test_guest_repairs_own_item_at_own_price():
    context, actor = guest_context()
    queries = smith_queries("friendly")
    queries.get_player_inventory = AsyncMock(side_effect=lambda player_id, **_: [{
        "id": "guest_blade", "name": "Blade", "rarity": "common", "durability_tier": "standard",
        "slot_info": {"current_hits": 3}}] if player_id == "player_2" else [])
    mutations = module(update_player_gold=None)
    inventory = module(update_item_durability=None)
    with actor:
        result = json.loads(await _repair_item_impl(
            context, "guest_blade", "grimjaw", db_mod=make_db_mod()[0],
            queries_mod=queries, mutations_mod=mutations, inv_mutations_mod=inventory,
            pricing_mod=pricing(), content_mod=module(get_npc=None)))
    assert result["item_id"] == "guest_blade"
    assert inventory.update_item_durability.await_args.args[0] == "player_2"
    assert mutations.update_player_gold.await_args.args[0] == "player_2"


@pytest.mark.asyncio
@pytest.mark.parametrize("exercise,last_check", [
    (test_guest_training_begin_owns_cycle_and_host_cycle_does_not_block, 2),
    (test_guest_training_resolve_owns_row, 2),
    (test_guest_dispatch_uses_own_companion_and_slot, 2),
    (test_guest_resolves_own_errand_and_cached_result, 3),
    (test_guest_rents_workspace_with_own_gold_and_disposition, 4),
    (test_guest_crafts_from_own_recipe_materials_and_slot, 3),
    (partial(test_guest_experiment_consumes_own_materials_and_records_result, True), 3),
    (partial(test_guest_experiment_consumes_own_materials_and_records_result, False), 3),
    (test_guest_learns_recipe_from_own_slots, 2),
    (test_guest_learns_spell_using_own_class, 2),
    (test_guest_starts_mentor_variant_from_own_eligibility, 3),
    (test_guest_repairs_own_item_at_own_price, 3),
], ids=["training_begin", "training_resolve", "errand_begin", "errand_resolve",
        "workspace_rent", "craft_begin", "experiment_success", "experiment_no_match",
        "recipe_learn", "spell_learn", "variant_learn", "repair"])
async def test_stale_generation_refuses_at_last_write(exercise, last_check, monkeypatch):
    original = guest_context
    original_module = module
    pending = []
    committed = []
    writes = {"create_training_activity", "update_training_activity", "create_async_activity",
              "apply_errand_affinity", "update_activity", "update_player_gold",
              "create_workspace_rental", "consume_player_materials", "add_player_known_recipe",
              "record_failed_experiment", "record_learned", "seed_progress",
              "update_item_durability"}
    def tracked_module(**methods):
        result = original_module(**methods)
        for name, value in methods.items():
            if name in writes:
                async def record(*args, _name=name, _value=value, **_kwargs):
                    pending.append((_name, args))
                    return _value
                getattr(result, name).side_effect = record
        return result
    @asynccontextmanager
    async def transaction():
        start = len(pending)
        try:
            yield object()
        except BaseException:
            del pending[start:]
            raise
        else:
            committed.extend(pending[start:])
            del pending[start:]
    monkeypatch.setattr(sys.modules[__name__], "module", tracked_module)
    monkeypatch.setattr(sys.modules[__name__], "make_db_mod", lambda: (SimpleNamespace(transaction=transaction), object()))
    def stale_context():
        checks = 0
        def validate(_player, _generation):
            nonlocal checks
            checks += 1
            if checks == last_check:
                raise RuntimeError("stale generation")
        return original(validate)
    monkeypatch.setattr(sys.modules[__name__], "guest_context", stale_context)
    with pytest.raises(RuntimeError, match="stale generation"):
        await exercise()
    assert committed == []
    assert pending == []


@pytest.mark.asyncio
async def test_revoked_guest_cannot_receive_cached_errand_result():
    calls = 0
    def validate(_player, _generation):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("stale generation")
    context, actor = guest_context(validate)
    activity = module(get_activity={"player_id": "player_2", "outcome": {"tier": "success"}})
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        await _resolve_companion_errand_impl(
            context, "guest_errand", db_mod=make_db_mod()[0], activity_mod=activity)


@pytest.mark.asyncio
async def test_guest_cannot_resolve_host_training_or_errand():
    context, actor = guest_context()
    training = module(get_training_activity={"player_id": "player_1", "state": "awaiting_decision"},
                      update_training_activity=None)
    activity = module(get_activity={"player_id": "player_1", "outcome": {"tier": "success"}})
    with actor:
        with pytest.raises(ToolError, match="does not belong"):
            await _resolve_training_midpoint_impl(
                context, "host_cycle", "focus", db_mod=make_db_mod()[0], db_training_mod=training)
        with pytest.raises(ToolError, match="does not belong"):
            await _resolve_companion_errand_impl(
                context, "host_errand", db_mod=make_db_mod()[0], activity_mod=activity)
    training.update_training_activity.assert_not_awaited()
