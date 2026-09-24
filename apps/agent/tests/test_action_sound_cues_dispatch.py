import json
from contextlib import asynccontextmanager
from datetime import datetime
from functools import partial
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import FIXED_NOW, make_context, make_mock_room, published_events, published_payloads
from test_action_sound_cues import CASES as OLD_CASES

import event_types as E
import recipe_tools
import spell_tools
from action_sound_content import ACTION_SOUND_IDS
from activity_tools import _begin_activity_impl, _resolve_activity_impl
from errand_tools import _resolve_companion_errand_impl
from recipe_tools import _learn_impl
from repair_item import _repair_item_impl
from training_tools import _resolve_training_midpoint_impl

NEW_IDS = {
    "training": "action_begin_training",
    "crafting": "action_begin_crafting",
    "companion_errand": "action_begin_companion_errand",
    "experiment": "action_begin_experiment",
    "workspace": "action_begin_workspace",
    "errand_resolution": "action_resolve_companion_errand",
    "training_midpoint": "action_resolve_training_midpoint",
    "recipe": "action_learn_recipe",
    "spell": "action_learn_spell",
    "repair": "action_repair_item",
}


def test_fixed_dispatch_rows_cover_catalog():
    assert len(NEW_IDS) == len(set(NEW_IDS.values())) == 10
    from test_action_sound_cues_modes import CASES as MODE_CASES

    assert (
        set(NEW_IDS.values()) | set(OLD_CASES.values()) | set(MODE_CASES.values()) | {"action_discover_reveal"}
        == ACTION_SOUND_IDS
    )


def recorded_context():
    ctx = make_context(room=make_mock_room())
    log = []
    original = ctx.userdata.event_bus.publish

    def record(event):
        if event.event_type == E.PLAY_SOUND:
            log.append("cue")
        return original(event)

    ctx.userdata.event_bus.publish = MagicMock(side_effect=record)
    return ctx, log


def cues(ctx):
    return [event for event in published_events(ctx) if event.event_type == E.PLAY_SOUND]


def assert_cue(ctx, log, expected):
    sounds = cues(ctx)
    assert len(sounds) == 1
    assert sounds[0].payload["sound_name"] == expected
    assert published_payloads(ctx.userdata.room) == [{"type": E.PLAY_SOUND, "sound_name": expected}]
    assert log.index("write") < log.index("commit") < log.index("cue") < log.index("return")


def db_with_commit(log):
    db = MagicMock()
    conn = object()

    @asynccontextmanager
    async def transaction():
        yield conn
        log.append("commit")

    db.transaction = transaction
    return db, conn


async def test_begin_refusal_reaches_validation_without_cue():
    ctx, _ = recorded_context()
    with pytest.raises(ToolError, match="program_id"):
        await _begin_activity_impl(ctx, "training")
    assert cues(ctx) == []


@pytest.mark.parametrize("tier,risk", [("success", "none"), ("complication", "injured")])
async def test_fresh_errand_cues_after_commit_and_cached_read_is_silent(tier, risk):
    ctx, log = recorded_context()
    db, conn = db_with_commit(log)
    outcome = {"tier": tier, "narrative_context": {"risk_outcome": risk}, "decision_options": []}
    row = {
        "player_id": "player_1",
        "status": "in_progress",
        "outcome": None,
        "resolve_at": "2026-05-22T00:00:00+00:00",
        "parameters": {"errand_type": "scout"},
    }
    activity = MagicMock(get_activity=AsyncMock(side_effect=lambda *a, **k: row.copy()))
    queries = MagicMock(get_player=AsyncMock(return_value={"player_id": "player_1", "class": "warrior"}))

    async def update(_id, updates, **_kwargs):
        assert _kwargs["conn"] is conn
        row.update(updates)
        log.append("write")

    mutations = MagicMock(update_activity=AsyncMock(side_effect=update))
    relationship = MagicMock(cached_effective_rank=AsyncMock(return_value=1), apply_errand_affinity=AsyncMock())

    async def resolve(*_args):
        return outcome

    kwargs: dict[str, Any] = dict(
        db_mod=db,
        activity_mod=activity,
        queries_mod=queries,
        mutations_mod=mutations,
        companion_rel_mod=relationship,
        resolve_fn=resolve,
        now_fn=lambda: datetime.fromisoformat("2026-05-22T12:00:00+00:00"),
    )
    raw = await _resolve_companion_errand_impl(ctx, "e1", **kwargs)
    log.append("return")
    assert json.loads(raw) == outcome
    mutations.update_activity.assert_awaited_once()
    assert_cue(ctx, log, NEW_IDS["errand_resolution"])
    again = await _resolve_activity_impl(
        ctx,
        "companion_errand",
        "e1",
        errand_mod=MagicMock(_resolve_companion_errand_impl=partial(_resolve_companion_errand_impl, **kwargs)),
    )
    assert json.loads(again) == outcome
    assert len(cues(ctx)) == 1
    mutations.update_activity.assert_awaited_once()


