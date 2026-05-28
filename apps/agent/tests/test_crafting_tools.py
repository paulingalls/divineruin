"""Tests for the crafting agent tools (story-004, M5.2).

query_available_workspaces (read-only) lists what the player can use at their
location + rental base prices. rent_workspace (mutating) prices by NPC disposition,
debits gold (interim 10sp=1gp), and writes a workspace_rentals row. Failures raise
ToolError (ADR 0002). The _*_impl seams take injected mods (mirrors recipe_tools).
"""

import json
import random
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from crafting_tools import (
    _query_available_workspaces_impl,
    _rent_workspace_impl,
    _resolve_crafting_slot,
    _start_crafting_project_impl,
)

# Real materials catalog the pure pre-flight + allocator run against (slices 1/3/4).
_CATALOG = {
    "iron_ingot": {"id": "iron_ingot", "category": "metal", "tier": 1},
    "steel_ingot": {"id": "steel_ingot", "category": "metal", "tier": 2},
}


def _recipe(**overrides):
    recipe = {
        "id": "iron_sword",
        "name": "Iron Sword",
        "tier": "trained",
        "workspace_required": "forge",
        "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False}],
        "tainted_materials": False,
        "output_item": "item_iron_sword",
        "crafting_dc": 12,
        "async_cycles": 0,
    }
    recipe.update(overrides)
    return recipe


def _craft_queries(
    *, recipe_known=True, tier="expert", accessible=None, materials=None, player_class=None, has_lab=False
):
    mod = MagicMock()
    player = {"player_id": "player_1", "gold": 15}
    if player_class is not None:
        player["class"] = player_class
    mod.get_player = AsyncMock(return_value=player)
    mod.get_player_known_recipe_ids = AsyncMock(return_value={"iron_sword"} if recipe_known else set())
    mod.get_single_skill_advancement = AsyncMock(return_value={"tier": tier})
    mod.get_accessible_workspaces = AsyncMock(return_value=accessible or {"field", "forge"})
    mod.get_player_materials = AsyncMock(return_value=materials or {"iron_ingot": 2})
    # Portable-Lab ownership read (Commit 3): None = not owned; a stack row with quantity.
    mod.get_inventory_item = AsyncMock(return_value={"quantity": 1} if has_lab else None)
    return mod


def _activity(crafting=0, training=0):
    mod = MagicMock()
    mod.lock_player_slot_rows = AsyncMock()
    mod.count_active_by_slot = AsyncMock(return_value={"training": training, "crafting": crafting, "companion": 0})
    return mod


def _recipes_mod(recipe):
    mod = MagicMock()
    mod.get_recipe = AsyncMock(return_value=recipe)
    return mod


def _materials_mod(catalog=None):
    mod = MagicMock()
    mod.get_materials_catalog = AsyncMock(return_value=catalog or _CATALOG)
    return mod


class TestResolveCraftingSlot:
    """Pure mirror of slot_validation.ts validateSlotAvailability crafting branch (ADR 0005)."""

    def test_open_crafting_slot_consumes_crafting(self):
        assert _resolve_crafting_slot({"crafting": 0, "training": 0}, None, False) == ("crafting", None)

    def test_artificer_with_lab_borrows_training_when_crafting_full(self):
        assert _resolve_crafting_slot({"crafting": 1, "training": 0}, "artificer", True) == ("training", None)

    def test_artificer_lab_matched_case_insensitively(self):
        assert _resolve_crafting_slot({"crafting": 1, "training": 0}, "Artificer", True) == ("training", None)

    def test_artificer_with_lab_both_full_refuses(self):
        slot, reason = _resolve_crafting_slot({"crafting": 1, "training": 1}, "artificer", True)
        assert slot is None
        assert reason is not None and "both" in reason.lower()

    def test_non_artificer_full_crafting_refuses(self):
        slot, reason = _resolve_crafting_slot({"crafting": 1, "training": 0}, "warrior", True)
        assert slot is None
        assert reason is not None and "underway" in reason.lower()

    def test_artificer_without_lab_full_crafting_refuses(self):
        slot, reason = _resolve_crafting_slot({"crafting": 1, "training": 0}, "artificer", False)
        assert slot is None
        assert reason is not None and "underway" in reason.lower()


