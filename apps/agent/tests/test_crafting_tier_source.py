import ast
import random
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import crafting_tools
import recipe_tools
import repair_item

SLOTS = {
    "untrained": {"max_recipe_tier": "basic", "known_recipe_slots": 3},
    "trained": {"max_recipe_tier": "trained", "known_recipe_slots": 8},
    "expert": {"max_recipe_tier": "expert", "known_recipe_slots": 15},
    "master": {"max_recipe_tier": "master", "known_recipe_slots": None},
}
SITES = ("start-project", "learn-recipe", "repair-item")


def _queries(player: dict, row_tier: str) -> MagicMock:
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player)
    queries.get_single_skill_advancement = AsyncMock(
        return_value={"tier": row_tier, "use_counter": 0, "narrative_moment_ready": False}
    )
    return queries


def _start_project_case(player: dict, row_tier: str, required_tier: str):
    db_mod, _ = make_db_mod()
    queries = _queries(player, row_tier)
    queries.get_inventory_item = AsyncMock(return_value=None)
    queries.get_player_known_recipe_ids = AsyncMock(return_value={"test_recipe"})
    queries.get_accessible_workspaces = AsyncMock(return_value={"forge"})
    queries.get_player_materials = AsyncMock(return_value={"iron_ingot": 2})

    recipe = {
        "id": "test_recipe",
        "name": "Test Recipe",
        "tier": required_tier,
        "workspace_required": "forge",
        "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False}],
        "tainted_materials": False,
        "output_item": "test_item",
        "crafting_dc": 12,
        "async_cycles": 0,
    }
    recipes = MagicMock()
    recipes.get_recipe = AsyncMock(return_value=recipe)
    materials = MagicMock()
    materials.get_materials_catalog = AsyncMock(
        return_value={"iron_ingot": {"id": "iron_ingot", "category": "metal", "tier": 1}}
    )
    activity = MagicMock()
    activity.lock_player_slot_rows = AsyncMock()
    activity.count_active_by_slot = AsyncMock(return_value={"training": 0, "crafting": 0, "companion": 0})
    mutations = MagicMock()
    mutations.consume_player_materials = AsyncMock()
    mutations.create_async_activity = AsyncMock(return_value="activity_1")

    async def invoke():
        await crafting_tools._start_crafting_project_impl(
            make_context(),
            "test_recipe",
            db_mod=db_mod,
            queries_mod=queries,
            mutations_mod=mutations,
            activity_mod=activity,
            recipes_mod=recipes,
            materials_mod=materials,
            rng=random.Random(1),
        )
        data = mutations.create_async_activity.await_args.args[1]
        return data["parameters"]["crafting_tier"]

    return invoke, (mutations.consume_player_materials, mutations.create_async_activity)


def _learn_recipe_case(player: dict, row_tier: str, required_tier: str):
    db_mod, _ = make_db_mod()
    queries = _queries(player, row_tier)
    queries.count_player_known_recipes = AsyncMock(return_value=0)
    recipes = MagicMock()
    recipes.get_recipe = AsyncMock(return_value={"id": "test_recipe", "name": "Test Recipe", "tier": required_tier})
    slots = MagicMock()
    slots.get_recipe_slots = AsyncMock(return_value=SLOTS)
    mutations = MagicMock()
    mutations.add_player_known_recipe = AsyncMock(return_value=True)

    async def invoke():
        await recipe_tools._learn_recipe_impl(
            make_context(),
            "test_recipe",
            "discovery",
            db_mod=db_mod,
            queries_mod=queries,
            mutations_mod=mutations,
            recipes_mod=recipes,
            slots_mod=slots,
        )

    return invoke, (mutations.add_player_known_recipe,)


