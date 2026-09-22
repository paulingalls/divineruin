import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sample_fixtures import make_db_mod

from mentor_variant_tools import _learn_variant_impl
from recipe_tools import _learn_recipe_impl
from repair_item import _repair_item_impl
from spell_tools import _learn_spell_impl

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
async def test_guest_learns_recipe_from_own_slots():
    context, actor = guest_context()
    queries = module(get_player=None, count_player_known_recipes=None)
    queries.get_player.side_effect = player_by_id
    queries.count_player_known_recipes.side_effect = lambda player_id, **_: 0 if player_id == "player_2" else 8
    recipe = {"id": "iron_sword", "name": "Iron Sword", "tier": "trained"}
    slots = {
        "untrained": {"max_recipe_tier": "basic", "known_recipe_slots": 1},
        "master": {"max_recipe_tier": "master", "known_recipe_slots": None},
    }
    mutations = module(add_player_known_recipe=True)
    with actor:
        result = json.loads(
            await _learn_recipe_impl(
                context,
                "iron_sword",
                "npc_teaching",
                db_mod=make_db_mod()[0],
                queries_mod=queries,
                mutations_mod=mutations,
                recipes_mod=module(get_recipe=recipe),
                slots_mod=module(get_recipe_slots=slots),
            )
        )
    assert result["learned"] == "iron_sword"
    assert mutations.add_player_known_recipe.await_args.args[0] == "player_2"


@pytest.mark.asyncio
async def test_guest_learns_spell_using_own_class():
    context, actor = guest_context()
    queries = module(get_player=None)
    queries.get_player.side_effect = player_by_id
    spells = SimpleNamespace(
        get_spell=lambda _: SimpleNamespace(
            id="arcane_missile", name="Arcane Missile", source="arcane", spell_tier="cantrip"
        )
    )
    library = module(record_learned=None)
    with actor:
        result = json.loads(
            await _learn_spell_impl(
                context,
                "arcane_missile",
                "discovery",
                queries_mod=queries,
                spells_mod=spells,
                character_spells_mod=library,
            )
        )
    assert result["learned"] == "arcane_missile"
    assert library.record_learned.await_args.args[0] == "player_2"


@pytest.mark.asyncio
async def test_guest_starts_mentor_variant_from_own_eligibility():
    context, actor = guest_context()
    variant = SimpleNamespace(
        ability_id="warrior_cleaving_blow", mentor_id="guildmaster_torin", cultural_attribution="Drathian"
    )
    requirements = module(check_mentor_requirements=None)
    requirements.check_mentor_requirements.side_effect = lambda player_id, *_: SimpleNamespace(
        met=player_id == "player_2", unmet=[]
    )
    progress = module(is_unlocked=False, seed_progress=None)
    persistence = module(owns_elective=None)
    persistence.owns_elective.side_effect = lambda player_id, *_, **__: player_id == "player_2"
    training = module(get_player_active_training_activities=[], create_training_activity="guest_variant_cycle")
    with actor:
        result = json.loads(
            await _learn_variant_impl(
                context,
                "cleaving_drathian",
                db_mod=make_db_mod()[0],
                variants_mod=SimpleNamespace(get_mentor_variant=lambda _: variant),
                requirements_mod=requirements,
                preconditions_mod=module(require_npc_present=None),
                content_mod=module(get_npc={"mentor": {"training_cycles": 3}}),
                progress_mod=progress,
                persistence_mod=persistence,
                abilities_mod=SimpleNamespace(
                    get_ability=lambda _: SimpleNamespace(ability_type="elective", name="Cleaving Blow")
                ),
                db_training_mod=training,
            )
        )
    assert result["activity_id"] == "guest_variant_cycle"
    assert progress.seed_progress.await_args.args[0] == "player_2"
    assert training.create_training_activity.await_args.kwargs["player_id"] == "player_2"


@pytest.mark.asyncio
async def test_guest_repairs_own_item_at_own_price():
    context, actor = guest_context()
    queries = smith_queries("friendly")
    queries.get_player_inventory = AsyncMock(
        side_effect=lambda player_id, **_: (
            [
                {
                    "id": "guest_blade",
                    "name": "Blade",
                    "rarity": "common",
                    "durability_tier": "standard",
                    "slot_info": {"current_hits": 3},
                }
            ]
            if player_id == "player_2"
            else []
        )
    )
    mutations = module(update_player_gold=None)
    inventory = module(update_item_durability=None)
    with actor:
        result = json.loads(
            await _repair_item_impl(
                context,
                "guest_blade",
                "grimjaw",
                db_mod=make_db_mod()[0],
                queries_mod=queries,
                mutations_mod=mutations,
                inv_mutations_mod=inventory,
                pricing_mod=pricing(),
                content_mod=module(get_npc=None),
            )
        )
    assert result["item_id"] == "guest_blade"
    assert inventory.update_item_durability.await_args.args[0] == "player_2"
    assert mutations.update_player_gold.await_args.args[0] == "player_2"


