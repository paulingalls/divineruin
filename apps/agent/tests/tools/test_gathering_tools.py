"""Tests for the gather mode of the `check` verb (M4.6c / story-003).

`_check_gather_impl` (folded into check via mode="gather") reads the player's current location,
rolls the gating skill, drives the pure gathering engine, grants materials, consumes a fixed
gathering_node on a rich find, and emits a DICE_ROLL. Drives the impl directly with mocked db
seams + a fixed rng; the dispatch wiring on `check` is covered at the bottom. Mirrors
test_social_tools.py.
"""

import json
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import FixedRng, mock_txn, published_events

import event_types as E
from bg_event_handlers import handle_events
from check_tools import VALID_CHECK_MODES, _check_impl
from gathering_tools import _check_gather_impl
from session_data import SessionData
from tools._helpers import SAMPLE_PLAYER, _make_context

_WILDERNESS = {
    "id": "greyvale_wilderness_north",
    "region": "greyvale",
    "resource_table": {
        "common": ["medicinal_herb", "oak_wood"],
        "uncommon": ["iron_ore"],
        "rare": [],
    },
}
_DUNGEON = {"id": "greyvale_ruins_entrance", "region": "greyvale"}  # no resource_table
_NODE = {
    "id": "n1",
    "location_id": "greyvale_wilderness_north",
    "node_type": "herb_garden",
    "resource_type": "sageroot",
    "quantity": 3,
    "discovered": False,
    "respawn_days": 2,
}

_PERSISTENT_NODE = {
    "id": "pool1",
    "location_id": "greyvale_wilderness_north",
    "node_type": "hollow_residue_pool",
    "resource_type": "drift_residue",
    "quantity": 4,
    "discovered": False,
    "respawn_days": -1,
}

_EXPERT = {**SAMPLE_PLAYER, "skill_tiers": {"survival": "expert", "nature": "expert", "arcana": "expert"}}


def _gather_mocks(player=SAMPLE_PLAYER, location=_WILDERNESS, nodes=None):
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player)
    mutations = MagicMock()
    mutations.add_inventory_item = AsyncMock()
    content = MagicMock()
    content.get_location = AsyncMock(return_value=location)
    content.get_gathering_nodes_at_location = AsyncMock(return_value=list(nodes or []))
    gather_mutations = MagicMock()
    gather_mutations.mark_node_discovered = AsyncMock()
    gather_mutations.deplete_node_quantity = AsyncMock()
    db_mod = MagicMock()
    db_mod.transaction = lambda: mock_txn(MagicMock())
    return queries, mutations, content, gather_mutations, db_mod


def _ctx_with_bus(location_id="greyvale_wilderness_north"):
    ctx = _make_context(location_id=location_id)
    ctx.userdata.event_bus = MagicMock()
    return ctx


async def _run(ctx, mocks, *, material_type="", rng_val=11):
    queries, mutations, content, gather_mutations, db_mod = mocks
    return json.loads(
        await _check_gather_impl(
            ctx,
            material_type,
            queries=queries,
            mutations=mutations,
            content=content,
            gather_mutations=gather_mutations,
            db_mod=db_mod,
            rng=FixedRng(rng_val),
        )
    )


class TestAmbientForage:
    @pytest.mark.asyncio
    async def test_success_grants_materials_and_emits_dice_roll(self):
        mocks = _gather_mocks()
        ctx = _ctx_with_bus()
        result = await _run(ctx, mocks, rng_val=20)
        assert result["outcome"] == "success"
        assert result["materials"]  # non-empty
        mocks[1].add_inventory_item.assert_awaited()  # mutations
        dice = next(e for e in published_events(ctx) if e.event_type == E.DICE_ROLL)
        assert dice.payload["roll_type"] == "gathering_check"
        assert dice.payload["skill"] == "survival"

    @pytest.mark.asyncio
    async def test_failed_roll_grants_nothing(self):
        mocks = _gather_mocks()  # untrained survival, roll 1 -> nothing
        ctx = _ctx_with_bus()
        result = await _run(ctx, mocks, rng_val=1)
        assert result["outcome"] == "failure"
        assert result["materials"] == []
        mocks[1].add_inventory_item.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_material_type_routes_skill(self):
        mocks = _gather_mocks(player=_EXPERT)
        ctx = _ctx_with_bus()
        result = await _run(ctx, mocks, material_type="herbs", rng_val=20)
        assert result["skill"] == "nature"


