"""Common Bond through registered checks, both crafting producers, and worker settlement."""

import json
import random
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import httpx
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance._server import mint_server_jwt, start_server
from sample_fixtures import CONTENT_ROOT, published_payloads
from test_patron_engine_aelora_craft import BLESSING, assert_creation, create, poll, set_patron

import db
import db_activity_queries
import db_mutations
import db_queries
import experimentation
from check_tools import check
from dispatch_agent import DispatchAgent
from quality_outcomes import get_quality_outcomes
from recipes import get_recipe

CLAUSE = "aelora_common_bond_crafting"
RECEIPT = {"id": CLAUSE, "name": "Common Bond", "bonus": 1}
ARCHETYPES = ("artificer", "bard", "diplomat")
RECIPE = "wooden_club"
EXCLUDED = [("aelora", "rogue"), ("thyra", "artificer")]


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


@pytest.fixture(scope="module")
def crafting_server(migrated_db: str) -> Iterator[dict[str, str]]:
    yield from start_server(migrated_db)


async def setup(
    world: SimpleNamespace, patron: str, archetype: str, *, trained: bool = False, wisdom: int = 10
) -> None:
    await configure(
        world,
        patron,
        archetype,
        location_id=world.ctx.userdata.location_id,
        attributes={"intelligence": 10, "wisdom": wisdom},
        proficiencies=["crafting"] if trained else [],
        divine_favor={"patron": patron, "level": 0, "max": 100},
    )


async def live_check(world: SimpleNamespace, patron: str, archetype: str, skill: str) -> dict:
    await setup(world, patron, archetype, wisdom=14)
    assert not world.ctx.userdata.ally_present_for(world.ids[0])
    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=13)):
        return await game_tools(world.ctx.userdata, check)(
            "check",
            roll={
                "kind": "skill",
                "skill": skill,
                "difficulty": "easy",
                "synergy_context": "none",
                "context_description": "Shape an oak branch",
                "hearing_only": False,
            },
        )


async def common_bond(world: SimpleNamespace, archetype: str) -> None:
    baseline = await live_check(world, "thyra", archetype, "crafting")
    result = await live_check(world, "aelora", archetype, "crafting")
    assert result["roll"] == baseline["roll"] == 13
    for field in ("total", "modifier", "margin"):
        assert result[field] == baseline[field] + 1
    assert baseline["total"] == 15 and "crafting_synergy" not in baseline
    assert result["crafting_synergy"] == RECEIPT
    event = [p for p in published_payloads(world.ctx.userdata.room) if p["type"] == "dice_roll"][-1]
    assert event["total"] == 16


SCENARIOS = {CLAUSE: ("patron_synergy:common_bond_crafting_bonus", common_bond, [(a,) for a in ARCHETYPES])}


@pytest.mark.parametrize("archetype", ARCHETYPES)
async def test_live_crafting(world: SimpleNamespace, archetype: str) -> None:
    await common_bond(world, archetype)


@pytest.mark.parametrize("archetype,skill,total", [("rogue", "crafting", 15), ("artificer", "arcana", 13)])
async def test_live_exclusions(world: SimpleNamespace, archetype: str, skill: str, total: int) -> None:
    result = await live_check(world, "aelora", archetype, skill)
    assert result["total"] == total and "crafting_synergy" not in result


def authored_receipt(archetype: str) -> dict:
    gods = json.loads((CONTENT_ROOT / "content/gods.json").read_text())
    registry = json.loads((CONTENT_ROOT / "content/engine_implementations.json").read_text())
    aelora = next(god for god in gods if god["god_id"] == "aelora")
    row = aelora["layer_4_synergy_matrix"][archetype]
    (implementation,) = (
        clause["implementation_id"]
        for clause in row["clauses"]
        if registry.get(clause.get("implementation_id")) == SCENARIOS[CLAUSE][0]
    )
    return {"id": implementation, "name": row["name"], "bonus": 1}


async def stock(world: SimpleNamespace, *, known: bool) -> None:
    player = world.ids[0]
    catalog = json.loads((CONTENT_ROOT / "content/recipes.json").read_text())
    recipe = next(recipe for recipe in catalog if recipe["id"] == RECIPE)
    for material in recipe["materials"]:
        await db_mutations.add_inventory_item(
            player, material["material_id"], material["quantity"], tainted=False, conn=world.pool
        )
    if known:
        await db_mutations.add_player_known_recipe(player, RECIPE, "test", conn=world.pool)


@pytest.mark.parametrize(
    "patron,archetype,seed,total,eligible",
    [
        ("aelora", "artificer", 7, 12, True),
        ("aelora", "artificer", 15, 8, True),
        *((patron, archetype, 7, 11, False) for patron, archetype in EXCLUDED),
    ],
)
async def test_experiment(
    world: SimpleNamespace, patron: str, archetype: str, seed: int, total: int, eligible: bool
) -> None:
    await setup(world, patron, archetype)
    await stock(world, known=False)
    resolve = experimentation.resolve_experimentation
    with patch.object(
        experimentation,
        "resolve_experimentation",
        side_effect=lambda p, dc, *, rng=None, **kwargs: resolve(p, dc, rng=random.Random(seed), **kwargs),
    ):
        result = await game_tools(world.ctx.userdata, agent=DispatchAgent())(
            "begin_activity",
            activity={
                "kind": "experiment",
                "materials": [{"material_id": "oak_wood", "quantity": 1}],
                "intended_output": "club_wooden",
            },
        )
    success = total >= 12
    assert (result["roll"], result["total"], result["margin"], result["outcome"]) == (
        total - int(eligible),
        total,
        total - 12,
        "success" if success else "failure",
    )
    assert result.get("crafting_synergy") == (RECEIPT if eligible else None)
    learned = await world.pool.fetchval(
        "SELECT learned_via FROM player_known_recipes WHERE player_id=$1 AND recipe_id=$2", world.ids[0], RECIPE
    )
    assert learned == ("experimentation" if success else None)
    assert "oak_wood" not in await db_queries.get_player_materials(world.ids[0])


