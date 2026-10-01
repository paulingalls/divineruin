"""Full owner snapshots follow gameplay and precede the action cue."""

from unittest.mock import AsyncMock

import pytest
from sample_fixtures import make_context, make_mock_room, published_payloads

from tools.test_gathering_tools import _NODE, _gather_mocks, _run


@pytest.mark.parametrize("guest", [False, True])
@pytest.mark.parametrize("node", [False, True])
async def test_gather_result_snapshot_sound_order(guest, node):
    context = make_context(room=make_mock_room(), party_member_ids=["guest"])
    from unittest.mock import MagicMock

    context.userdata.event_bus = MagicMock()
    actor = context.userdata._bind_authenticated_actor("guest" if guest else "player_1", 1, lambda *_: None)
    owner = "guest" if guest else "player_1"
    inventory = [{"id": "oak_wood", "name": "Oak Wood", "type": "material", "slot_info": {"quantity": 2}}]
    mocks = _gather_mocks(nodes=[_NODE] if node else [])
    mocks[0].get_player_inventory = AsyncMock(return_value=inventory)
    with actor:
        await _run(context, mocks, rng_val=20 if node else 11)
    payloads = published_payloads(context.userdata.room)
    assert [p["type"] for p in payloads] == [
        "dice_roll",
        *(["hidden_revealed"] if node else []),
        "inventory_updated",
        "play_sound",
    ]
    assert payloads[-2] == {"type": "inventory_updated", "player_id": owner, "inventory": inventory}
    assert [
        {"type": call.args[0].event_type, **call.args[0].payload}
        for call in context.userdata.event_bus.publish.call_args_list
    ] == payloads
    mocks[0].get_player_inventory.assert_awaited_once_with(owner)
    actor.__exit__(None, None, None)


@pytest.mark.parametrize("roll,output", [(20, "iron_sword"), (1, "iron_sword"), (20, "unknown_sword")])
async def test_experiment_consumption_publishes_full_snapshot(roll, output):
    from sample_fixtures import FixedRng
    from test_experimentation import IRON_SWORD, _seams

    from experimentation_tools import _experiment_with_materials_impl

    kwargs, _, mods = _seams(recipes_list=[IRON_SWORD], known_ids=[], available={"iron_ingot": 2, "leather_strip": 1})
    mods["queries"].get_player_inventory = AsyncMock(return_value=[])
    context = make_context(room=make_mock_room())
    await _experiment_with_materials_impl(
        context, {"iron_ingot": 2, "leather_strip": 1}, output, rng=FixedRng(roll), **kwargs
    )
    assert published_payloads(context.userdata.room) == [
        {"type": "inventory_updated", "player_id": "player_1", "inventory": []}
    ]


async def test_crafting_consumption_publishes_snapshot():
    from unittest.mock import MagicMock

    from sample_fixtures import make_db_mod
    from test_crafting_tools_projects import _activity, _craft_queries, _materials_mod, _recipe, _recipes_mod

    from crafting_tools import _start_crafting_project_impl

    queries = _craft_queries()
    queries.get_player_inventory = AsyncMock(return_value=[])
    context = make_context(room=make_mock_room())
    await _start_crafting_project_impl(
        context,
        "iron_sword",
        db_mod=make_db_mod()[0],
        queries_mod=queries,
        mutations_mod=MagicMock(
            consume_player_materials=AsyncMock(), create_async_activity=AsyncMock(return_value="c1")
        ),
        activity_mod=_activity(),
        recipes_mod=_recipes_mod(_recipe()),
        materials_mod=_materials_mod(),
    )
    assert published_payloads(context.userdata.room) == [
        {"type": "inventory_updated", "player_id": "player_1", "inventory": []}
    ]


async def test_inventory_gain_result_before_snapshot():
    from unittest.mock import MagicMock

    from sample_fixtures import make_db_mod

    from inventory_tools import _transact_impl

    context = make_context(room=make_mock_room())
    queries = MagicMock(get_player_inventory=AsyncMock(return_value=[]))
    await _transact_impl(
        context,
        "crystal_flask",
        1,
        "found",
        db_mod=make_db_mod()[0],
        queries=queries,
        mutations=MagicMock(add_inventory_item=AsyncMock()),
        content=MagicMock(get_item=AsyncMock(return_value={"id": "crystal_flask", "name": "Crystal Flask"})),
    )
    events = published_payloads(context.userdata.room)
    assert [e["type"] for e in events] == ["item_acquired", "inventory_updated"]
    assert events[-1] == {"type": "inventory_updated", "player_id": "player_1", "inventory": []}