class TestNodeConsumer:
    @pytest.mark.asyncio
    async def test_rich_find_discovers_and_depletes_node(self):
        mocks = _gather_mocks(player=_EXPERT, nodes=[_NODE])
        ctx = _ctx_with_bus()
        result = await _run(ctx, mocks, rng_val=20)  # expert + nat20 vs dc10 -> rich_find
        assert result["discovery"] is True
        assert result["node_revealed"] == "n1"
        mocks[3].mark_node_discovered.assert_awaited_once_with("n1", conn=ANY)
        mocks[3].deplete_node_quantity.assert_awaited_once()
        # node resource granted
        granted = [c.args[1] for c in mocks[1].add_inventory_item.await_args_list]
        assert "sageroot" in granted

    @pytest.mark.asyncio
    async def test_dungeon_yields_only_via_node_on_rich_find(self):
        mocks = _gather_mocks(player=_EXPERT, location=_DUNGEON, nodes=[_NODE])
        ctx = _ctx_with_bus(location_id="greyvale_ruins_entrance")
        result = await _run(ctx, mocks, rng_val=20)
        assert result["node_revealed"] == "n1"
        granted = [c.args[1] for c in mocks[1].add_inventory_item.await_args_list]
        assert granted == ["sageroot"]  # no ambient materials at a dungeon

    @pytest.mark.asyncio
    async def test_rich_find_matches_node_to_rolled_skill(self):
        # location has an ore vein (survival) listed first + an herb garden (nature); foraging for
        # herbs must surface the herb garden, not the listed-first ore vein.
        ore = {**_NODE, "id": "ore1", "node_type": "ore_vein", "resource_type": "iron_ore"}
        mocks = _gather_mocks(player=_EXPERT, nodes=[ore, _NODE])
        ctx = _ctx_with_bus()
        result = await _run(ctx, mocks, material_type="herbs", rng_val=20)
        assert result["node_revealed"] == "n1"  # the herb garden, not ore1
        mocks[3].mark_node_discovered.assert_awaited_once_with("n1", conn=ANY)
        granted = [c.args[1] for c in mocks[1].add_inventory_item.await_args_list]
        assert "sageroot" in granted  # the herb-garden node resource, not the ore vein's

    @pytest.mark.asyncio
    async def test_persistent_node_is_discovered_but_never_depleted(self):
        # A respawn_days == -1 node is infinite (the hollow residue pool): a rich find reveals it
        # and grants its resource, but must NOT deplete quantity — nothing respawns it, so a
        # depletion would drain it to 0 permanently.
        mocks = _gather_mocks(player=_EXPERT, nodes=[_PERSISTENT_NODE])
        ctx = _ctx_with_bus()
        result = await _run(ctx, mocks, material_type="arcane_components", rng_val=20)  # arcana rich_find
        assert result["node_revealed"] == "pool1"
        mocks[3].mark_node_discovered.assert_awaited_once_with("pool1", conn=ANY)
        mocks[3].deplete_node_quantity.assert_not_awaited()
        granted = [c.args[1] for c in mocks[1].add_inventory_item.await_args_list]
        assert "drift_residue" in granted  # still harvestable

    @pytest.mark.asyncio
    async def test_non_rich_success_does_not_touch_node(self):
        mocks = _gather_mocks(player=SAMPLE_PLAYER, nodes=[_NODE])  # untrained -> at most success
        ctx = _ctx_with_bus()
        result = await _run(ctx, mocks, rng_val=11)
        assert result["discovery"] is False
        assert result["node_revealed"] is None
        mocks[3].mark_node_discovered.assert_not_awaited()


class TestGuards:
    @pytest.mark.asyncio
    async def test_no_resource_table_and_no_nodes_raises(self):
        mocks = _gather_mocks(location=_DUNGEON, nodes=[])
        with pytest.raises(ToolError, match="forage"):
            await _run(_ctx_with_bus(location_id="greyvale_ruins_entrance"), mocks, rng_val=11)

    @pytest.mark.asyncio
    async def test_unknown_material_category_raises(self):
        mocks = _gather_mocks()
        with pytest.raises(ToolError, match="material type"):
            await _run(_ctx_with_bus(), mocks, material_type="antimatter", rng_val=11)


