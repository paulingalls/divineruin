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

CLAUSE = "aelora_common_bond_crafting"
RECEIPT = {"id": CLAUSE, "name": "Common Bond", "bonus": 1}
ARCHETYPES = ("artificer", "bard", "diplomat")
RECIPE = "wooden_club"
EXCLUDED = [("aelora", "rogue"), ("thyra", "artificer"), ("none", "artificer"), (None, "artificer")]


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


@pytest.fixture(scope="module")
def crafting_server(migrated_db: str) -> Iterator[dict[str, str]]:
    yield from start_server(migrated_db)


async def setup(world: SimpleNamespace, patron: str | None, archetype: str, *, trained: bool = False) -> None:
    await configure(
        world,
        patron or "none",
        archetype,
        location_id=world.ctx.userdata.location_id,
        attributes={"intelligence": 10},
        proficiencies=["crafting"] if trained else [],
        divine_favor={"patron": patron, "level": 0, "max": 100} if patron else None,
    )


async def live_check(world: SimpleNamespace, patron: str, archetype: str, skill: str) -> dict:
    await setup(world, patron, archetype)
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
    assert baseline["total"] == 13 and "crafting_synergy" not in baseline
    assert result["crafting_synergy"] == RECEIPT
    event = [p for p in published_payloads(world.ctx.userdata.room) if p["type"] == "dice_roll"][-1]
    assert event["total"] == 14


SCENARIOS = {CLAUSE: ("patron_synergy:common_bond_crafting_bonus", common_bond, [(a,) for a in ARCHETYPES])}


@pytest.mark.parametrize("archetype", ARCHETYPES)
async def test_live_crafting(world: SimpleNamespace, archetype: str) -> None:
    await common_bond(world, archetype)


@pytest.mark.parametrize("archetype,skill", [("rogue", "crafting"), ("artificer", "arcana")])
async def test_live_exclusions(world: SimpleNamespace, archetype: str, skill: str) -> None:
    result = await live_check(world, "aelora", archetype, skill)
    assert result["total"] == 13 and "crafting_synergy" not in result


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
        *((patron, archetype, 7, 11, False) for patron, archetype in EXCLUDED[:2]),
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
        side_effect=lambda p, dc, **_: resolve(p, dc, rng=random.Random(seed)),
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
    "via,seed,legacy,tier,roll",
    [
        ("agent", 15, False, "success", 7),
        ("rest", 15, False, "success", 7),
        ("agent", 7, False, "success", 11),
        ("agent", 31, False, "failure", 1),
        ("agent", 15, True, "partial", 7),
    ],
)
async def test_async_crafting(
    world: SimpleNamespace, request: pytest.FixtureRequest, via: str, seed: int, legacy: bool, tier: str, roll: int
) -> None:
    await setup(world, "aelora", "artificer", trained=True)
    activity = await queue(world, request, via)
    if legacy:
        await world.pool.execute(
            "UPDATE async_activities SET data = data #- '{parameters,common_bond}' WHERE id=$1", activity["id"]
        )
    else:
        await set_patron(world, "thyra")

    outcome, prompt, _ = await poll(world, activity, seed)
    ctx = outcome["narrative_context"]
    assert (outcome["tier"], ctx["roll"], ctx["total"], ctx["dc"]) == (tier, roll, roll + int(not legacy), 8)
    assert ctx.get("common_bond") == (None if legacy else RECEIPT)
    assert ("Common Bond" in prompt) is not legacy
    assert outcome["crafted_item_id"] == (None if tier == "failure" else "club_wooden")
    assert_creation(activity, (675, 1350), "Acknowledged")
    if not legacy:
        assert activity["parameters"]["common_bond"] == authored_receipt("artificer")
    if seed == 15 and not legacy:
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


@pytest.mark.parametrize("via", ["agent", "rest"])
@pytest.mark.parametrize("patron,archetype", EXCLUDED)
async def test_async_creation_exclusions(
    world: SimpleNamespace, request: pytest.FixtureRequest, via: str, patron: str | None, archetype: str
) -> None:
    await setup(world, patron, archetype, trained=True)
    activity = await queue(world, request, via)
    assert "common_bond" not in activity["parameters"]
    if patron == "aelora":
        assert activity["parameters"]["craft_blessing"] == {**BLESSING, "tier": "Acknowledged"}