async def test_quest_results_before_owner_snapshots():
    from test_guest_quests import advance, quest_case

    case = quest_case(
        [{"on_complete": {"rewards": [{"item": "relic"}, {"item": "relic"}]}}], {"player_1": 0, "player_2": 0}
    )
    case[4].get_item.return_value = {"name": "Relic"}
    case[5].get_player_inventory = AsyncMock(side_effect=lambda pid: [{"id": pid}])
    await advance(case, 1)
    events = published_payloads(case[0].userdata.room)
    assert [e["type"] for e in events] == ["quest_updated", "inventory_updated", "inventory_updated"]
    assert events[1:] == [
        {"type": "inventory_updated", "player_id": pid, "inventory": [{"id": pid}]} for pid in ["player_1", "player_2"]
    ]


@pytest.mark.parametrize("guest", [False, True])
@pytest.mark.parametrize("failure", ["no_gain", "rollback"])
async def test_gather_refusal_no_gain_and_rollback_emit_no_snapshot(guest, failure):
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    context = make_context(room=make_mock_room(), party_member_ids=["guest"])
    context.userdata.event_bus = MagicMock()
    mocks = _gather_mocks()
    mocks[0].get_player_inventory = AsyncMock(return_value=[])
    if failure == "rollback":

        @asynccontextmanager
        async def transaction():
            yield object()
            raise RuntimeError("commit failed")

        mocks[-1].transaction = transaction
    with context.userdata._bind_authenticated_actor("guest" if guest else "player_1", 1, lambda *_: None):
        if failure == "rollback":
            with pytest.raises(RuntimeError, match="commit failed"):
                await _run(context, mocks, rng_val=11)
        else:
            await _run(context, mocks, rng_val=1)
    events = published_payloads(context.userdata.room)
    assert [e["type"] for e in events] == (["dice_roll"] if failure == "no_gain" else [])
    assert [call.args[0].event_type for call in context.userdata.event_bus.publish.call_args_list] == [
        e["type"] for e in events
    ]
    mocks[0].get_player_inventory.assert_not_awaited()


@pytest.mark.parametrize("failure", ["duplicate", "refusal", "rollback"])
async def test_experiment_duplicate_refusal_and_rollback_emit_no_snapshot(failure):
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from livekit.agents.llm import ToolError
    from test_experimentation import _seams

    from experimentation_tools import _experiment_with_materials_impl

    kwargs, _, mods = _seams(recipes_list=[], known_ids=[], available={"oak_wood": 1})
    mods["queries"].get_player_inventory = AsyncMock(return_value=[])
    mods["exp_db"].has_failed_experiment.return_value = failure == "duplicate"
    if failure == "refusal":
        mods["queries"].get_player_materials.return_value = {}
    if failure == "rollback":

        @asynccontextmanager
        async def transaction():
            yield object()
            raise RuntimeError("commit failed")

        kwargs["db_mod"].transaction = transaction
    context = make_context(room=make_mock_room())
    context.userdata.event_bus = MagicMock()
    if failure == "duplicate":
        await _experiment_with_materials_impl(context, {"oak_wood": 1}, "unknown_output", **kwargs)
    else:
        with pytest.raises(ToolError if failure == "refusal" else RuntimeError):
            await _experiment_with_materials_impl(context, {"oak_wood": 1}, "unknown_output", **kwargs)
    assert published_payloads(context.userdata.room) == []
    context.userdata.event_bus.publish.assert_not_called()
    mods["queries"].get_player_inventory.assert_not_awaited()


@pytest.mark.parametrize("failure", ["refusal", "rollback"])
async def test_craft_refusal_and_rollback_emit_no_snapshot(failure):
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from livekit.agents.llm import ToolError
    from sample_fixtures import make_db_mod
    from test_crafting_tools_projects import _activity, _craft_queries, _materials_mod, _recipe, _recipes_mod

    from crafting_tools import _start_crafting_project_impl

    queries = _craft_queries(recipe_known=failure != "refusal")
    queries.get_player_inventory = AsyncMock(return_value=[])
    db_mod = make_db_mod()[0]
    if failure == "rollback":

        @asynccontextmanager
        async def transaction():
            yield object()
            raise RuntimeError("commit failed")

        db_mod.transaction = transaction
    context = make_context(room=make_mock_room())
    context.userdata.event_bus = MagicMock()
    with pytest.raises(ToolError if failure == "refusal" else RuntimeError):
        await _start_crafting_project_impl(
            context,
            "iron_sword",
            db_mod=db_mod,
            queries_mod=queries,
            mutations_mod=MagicMock(
                consume_player_materials=AsyncMock(), create_async_activity=AsyncMock(return_value="c1")
            ),
            activity_mod=_activity(),
            recipes_mod=_recipes_mod(_recipe()),
            materials_mod=_materials_mod(),
        )
    assert published_payloads(context.userdata.room) == []
    context.userdata.event_bus.publish.assert_not_called()
    queries.get_player_inventory.assert_not_awaited()