async def test_training_midpoint_cues_after_update_commit():
    from test_training_resolve import SAMPLE_AWAITING_ROW, _make_midpoint_result

    ctx, log = recorded_context()
    db, conn = db_with_commit(log)
    row = SAMPLE_AWAITING_ROW.copy()
    training = MagicMock(get_training_activity=AsyncMock(return_value=row))

    async def update(*_args, **kwargs):
        assert kwargs["conn"] is conn
        log.append("write")

    training.update_training_activity = AsyncMock(side_effect=update)
    result = _make_midpoint_result()
    raw = await _resolve_training_midpoint_impl(
        ctx,
        "train_abc123",
        "fundamentals",
        db_mod=db,
        db_training_mod=training,
        rules_mod=lambda *_: result,
        now_fn=lambda: FIXED_NOW,
    )
    log.append("return")
    assert json.loads(raw)["state"] == "running_second_half"
    training.update_training_activity.assert_awaited_once()
    assert_cue(ctx, log, NEW_IDS["training_midpoint"])


async def test_recipe_learn_cues_after_insert_commit():
    from test_recipe_tools import _queries, _recipes, _slots

    ctx, log = recorded_context()
    db, conn = db_with_commit(log)

    async def insert(*_args, **kwargs):
        assert kwargs["conn"] is conn
        log.append("write")
        return True

    mutations = MagicMock(add_player_known_recipe=AsyncMock(side_effect=insert))
    raw = await _learn_impl(
        ctx,
        "recipe",
        "iron_sword",
        "discovery",
        db_mod=db,
        queries_mod=_queries(),
        mutations_mod=mutations,
        recipes_mod=_recipes(),
        slots_mod=_slots(),
    )
    log.append("return")
    assert json.loads(raw)["learned"] == "iron_sword"
    mutations.add_player_known_recipe.assert_awaited_once()
    assert_cue(ctx, log, NEW_IDS["recipe"])


async def test_spell_learn_cues_after_record():
    from test_learn_spell import _queries_mod, _spell, _spells_mod

    ctx, log = recorded_context()

    async def record(*_args):
        log.extend(["write", "commit"])

    cs = MagicMock(record_learned=AsyncMock(side_effect=record))
    real_spell = partial(
        spell_tools._learn_spell_impl,
        queries_mod=_queries_mod(level=3),
        spells_mod=_spells_mod(_spell(tier="standard")),
        character_spells_mod=cs,
    )

    with patch.object(recipe_tools.spell_tools, "_learn_spell_impl", real_spell):
        raw = await _learn_impl(ctx, "spell", "arcane_fireball", "discovery")
    log.append("return")
    assert json.loads(raw)["learned"] == "arcane_fireball"
    cs.record_learned.assert_awaited_once()
    assert_cue(ctx, log, NEW_IDS["spell"])


async def test_repair_cues_after_gold_commit():
    from test_repair_item import _item, _repair_kwargs

    ctx, log = recorded_context()
    kwargs, mutations, inventory = _repair_kwargs(item=_item())
    db, conn = db_with_commit(log)
    kwargs["db_mod"] = db

    async def restore(*_args, **call_kwargs):
        assert call_kwargs["conn"] is conn
        log.append("write")

    inventory.update_item_durability = AsyncMock(side_effect=restore)
    raw = await _repair_item_impl(ctx, "longsword_guild", "grimjaw", **kwargs)
    log.append("return")
    assert json.loads(raw)["restored_to"] == 10
    inventory.update_item_durability.assert_awaited_once()
    mutations.update_player_gold.assert_awaited_once()
    assert_cue(ctx, log, NEW_IDS["repair"])


async def test_failed_repair_reaches_gold_gate_without_cue():
    from test_repair_item import _item, _repair_kwargs

    ctx, _ = recorded_context()
    kwargs, mutations, inventory = _repair_kwargs(item=_item(rarity="legendary"), gold=0)
    with pytest.raises(ToolError, match="Not enough gold"):
        await _repair_item_impl(ctx, "longsword_guild", "grimjaw", **kwargs)
    kwargs["pricing_mod"].get_economy_pricing.assert_awaited_once()
    inventory.update_item_durability.assert_not_awaited()
    mutations.update_player_gold.assert_not_awaited()
    assert cues(ctx) == []