async def queue(world: SimpleNamespace, request: pytest.FixtureRequest, via: str) -> dict:
    await stock(world, known=True)
    if via == "agent":
        return await create(world, RECIPE)
    server = request.getfixturevalue("crafting_server")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{server['base_url']}/api/activities",
            headers={"Authorization": f"Bearer {mint_server_jwt(player_id=world.ids[0])}"},
            json={"type": "crafting", "parameters": {"recipe_id": RECIPE}},
        )
    assert response.status_code == 200, response.text
    activity = await db_activity_queries.get_activity(response.json()["activity_id"])
    assert activity is not None
    return activity


@pytest.mark.parametrize(
    "via,queued,settled,old_snapshot,seed,tier,roll",
    [
        ("agent", "aelora", "aelora", True, 15, "success", 7),
        ("rest", "aelora", "thyra", True, 15, "partial", 7),
        ("rest", "thyra", "aelora", False, 15, "success", 7),
        ("agent", "aelora", "aelora", False, 7, "success", 11),
        ("agent", "thyra", "aelora", False, 31, "failure", 1),
        ("agent", "aelora", "thyra", True, 15, "partial", 7),
    ],
)
async def test_async_crafting(
    world: SimpleNamespace,
    request: pytest.FixtureRequest,
    via: str,
    queued: str,
    settled: str,
    old_snapshot: bool,
    seed: int,
    tier: str,
    roll: int,
) -> None:
    await setup(world, queued, "artificer", trained=True)
    activity = await queue(world, request, via)
    if old_snapshot:
        await world.pool.execute(
            "UPDATE async_activities SET data=jsonb_set(data, '{parameters,common_bond}', $2::jsonb) WHERE id=$1",
            activity["id"],
            json.dumps(authored_receipt("artificer")),
        )
    else:
        await world.pool.execute(
            "UPDATE async_activities SET data = data #- '{parameters,common_bond}' WHERE id=$1", activity["id"]
        )
    await set_patron(world, settled)

    outcome, prompt, _ = await poll(world, activity, seed)
    ctx = outcome["narrative_context"]
    eligible = settled == "aelora"
    assert (outcome["tier"], ctx["roll"], ctx["total"], ctx["dc"]) == (tier, roll, roll + int(eligible), 8)
    assert ctx.get("common_bond") == (RECEIPT if eligible else None)
    assert ("Common Bond" in prompt) == eligible
    assert outcome["crafted_item_id"] == (None if tier == "failure" else "club_wooden")
    assert "common_bond" not in activity["parameters"]
    if queued == "aelora":
        assert_creation(activity, (675, 1350), "Acknowledged")
    if queued == "aelora" and eligible and seed == 15:
        saved = await db_activity_queries.get_activity(activity["id"])
        assert saved is not None
        assert [option["id"] for option in saved["decision_options"]] == ["keep", "sell"]
        assert saved["decision_options"] == outcome["decision_options"]
        server = request.getfixturevalue("crafting_server")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{server['base_url']}/api/activities/{activity['id']}/decide",
                headers={"Authorization": f"Bearer {mint_server_jwt(player_id=world.ids[0])}"},
                json={"decision_id": "keep"},
            )
        assert response.status_code == 200, response.text
        assert (
            await world.pool.fetchval(
                "SELECT (data->>'quantity')::int FROM player_inventory WHERE player_id=$1 AND item_id='club_wooden'",
                world.ids[0],
            )
            == 1
        )
        table = await get_quality_outcomes("weapon")
        assert table is not None
        rng = random.Random(seed)
        rng.randint(1, 20)
        rng.random()
        assert outcome["bonus_property"] == rng.choice(table["bonus_properties"])
        assert ctx["craft_blessing"] == {**BLESSING, "tier": "Acknowledged"}
        assert "Craft Blessing" in prompt
    else:
        assert outcome["bonus_property"] is None and "Craft Blessing" not in prompt


async def test_async_zero_value_craft_offers_only_keep(world: SimpleNamespace) -> None:
    await setup(world, "none", "artificer", trained=True)
    player = world.ids[0]
    recipe_id = "anti_hollow_blade"
    recipe = await get_recipe(recipe_id)
    assert recipe is not None
    await world.pool.execute(
        "INSERT INTO skill_advancement (player_id, skill_id, tier) VALUES ($1, 'crafting', 'expert')", player
    )
    await db_mutations.create_workspace_rental(
        player, world.ctx.userdata.location_id, "laboratory", "standing", None, conn=world.pool
    )
    await db_mutations.add_player_known_recipe(player, recipe_id, "test", conn=world.pool)
    for material in recipe["materials"]:
        material_id = material["material_id"]
        await db_mutations.add_inventory_item(
            player, material_id, material["quantity"], tainted=material_id == "wrack_core", conn=world.pool
        )
    activity = await create(world, recipe_id)
    outcome, _, _ = await poll(world, activity, 5)
    assert (outcome["tier"], outcome["crafted_item_id"]) == ("success", "hollow_edge_blade")
    saved = await db_activity_queries.get_activity(activity["id"])
    assert saved is not None
    assert [option["id"] for option in saved["decision_options"]] == ["keep"]
    assert saved["decision_options"] == outcome["decision_options"]