class TestStartCraftingProject:
    async def test_creates_in_progress_activity_with_spec_parameters(self):
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.consume_player_materials = AsyncMock()
        mutations.create_async_activity = AsyncMock(return_value="activity_xyz")
        result = json.loads(
            await _start_crafting_project_impl(
                make_context(),
                "iron_sword",
                db_mod=db_mod,
                queries_mod=_craft_queries(),
                mutations_mod=mutations,
                activity_mod=_activity(),
                recipes_mod=_recipes_mod(_recipe()),
                materials_mod=_materials_mod(),
                rng=random.Random(1),
            )
        )
        assert result["activity_id"] == "activity_xyz"
        # consumed the allocated materials
        mutations.consume_player_materials.assert_awaited_once()
        assert mutations.consume_player_materials.call_args.args[1] == {"iron_ingot": 2}
        # created an in_progress crafting activity with the TS-identical parameters shape
        data = mutations.create_async_activity.call_args.args[1]
        assert data["status"] == "in_progress"
        assert data["activity_type"] == "crafting"
        assert data["parameters"] == {
            "recipe_id": "iron_sword",
            "result_item_id": "item_iron_sword",
            "result_item_name": "Iron Sword",
            "required_materials": ["iron_ingot", "iron_ingot"],
            "dc": 12,
            # Resolution gate inputs captured at creation (story-005): the worker
            # passes these to resolve_crafting so it can re-check workspace access +
            # tainted-Expert. workspace_access is the player's accessible set sorted
            # for deterministic JSONB; crafting_tier/tainted_materials feed the gates.
            "workspace_required": "forge",
            "workspace_access": ["field", "forge"],
            "crafting_tier": "expert",
            "tainted_materials": False,
        }
        # async_cycles=0 -> 900s floor, max 2x
        assert data["duration_min_seconds"] == 900
        assert data["duration_max_seconds"] == 1800

    async def test_unknown_recipe_raises(self):
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError, match="Unknown recipe"):
            await _start_crafting_project_impl(
                make_context(),
                "nope",
                db_mod=db_mod,
                queries_mod=_craft_queries(),
                mutations_mod=MagicMock(),
                activity_mod=_activity(),
                recipes_mod=_recipes_mod(None),
                materials_mod=_materials_mod(),
            )

    async def test_preflight_gate_failure_raises_with_reason(self):
        # Unknown recipe to the player -> Check 1 (Knowledge) fails.
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError, match="not known"):
            await _start_crafting_project_impl(
                make_context(),
                "iron_sword",
                db_mod=db_mod,
                queries_mod=_craft_queries(recipe_known=False),
                mutations_mod=MagicMock(),
                activity_mod=_activity(),
                recipes_mod=_recipes_mod(_recipe()),
                materials_mod=_materials_mod(),
            )

    async def test_slot_full_raises(self):
        # Non-Artificer (no class) with the crafting slot full -> refused by the cap.
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError):
            await _start_crafting_project_impl(
                make_context(),
                "iron_sword",
                db_mod=db_mod,
                queries_mod=_craft_queries(),
                mutations_mod=MagicMock(),
                activity_mod=_activity(crafting=1),
                recipes_mod=_recipes_mod(_recipe()),
                materials_mod=_materials_mod(),
            )

    async def test_normal_craft_stamps_crafting_slot(self):
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.consume_player_materials = AsyncMock()
        mutations.create_async_activity = AsyncMock(return_value="a1")
        await _start_crafting_project_impl(
            make_context(),
            "iron_sword",
            db_mod=db_mod,
            queries_mod=_craft_queries(),
            mutations_mod=mutations,
            activity_mod=_activity(),
            recipes_mod=_recipes_mod(_recipe()),
            materials_mod=_materials_mod(),
            rng=random.Random(1),
        )
        # data.slot stamped so count_active_by_slot (COALESCE) buckets it as crafting (TS parity).
        assert mutations.create_async_activity.call_args.args[1]["slot"] == "crafting"

    async def test_locks_slot_rows_before_counting(self):
        # TS parity (activity_create.ts): lockPlayerSlotRows runs before countActiveBySlot
        # so a concurrent create can't pass the slot check during a worker status flip.
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.consume_player_materials = AsyncMock()
        mutations.create_async_activity = AsyncMock(return_value="a1")
        activity = _activity()
        await _start_crafting_project_impl(
            make_context(),
            "iron_sword",
            db_mod=db_mod,
            queries_mod=_craft_queries(),
            mutations_mod=mutations,
            activity_mod=activity,
            recipes_mod=_recipes_mod(_recipe()),
            materials_mod=_materials_mod(),
            rng=random.Random(1),
        )
        called = [c[0] for c in activity.mock_calls if c[0] in ("lock_player_slot_rows", "count_active_by_slot")]
        assert called == ["lock_player_slot_rows", "count_active_by_slot"]

    async def test_artificer_with_lab_borrows_training_slot_when_crafting_full(self):
        # Artificer + Portable Lab + crafting slot full + training free -> allowed,
        # borrowing the training slot (ADR 0005). The lab also grants the workshop the
        # recipe needs; here the mocked accessible set supplies it.
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.consume_player_materials = AsyncMock()
        mutations.create_async_activity = AsyncMock(return_value="a2")
        queries = _craft_queries(player_class="artificer", has_lab=True, accessible={"field", "workshop"})
        await _start_crafting_project_impl(
            make_context(),
            "iron_sword",
            db_mod=db_mod,
            queries_mod=queries,
            mutations_mod=mutations,
            activity_mod=_activity(crafting=1, training=0),
            recipes_mod=_recipes_mod(_recipe(workspace_required="workshop")),
            materials_mod=_materials_mod(),
            rng=random.Random(1),
        )
        assert mutations.create_async_activity.call_args.args[1]["slot"] == "training"
        # Lab ownership is read once and fed to the workspace grant too.
        assert queries.get_accessible_workspaces.call_args.kwargs.get("has_portable_lab") is True

    async def test_artificer_with_lab_both_slots_full_raises(self):
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError, match=r"[Bb]oth"):
            await _start_crafting_project_impl(
                make_context(),
                "iron_sword",
                db_mod=db_mod,
                queries_mod=_craft_queries(player_class="artificer", has_lab=True),
                mutations_mod=MagicMock(),
                activity_mod=_activity(crafting=1, training=1),
                recipes_mod=_recipes_mod(_recipe()),
                materials_mod=_materials_mod(),
            )

    async def test_off_tier_recipe_raises_toolerror(self):
        # A recipe whose tier is not a canonical RECIPE_TIER (content/migration bug)
        # makes run_preflight Check 2 raise ValueError; start_crafting_project must
        # surface it as ToolError (ADR 0002), not leak the raw exception, and must
        # not consume materials or create an activity.
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.consume_player_materials = AsyncMock()
        mutations.create_async_activity = AsyncMock()
        with pytest.raises(ToolError, match="invalid tier configuration"):
            await _start_crafting_project_impl(
                make_context(),
                "iron_sword",
                db_mod=db_mod,
                queries_mod=_craft_queries(),
                mutations_mod=mutations,
                activity_mod=_activity(),
                recipes_mod=_recipes_mod(_recipe(tier="legendary")),
                materials_mod=_materials_mod(),
            )
        mutations.consume_player_materials.assert_not_awaited()
        mutations.create_async_activity.assert_not_awaited()

    async def test_allocation_fails_after_preflight_passes(self):
        # Two substitutable metal reqs need 4 units; only 3 metal on hand. The greedy
        # pre-flight Check 4 passes (each req sees 3>=2) but allocate_materials cannot
        # cover 4 disjointly -> ToolError, no activity created.
        recipe = _recipe(
            materials=[
                {"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": True},
                {"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": True},
            ]
        )
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.consume_player_materials = AsyncMock()
        mutations.create_async_activity = AsyncMock()
        with pytest.raises(ToolError):
            await _start_crafting_project_impl(
                make_context(),
                "iron_sword",
                db_mod=db_mod,
                queries_mod=_craft_queries(materials={"iron_ingot": 2, "steel_ingot": 1}),
                mutations_mod=mutations,
                activity_mod=_activity(),
                recipes_mod=_recipes_mod(recipe),
                materials_mod=_materials_mod(),
            )
        mutations.create_async_activity.assert_not_awaited()