class TestNodeRevealSignal:
    @pytest.mark.asyncio
    async def test_first_reveal_emits_hidden_revealed(self):
        """Undiscovered node + rich find should emit HIDDEN_REVEALED alongside DICE_ROLL."""
        mocks = _gather_mocks(player=_EXPERT, nodes=[_NODE])
        ctx = _ctx_with_bus()
        await _run(ctx, mocks, rng_val=20)  # expert + nat20 -> rich_find
        events = published_events(ctx)
        dice_roll = next(e for e in events if e.event_type == E.DICE_ROLL)
        assert dice_roll is not None
        hidden = next((e for e in events if e.event_type == E.HIDDEN_REVEALED), None)
        assert hidden is not None
        assert hidden.payload["element_id"] == "n1"
        assert hidden.payload["skill"] == "survival"

    @pytest.mark.asyncio
    async def test_already_discovered_omits_hidden_revealed(self):
        """Already-discovered node should NOT emit HIDDEN_REVEALED (first-reveal-only gate)."""
        discovered_node = {**_NODE, "discovered": True}
        mocks = _gather_mocks(player=_EXPERT, nodes=[discovered_node])
        ctx = _ctx_with_bus()
        await _run(ctx, mocks, rng_val=20)  # expert + nat20 -> rich_find
        events = published_events(ctx)
        dice_roll = next(e for e in events if e.event_type == E.DICE_ROLL)
        assert dice_roll is not None
        hidden = next((e for e in events if e.event_type == E.HIDDEN_REVEALED), None)
        assert hidden is None  # no HIDDEN_REVEALED for already-discovered

    @pytest.mark.asyncio
    async def test_non_rich_success_omits_hidden_revealed(self):
        """Non-rich success should emit only DICE_ROLL, no HIDDEN_REVEALED."""
        mocks = _gather_mocks(player=SAMPLE_PLAYER, nodes=[_NODE])  # untrained -> no rich find
        ctx = _ctx_with_bus()
        await _run(ctx, mocks, rng_val=11)
        events = published_events(ctx)
        dice_roll = next(e for e in events if e.event_type == E.DICE_ROLL)
        assert dice_roll is not None
        hidden = next((e for e in events if e.event_type == E.HIDDEN_REVEALED), None)
        assert hidden is None  # no HIDDEN_REVEALED for non-rich

    @pytest.mark.asyncio
    async def test_emitted_event_feeds_real_handler_roundtrip(self):
        """AC#3: the exact event the gather path emits, fed through the REAL bg_event_handlers
        handler, must trigger a warm rebuild AND land the node id in recently_revealed_element_ids
        — pinning the emit-side payload against the consume-side contract in one test (mirrors
        check_discovery.py's mode=discover reveal path)."""
        mocks = _gather_mocks(player=_EXPERT, nodes=[_NODE])
        ctx = _ctx_with_bus()
        await _run(ctx, mocks, rng_val=20)  # expert + nat20 -> rich_find
        hidden = next(e for e in published_events(ctx) if e.event_type == E.HIDDEN_REVEALED)

        sd = SessionData(player_id="player_1", location_id="greyvale_wilderness_north")
        needs_rebuild, _ = handle_events([hidden], sd, [], False, {}, [])

        assert needs_rebuild is True
        assert sd.recently_revealed_element_ids == ["n1"]


class TestCheckModeRegistration:
    def test_gather_is_a_valid_check_mode(self):
        assert "gather" in VALID_CHECK_MODES

    @pytest.mark.asyncio
    async def test_check_dispatches_gather_mode(self):
        # Proves _check_impl routes mode="gather" to _check_gather_impl. Uses a dungeon (no
        # resource_table) with no nodes so the impl fail-louds at its guard BEFORE the DB
        # transaction — keeping this a pure routing assertion (no db_mod injection / real conn).
        queries, mutations, content, _gm, _db = _gather_mocks(location=_DUNGEON, nodes=[])
        ctx = _ctx_with_bus(location_id="greyvale_ruins_entrance")
        with pytest.raises(ToolError, match="forage"):
            await _check_impl(ctx, "gather", target="", queries=queries, mutations=mutations, content=content)