@pytest.mark.asyncio
async def test_stale_recipe_add_known():
    context, actor, revocation = revocable_context()
    queries = module(get_player=None, count_player_known_recipes=None)
    queries.get_player.side_effect = player_by_id
    queries.count_player_known_recipes.side_effect = lambda player_id, **_: 0 if player_id == "player_2" else 8
    recipe = {"id": "iron_sword", "name": "Iron Sword", "tier": "trained"}
    slots = {
        "untrained": {"max_recipe_tier": "basic", "known_recipe_slots": 1},
        "master": {"max_recipe_tier": "master", "known_recipe_slots": None},
    }
    mutations = module(add_player_known_recipe=True)
    revoke_after(queries.count_player_known_recipes, revocation)
    tx_db, tx_state = transaction_probe()
    result = None
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        result = json.loads(
            await _learn_recipe_impl(
                context,
                "iron_sword",
                "npc_teaching",
                db_mod=tx_db,
                queries_mod=queries,
                mutations_mod=mutations,
                recipes_mod=module(get_recipe=recipe),
                slots_mod=module(get_recipe_slots=slots),
            )
        )
    mutations.add_player_known_recipe.assert_not_awaited()
    assert tx_state["rolled_back"]
    assert not tx_state["committed"]
    assert result is None


@pytest.mark.asyncio
async def test_stale_spell_record_learned():
    context, actor, revocation = revocable_context()
    queries = module(get_player=None)
    queries.get_player.side_effect = player_by_id
    spells = SimpleNamespace(
        get_spell=lambda _: SimpleNamespace(
            id="arcane_missile", name="Arcane Missile", source="arcane", spell_tier="cantrip"
        )
    )
    library = module(record_learned=None)
    revoke_after(queries.get_player, revocation)
    result = None
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        result = json.loads(
            await _learn_spell_impl(
                context,
                "arcane_missile",
                "discovery",
                queries_mod=queries,
                spells_mod=spells,
                character_spells_mod=library,
            )
        )
    library.record_learned.assert_not_awaited()
    assert result is None


@pytest.mark.asyncio
async def test_stale_variant_create_activity():
    context, actor, revocation = revocable_context()
    variant = SimpleNamespace(
        ability_id="warrior_cleaving_blow", mentor_id="guildmaster_torin", cultural_attribution="Drathian"
    )
    requirements = module(check_mentor_requirements=None)
    requirements.check_mentor_requirements.side_effect = lambda player_id, *_: SimpleNamespace(
        met=player_id == "player_2", unmet=[]
    )
    progress = module(is_unlocked=False, seed_progress=None)
    persistence = module(owns_elective=None)
    persistence.owns_elective.side_effect = lambda player_id, *_, **__: player_id == "player_2"
    training = module(get_player_active_training_activities=[], create_training_activity="guest_variant_cycle")
    revoke_after(progress.seed_progress, revocation)
    tx_db, tx_state = transaction_probe()
    result = None
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        result = json.loads(
            await _learn_variant_impl(
                context,
                "cleaving_drathian",
                db_mod=tx_db,
                variants_mod=SimpleNamespace(get_mentor_variant=lambda _: variant),
                requirements_mod=requirements,
                preconditions_mod=module(require_npc_present=None),
                content_mod=module(get_npc={"mentor": {"training_cycles": 3}}),
                progress_mod=progress,
                persistence_mod=persistence,
                abilities_mod=SimpleNamespace(
                    get_ability=lambda _: SimpleNamespace(ability_type="elective", name="Cleaving Blow")
                ),
                db_training_mod=training,
            )
        )
    training.create_training_activity.assert_not_awaited()
    assert tx_state["rolled_back"]
    assert not tx_state["committed"]
    progress.seed_progress.assert_awaited_once()
    assert result is None


@pytest.mark.asyncio
async def test_stale_repair_gold_debit():
    context, actor, revocation = revocable_context()
    queries = smith_queries("friendly")
    queries.get_player_inventory = AsyncMock(
        side_effect=lambda player_id, **_: (
            [
                {
                    "id": "guest_blade",
                    "name": "Blade",
                    "rarity": "common",
                    "durability_tier": "standard",
                    "slot_info": {"current_hits": 3},
                }
            ]
            if player_id == "player_2"
            else []
        )
    )
    mutations = module(update_player_gold=None)
    inventory = module(update_item_durability=None)
    revoke_after(inventory.update_item_durability, revocation)
    tx_db, tx_state = transaction_probe()
    result = None
    with actor, pytest.raises(RuntimeError, match="stale generation"):
        result = json.loads(
            await _repair_item_impl(
                context,
                "guest_blade",
                "grimjaw",
                db_mod=tx_db,
                queries_mod=queries,
                mutations_mod=mutations,
                inv_mutations_mod=inventory,
                pricing_mod=pricing(),
                content_mod=module(get_npc=None),
            )
        )
    mutations.update_player_gold.assert_not_awaited()
    assert tx_state["rolled_back"]
    assert not tx_state["committed"]
    inventory.update_item_durability.assert_awaited_once()
    assert result is None