async def test_repair_rollback_after_restore_has_no_cue():
    from test_repair_item import _item, _repair_kwargs

    ctx, log = recorded_context()
    kwargs, mutations, inventory = _repair_kwargs(item=_item())
    db = MagicMock()

    @asynccontextmanager
    async def transaction():
        try:
            yield object()
        except RuntimeError:
            log.append("rollback")
            raise

    db.transaction = transaction
    kwargs["db_mod"] = db
    inventory.update_item_durability = AsyncMock(side_effect=lambda *_a, **_k: log.append("write"))
    mutations.update_player_gold = AsyncMock(side_effect=RuntimeError("gold write failed"))
    with pytest.raises(RuntimeError, match="gold write failed"):
        await _repair_item_impl(ctx, "longsword_guild", "grimjaw", **kwargs)
    assert log == ["write", "rollback"]
    assert cues(ctx) == []


async def test_refused_recipe_learn_reaches_source_gate_without_cue():
    ctx, _ = recorded_context()
    with pytest.raises(ToolError, match="Invalid learned_via"):
        await _learn_impl(ctx, "recipe", "iron_sword", "bad_source")
    assert cues(ctx) == []


@pytest.mark.parametrize("outcome", ["success", "failure", "no_match", "already_tried"])
async def test_real_experiment_cues_only_written_outcomes(outcome):
    import random

    from dice_seeds import seed_for_d20
    from test_experimentation import IRON_SWORD, _seams

    import activity_tools
    import experimentation_tools

    ctx, log = recorded_context()
    matched = outcome in {"success", "failure"}
    materials = {"iron_ingot": 2, "leather_strip": 1} if matched else {"scrap": 3}
    output = "iron_sword" if matched else "mithril_blade"
    kwargs, _, mods = _seams(recipes_list=[IRON_SWORD], known_ids=[], available=materials)
    db, conn = db_with_commit(log)
    kwargs["db_mod"] = db
    if outcome == "already_tried":
        mods["exp_db"].has_failed_experiment.return_value = True

    async def consume(*_args, **call_kwargs):
        assert call_kwargs["conn"] is conn
        log.append("write")

    mods["mutations"].consume_player_materials = AsyncMock(side_effect=consume)
    real_experiment = partial(
        experimentation_tools._experiment_with_materials_impl,
        rng=random.Random(seed_for_d20(20 if outcome == "success" else 1)),
        **kwargs,
    )

    with patch.object(activity_tools.experimentation_tools, "_experiment_with_materials_impl", real_experiment):
        raw = await _begin_activity_impl(
            ctx, "experiment", material_ids=list(materials), quantities=list(materials.values()), intended_output=output
        )
    log.append("return")
    assert json.loads(raw)["outcome"] == outcome
    if not matched:
        mods["exp_db"].has_failed_experiment.assert_awaited_once()
    if outcome == "already_tried":
        mods["mutations"].consume_player_materials.assert_not_awaited()
        mods["exp_db"].record_failed_experiment.assert_not_awaited()
        assert cues(ctx) == []
    else:
        mods["mutations"].consume_player_materials.assert_awaited_once()
        if outcome == "success":
            mods["mutations"].add_player_known_recipe.assert_awaited_once()
        elif outcome == "no_match":
            mods["exp_db"].record_failed_experiment.assert_awaited_once()
        assert_cue(ctx, log, NEW_IDS["experiment"])


async def test_mentor_variant_starts_training_without_instant_cue():
    from test_learn_variant import (
        _abilities_mod,
        _content_mod,
        _cycle,
        _persistence_mod,
        _preconds_mod,
        _progress_mod,
        _reqs_mod,
        _rules_factory,
        _variant,
        _variants_mod,
    )

    import mentor_variant_tools

    ctx, _ = recorded_context()
    progress = _progress_mod()
    training = MagicMock(
        get_player_active_training_activities=AsyncMock(return_value=[]),
        create_training_activity=AsyncMock(return_value="train_var1"),
    )
    db, _conn = db_with_commit([])
    real_variant = partial(
        mentor_variant_tools._learn_variant_impl,
        db_mod=db,
        db_training_mod=training,
        variants_mod=_variants_mod(_variant()),
        progress_mod=progress,
        abilities_mod=_abilities_mod(),
        persistence_mod=_persistence_mod(),
        requirements_mod=_reqs_mod(),
        preconditions_mod=_preconds_mod(),
        content_mod=_content_mod(),
        rules_mod=_rules_factory(_cycle()),
        now_fn=lambda: FIXED_NOW,
    )

    with patch.object(recipe_tools.mentor_variant_tools, "_learn_variant_impl", real_variant):
        raw = await _learn_impl(ctx, "variant", "warrior_cleaving_blow_drathian")
    assert json.loads(raw)["training_started"] == "warrior_cleaving_blow_drathian"
    progress.seed_progress.assert_awaited_once()
    training.create_training_activity.assert_awaited_once()
    assert cues(ctx) == []