def _queries(*, accessible=None, disposition="neutral", player=None, present_npc_ids=("grimjaw",)):
    mod = MagicMock()
    mod.get_accessible_workspaces = AsyncMock(return_value=accessible or {"field"})
    mod.get_npc_disposition = AsyncMock(return_value=disposition)
    mod.get_player = AsyncMock(return_value=player or {"player_id": "player_1", "gold": 15})
    # Co-location source (reuses db_queries.get_npcs_at_location): NPCs present at the
    # player's location. Default: the rental NPC is here.
    mod.get_npcs_at_location = AsyncMock(return_value=[{"id": nid} for nid in present_npc_ids])
    return mod


class TestQueryAvailableWorkspaces:
    async def test_returns_accessible_and_rental_prices(self):
        ctx = make_context()
        result = json.loads(
            await _query_available_workspaces_impl(ctx, queries_mod=_queries(accessible={"field", "forge"}))
        )
        assert set(result["accessible"]) == {"field", "forge"}
        # rentable base prices surfaced (workshop 2 / forge 5 / laboratory 10 + combined 12).
        prices = {r["workspace_type"]: r["base_price_sp"] for r in result["rentable"]}
        assert prices == {"workshop": 2, "forge": 5, "laboratory": 10}
        assert result["combined_forge_lab_sp"] == 12


