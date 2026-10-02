"""Material consumption through public activity dispatch before its sound cue."""

import json
from functools import partial
from unittest.mock import AsyncMock, patch

import pytest
from inventory_snapshot_fixture import snapshot_query
from sample_fixtures import make_context, published_payloads
from test_action_sound_cues_dispatch import NEW_IDS, assert_cue, cues, db_with_commit, recorded_context

from activity_payloads import Experiment, MaterialQuantity
from activity_tools import begin_activity


@pytest.mark.parametrize("guest", [False, True])
@pytest.mark.parametrize("outcome", ["success", "failure", "no_match", "already_tried"])
async def test_activity_snapshot_before_dispatch_sound(outcome, guest):
    import random

    from dice_seeds import seed_for_d20
    from test_experimentation import IRON_SWORD, _seams

    import activity_tools
    import experimentation_tools

    ctx, log = recorded_context()
    party_context = make_context(room=ctx.userdata.room, party_member_ids=["player_2"])
    party_context.userdata.event_bus = ctx.userdata.event_bus
    ctx = party_context
    owner = "player_2" if guest else "player_1"
    matched = outcome in {"success", "failure"}
    materials = {"iron_ingot": 2, "leather_strip": 1} if matched else {"scrap": 3}
    output = "iron_sword" if matched else "mithril_blade"
    kwargs, _, mods = _seams(recipes_list=[IRON_SWORD], known_ids=[], available=materials)
    db, conn = db_with_commit(log)
    kwargs["db_mod"] = db

    async def inventory(pid):
        assert pid == owner
        assert "commit" in log
        log.append("snapshot_read")
        return []

    mods["queries"].get_player_inventory = AsyncMock(side_effect=inventory)
    mods["queries"].get_inventory_snapshot = snapshot_query(inventory)
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

    with (
        ctx.userdata._bind_authenticated_actor(owner, 1, lambda *_: None),
        patch.object(activity_tools.experimentation_tools, "_experiment_with_materials_impl", real_experiment),
    ):
        raw = await begin_activity(
            ctx,
            Experiment(
                kind="experiment",
                materials=[MaterialQuantity(material_id=mid, quantity=qty) for mid, qty in materials.items()],
                intended_output=output,
            ),
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
        assert log.index("commit") < log.index("snapshot_read") < log.index("cue")
        assert published_payloads(ctx.userdata.room) == [
            {"type": "inventory_updated", "inventory_revision": "1", "player_id": owner, "inventory": []},
            {"type": "play_sound", "sound_name": NEW_IDS["experiment"]},
        ]


@pytest.mark.parametrize("guest", [False, True])
async def test_craft_snapshot_before_dispatch_sound(guest):
    from unittest.mock import MagicMock

    from test_crafting_tools_projects import _activity, _craft_queries, _materials_mod, _recipe, _recipes_mod

    import crafting_tools
    from activity_payloads import Crafting

    ctx, log = recorded_context()
    ctx.userdata.party = make_context(party_member_ids=["player_2"]).userdata.party
    owner = "player_2" if guest else "player_1"
    db, _conn = db_with_commit(log)
    queries = _craft_queries()

    async def inventory(pid):
        assert pid == owner and "commit" in log
        log.append("snapshot_read")
        return []

    queries.get_player_inventory = AsyncMock(side_effect=inventory)
    queries.get_inventory_snapshot = snapshot_query(inventory)
    mutations = MagicMock(
        consume_player_materials=AsyncMock(side_effect=lambda *a, **k: log.append("write")),
        create_async_activity=AsyncMock(return_value="craft1"),
    )
    delegate = partial(
        crafting_tools._start_crafting_project_impl,
        db_mod=db,
        queries_mod=queries,
        mutations_mod=mutations,
        activity_mod=_activity(),
        recipes_mod=_recipes_mod(_recipe()),
        materials_mod=_materials_mod(),
    )
    with (
        ctx.userdata._bind_authenticated_actor(owner, 1, lambda *_: None),
        patch.object(crafting_tools, "_start_crafting_project_impl", delegate),
    ):
        await begin_activity(ctx, Crafting(kind="crafting", recipe_id="iron_sword"))
    log.append("return")
    assert_cue(ctx, log, NEW_IDS["crafting"])
    assert log.index("commit") < log.index("snapshot_read") < log.index("cue")
    assert published_payloads(ctx.userdata.room) == [
        {"type": "inventory_updated", "inventory_revision": "1", "player_id": owner, "inventory": []},
        {"type": "play_sound", "sound_name": NEW_IDS["crafting"]},
    ]