@pytest.mark.parametrize("kind", ["training", "crafting", "companion_errand", "workspace"])
async def test_real_begin_writes_before_router_cue(kind):
    import random

    import crafting_tools
    import errand_tools
    import training_tools

    ctx, log = recorded_context()
    db, conn = db_with_commit(log)
    mods: dict[str, Any] = {}
    if kind == "training":
        from test_training_initiate import SAMPLE_PROGRAM, _make_cycle

        training = MagicMock(get_player_active_training_activities=AsyncMock(return_value=[]))

        async def create_training(*_args, **call_kwargs):
            assert call_kwargs["conn"] is conn
            log.append("write")
            return "t1"

        training.create_training_activity = AsyncMock(side_effect=create_training)
        mods["training_mod"] = SimpleNamespace(
            _initiate_training_cycle_impl=partial(
                training_tools._initiate_training_cycle_impl,
                db_mod=db,
                db_training_mod=training,
                db_content_mod=MagicMock(get_training_program=AsyncMock(return_value=SAMPLE_PROGRAM)),
                rules_mod=lambda *_: _make_cycle(),
                now_fn=lambda: FIXED_NOW,
            )
        )
        args = {"program_id": "combat_basics"}
        write = training.create_training_activity
    elif kind == "crafting":
        from test_crafting_tools_projects import _activity, _craft_queries, _materials_mod, _recipe, _recipes_mod

        mutations = MagicMock(consume_player_materials=AsyncMock())

        async def create_crafting(*_args, **call_kwargs):
            assert call_kwargs["conn"] is conn
            log.append("write")
            return "c1"

        mutations.create_async_activity = AsyncMock(side_effect=create_crafting)
        mods["crafting_mod"] = SimpleNamespace(
            _start_crafting_project_impl=partial(
                crafting_tools._start_crafting_project_impl,
                db_mod=db,
                queries_mod=_craft_queries(),
                mutations_mod=mutations,
                activity_mod=_activity(),
                recipes_mod=_recipes_mod(_recipe()),
                materials_mod=_materials_mod(),
                rng=random.Random(1),
            )
        )
        args = {"recipe_id": "iron_sword"}
        write = mutations.create_async_activity
    elif kind == "companion_errand":
        from test_errand_tools_dispatch import SCOUT_TEMPLATE, _activity, _content, _queries

        mutations = MagicMock()

        async def create_errand(*_args, **_kwargs):
            log.extend(["write", "commit"])
            return "e1"

        mutations.create_async_activity = AsyncMock(side_effect=create_errand)
        mods["errand_mod"] = SimpleNamespace(
            _dispatch_companion_errand_impl=partial(
                errand_tools._dispatch_companion_errand_impl,
                content_mod=_content(SCOUT_TEMPLATE, {"danger_level": 0}),
                queries_mod=_queries(),
                activity_mod=_activity(),
                mutations_mod=mutations,
                now_fn=lambda: FIXED_NOW,
                rng=random.Random(1),
            )
        )
        args = {"companion_id": "companion_kael", "errand_type": "scout", "destination": "millhaven"}
        write = mutations.create_async_activity
    else:
        from test_crafting_tools_workspaces import _pricing, _queries

        mutations = MagicMock(update_player_gold=AsyncMock())

        async def create_workspace(*_args, **call_kwargs):
            assert call_kwargs["conn"] is conn
            log.append("write")
            return "rent1"

        mutations.create_workspace_rental = AsyncMock(side_effect=create_workspace)
        mods["crafting_mod"] = SimpleNamespace(
            _rent_workspace_impl=partial(
                crafting_tools._rent_workspace_impl,
                db_mod=db,
                queries_mod=_queries(),
                mutations_mod=mutations,
                pricing_mod=_pricing(),
            )
        )
        args = {"workspace_type": "forge", "npc_id": "grimjaw", "days": 1}
        write = mutations.create_workspace_rental

    raw = await _begin_activity_impl(ctx, kind, **args, **mods)
    log.append("return")
    assert json.loads(raw)
    write.assert_awaited_once()
    assert_cue(ctx, log, NEW_IDS[kind])