class TestRentWorkspace:
    async def test_neutral_rents_at_full_price_and_debits_gold(self):
        db_mod, _ = make_db_mod()
        queries = _queries(disposition="neutral", player={"player_id": "player_1", "gold": 15})
        mutations = MagicMock()
        mutations.update_player_gold = AsyncMock()
        mutations.create_workspace_rental = AsyncMock(return_value="rent_abc")
        result = json.loads(
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=queries,
                mutations_mod=mutations,
            )
        )
        # forge 5sp at neutral = 5sp = 0.5gp; gold 15 -> 14.5.
        assert result["price_sp"] == pytest.approx(5.0)
        mutations.update_player_gold.assert_awaited_once()
        assert mutations.update_player_gold.call_args.args[1] == pytest.approx(14.5)
        mutations.create_workspace_rental.assert_awaited_once()

    async def test_friendly_gets_discount(self):
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.update_player_gold = AsyncMock()
        mutations.create_workspace_rental = AsyncMock(return_value="rent_x")
        result = json.loads(
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=_queries(disposition="friendly"),
                mutations_mod=mutations,
            )
        )
        assert result["price_sp"] == pytest.approx(4.0)  # 5 * 0.8

    async def test_below_neutral_refuses(self):
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError):
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=_queries(disposition="hostile"),
                mutations_mod=MagicMock(),
            )

    async def test_insufficient_gold_raises(self):
        db_mod, _ = make_db_mod()
        queries = _queries(
            disposition="neutral", player={"player_id": "player_1", "gold": 0}, present_npc_ids=("alchemist",)
        )
        with pytest.raises(ToolError, match="gold"):
            await _rent_workspace_impl(
                make_context(),
                "laboratory",
                "alchemist",
                1,
                db_mod=db_mod,
                queries_mod=queries,
                mutations_mod=MagicMock(),
            )

    async def test_absent_npc_refuses_before_debit(self):
        # Co-location gate (concern bec87679b223): the rental NPC is not at the player's
        # location -> ToolError before any disposition read or gold debit.
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.update_player_gold = AsyncMock()
        mutations.create_workspace_rental = AsyncMock()
        with pytest.raises(ToolError):
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=_queries(present_npc_ids=()),
                mutations_mod=mutations,
            )
        mutations.update_player_gold.assert_not_awaited()
        mutations.create_workspace_rental.assert_not_awaited()

    async def test_rejects_field_workspace(self):
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError):
            await _rent_workspace_impl(
                make_context(),
                "field",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=_queries(),
                mutations_mod=MagicMock(),
            )

    async def test_off_tier_disposition_raises_toolerror(self):
        # A content NPC whose default_disposition is not a canonical tier makes
        # compute_rental_price raise ValueError; rent_workspace must surface it as
        # ToolError (ADR 0002), not leak the raw exception.
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError, match="invalid disposition"):
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=_queries(disposition="grumpy"),
                mutations_mod=MagicMock(),
            )

    async def test_rejects_zero_days(self):
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError):
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                0,
                db_mod=db_mod,
                queries_mod=_queries(),
                mutations_mod=MagicMock(),
            )
