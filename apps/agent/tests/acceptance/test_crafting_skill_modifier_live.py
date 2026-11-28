"""Settlement and experimentation use the live Arcana modifier."""

import json
import random
from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance.test_common_bond_crafting import RECIPE, stock
from dice_seeds import seed_for_d20
from test_aelora_gift import _live_party
from test_patron_engine_aelora_craft import create, poll

import db
import db_queries
import experimentation
import experimentation_db
from check_tools import check
from dispatch_agent import DispatchAgent

EXHAUSTED = {"type": "exhausted", "duration": None, "source": "march", "stacks": 2}
INSPIRED = {"type": "inspired", "duration": 2, "source": "ally"}


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


async def set_conditions(world: SimpleNamespace, conditions: list[dict]) -> None:
    await world.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{conditions}', $2::jsonb) WHERE player_id=$1",
        world.ids[0],
        json.dumps(conditions),
    )


async def survey(world: SimpleNamespace) -> None:
    await configure(
        world, "none", "artificer", level=3, attributes={"intelligence": 14}, proficiencies=["arcana", "crafting"]
    )
    assert not world.ctx.userdata.ally_present_for(world.ids[0])


async def live_arcana(world: SimpleNamespace, *, inspired: bool) -> int:
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=13)),
        patch("condition_bonus.dice_roll", return_value=SimpleNamespace(total=2)),
    ):
        result = await game_tools(world.ctx.userdata, check)(
            "check",
            roll={
                "kind": "skill",
                "skill": "arcana",
                "difficulty": "easy",
                "synergy_context": "none",
                "context_description": "Examine the wood grain",
                "hearing_only": False,
            },
        )
    if inspired:
        assert all(c["type"] != "inspired" for c in (await row(world, 0))["conditions"])
    return result["modifier"] - (2 if inspired else 0)


@pytest.mark.parametrize(
    "conditions,roll,modifier,tier",
    [([], 2, 6, "success"), ([EXHAUSTED, INSPIRED], 3, 4, "partial")],
)
async def test_queued_crafting(
    world: SimpleNamespace, conditions: list[dict], roll: int, modifier: int, tier: str
) -> None:
    await survey(world)
    await stock(world, known=True)
    activity = await create(world, RECIPE)
    await set_conditions(world, conditions)
    outcome, _, _ = await poll(world, activity, seed_for_d20(roll))
    ctx = outcome["narrative_context"]
    assert (ctx["roll"], ctx["total"], outcome["tier"]) == (roll, roll + modifier, tier)
    assert (await row(world, 0))["conditions"] == conditions
    assert ctx["total"] - ctx["roll"] == await live_arcana(world, inspired=INSPIRED in conditions)


@pytest.mark.parametrize(
    "conditions,allied,roll,modifier,expected",
    # A live ally removes the Unbound-alone +1, exactly as on the live check.
    [([], False, 6, 6, "success"), ([EXHAUSTED, INSPIRED], False, 7, 4, "failure"), ([], True, 6, 5, "failure")],
)
async def test_experiment(
    world: SimpleNamespace, conditions: list[dict], allied: bool, roll: int, modifier: int, expected: str
) -> None:
    await survey(world)
    if allied:
        _live_party(world.ctx.userdata, *world.ids)
        assert world.ctx.userdata.allies_present_for(world.ids[0]) == 1
    await set_conditions(world, conditions)
    await stock(world, known=False)
    resolve = experimentation.resolve_experimentation
    with patch.object(
        experimentation,
        "resolve_experimentation",
        side_effect=lambda player, dc, *, rng=None, **kwargs: resolve(
            player, dc, rng=random.Random(seed_for_d20(roll)), **kwargs
        ),
    ):
        result = await game_tools(world.ctx.userdata, agent=DispatchAgent())(
            "begin_activity",
            activity={
                "kind": "experiment",
                "materials": [{"material_id": "oak_wood", "quantity": 1}],
                "intended_output": "club_wooden",
            },
        )
    assert (result["roll"], result["total"], result["margin"], result["outcome"]) == (
        roll,
        roll + modifier,
        roll + modifier - 12,
        expected,
    )
    assert (await row(world, 0))["conditions"] == conditions
    assert result["total"] - result["roll"] == await live_arcana(world, inspired=INSPIRED in conditions)
    assert result["dc"] == 12
    assert result["learned_recipe"] == (RECIPE if expected == "success" else None)
    if expected == "failure":
        assert result["retryable"] is True
        assert not await experimentation_db.has_failed_experiment(
            world.ids[0], "club_wooden", experimentation.make_combination_key({"oak_wood": 1}), conn=world.pool
        )
    assert "oak_wood" not in await db_queries.get_player_materials(world.ids[0])
    learned = await db_queries.get_player_known_recipe_ids(world.ids[0])
    assert (RECIPE in learned) == (expected == "success")