def _repair_item_case(player: dict, row_tier: str, required_tier: str):
    db_mod, _ = make_db_mod()
    queries = _queries(player, row_tier)
    queries.get_npcs_at_location = AsyncMock(return_value=[{"id": "blacksmith"}])
    queries.get_player_inventory = AsyncMock(
        return_value=[
            {
                "id": "test_item",
                "name": "Test Item",
                "rarity": "common",
                "durability_tier": "reinforced" if required_tier == "expert" else "standard",
                "slot_info": {"current_hits": 1},
            }
        ]
    )
    queries.get_npc_disposition = AsyncMock(return_value="neutral")
    content = MagicMock()
    content.get_npc = AsyncMock(return_value=None)
    pricing = MagicMock()
    pricing.get_economy_pricing = AsyncMock(
        return_value={
            "repair_cost_sp": {"common": 2},
            "disposition_multipliers": {},
            "silver_per_gold": 10,
        }
    )
    mutations = MagicMock()
    mutations.update_player_gold = AsyncMock()
    inventory_mutations = MagicMock()
    inventory_mutations.update_item_durability = AsyncMock()

    async def invoke():
        await repair_item._repair_item_impl(
            make_context(),
            "test_item",
            "blacksmith",
            db_mod=db_mod,
            queries_mod=queries,
            mutations_mod=mutations,
            inv_mutations_mod=inventory_mutations,
            content_mod=content,
            pricing_mod=pricing,
        )

    return invoke, (inventory_mutations.update_item_durability, mutations.update_player_gold)


def _case(site: str, player: dict, row_tier: str, required_tier: str):
    factories = {
        "start-project": _start_project_case,
        "learn-recipe": _learn_recipe_case,
        "repair-item": _repair_item_case,
    }
    return factories[site](player, row_tier, required_tier)


@pytest.mark.parametrize("site", SITES)
async def test_proficient_no_row_reads_trained_at_each_crafting_gate(site):
    player = {"player_id": "player_1", "gold": 15, "proficiencies": ["crafting"]}
    invoke, writes = _case(site, player, "untrained", "trained")

    observed_tier = await invoke()

    if site == "start-project":
        assert observed_tier == "trained"
    for write in writes:
        write.assert_awaited_once()


@pytest.mark.parametrize("site", SITES)
async def test_expert_row_wins_at_each_crafting_gate(site):
    player = {"player_id": "player_1", "gold": 15, "skill_tiers": {"crafting": "expert"}}
    invoke, writes = _case(site, player, "expert", "expert")

    observed_tier = await invoke()

    if site == "start-project":
        assert observed_tier == "expert"
    for write in writes:
        write.assert_awaited_once()


@pytest.mark.parametrize("site", SITES)
async def test_nonproficient_no_row_is_refused_at_each_crafting_gate(site):
    player = {"player_id": "player_1", "gold": 15}
    invoke, writes = _case(site, player, "untrained", "trained")

    with pytest.raises(ToolError, match="untrained"):
        await invoke()
    for write in writes:
        write.assert_not_awaited()


# Both skill_advancement read accessors, because the split this story closes is the TABLE,
# not one function: a fourth gate reintroduces it through either.
ACCESSORS = {"get_single_skill_advancement", "get_skill_advancement"}

# skill_persistence is not a split source: it seeds the row read with the hydrated tier
# (default_tier=rules_engine._get_skill_tier, story-056), so a proficient player with no row
# advances from `trained`.
KNOWN_READERS = {
    ("skill_persistence.py", "apply_skill_use_with_persistence", "get_single_skill_advancement"),
}


class _AccessorCallVisitor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.functions = []
        self.calls = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._visit_function(node)

    def visit_Call(self, node):
        # `db_queries.get_x(...)` AND a bare `get_x(...)` off `from db_queries import get_x` —
        # a live import style here (companion_relationship_queries.py:19), so an attribute-only
        # walk would wave the next gate through.
        func = node.func
        called = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        if called in ACCESSORS:
            self.calls.append((self.path.as_posix(), self.functions[-1] if self.functions else None, called))
        self.generic_visit(node)


def test_only_known_readers_call_the_skill_advancement_accessors():
    agent_root = Path(__file__).parents[1]
    calls = []
    for path in agent_root.rglob("*.py"):
        relative = path.relative_to(agent_root)
        if "tests" in relative.parts or ".venv" in relative.parts:
            continue
        visitor = _AccessorCallVisitor(relative)
        visitor.visit(ast.parse(path.read_text(), filename=str(path)))
        calls.extend(visitor.calls)

    assert set(calls) == KNOWN_READERS
    assert len(calls) == len(KNOWN_READERS)
