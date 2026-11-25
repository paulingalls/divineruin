from unittest.mock import patch

import pytest
from _thyra_wrath_fixtures import checkpoint, fighter, snapshot
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from livekit.agents.llm import ToolError
from test_patron_engine_thyra_thornwall import GIFT, SEGMENT, battlefield

import db_mutations
from combat_spatial import position
from combat_structures import add_wall


async def test_save_failure_rolls_back_wall_spend_and_publications(world):
    save = db_mutations.save_combat_state

    async def fail_after_save(*args, **kwargs):
        await save(*args, **kwargs)
        raise RuntimeError("injected save failure")

    async with battlefield(world) as call:
        before = await snapshot(world)
        with (
            patch.object(db_mutations, "save_combat_state", side_effect=fail_after_save),
            pytest.raises(RuntimeError, match="injected save failure"),
        ):
            await call("activate", id=GIFT, destination=SEGMENT)
        assert await snapshot(world) == before
        wall = (await call("activate", id=GIFT, destination=SEGMENT))["wall"]
        assert list(world.ctx.userdata.combat_state.spatial["structures"]) == [wall["id"]]
        assert (await row(world, 0))["patron_gifts"] == {GIFT: {"spent": True}}


@pytest.mark.parametrize(
    "selectors,reason",
    [
        ({}, "requires start and end points"),
        ({"destination": SEGMENT["start"]}, "takes start and end points"),
        ({"destination": {"start": SEGMENT["start"]}}, "Error parsing arguments"),
        ({"destination": SEGMENT, "target_id": "companion"}, "Omit entity"),
        ({"destination": SEGMENT, "target_ids": ["companion"]}, "Omit entity"),
        ({"destination": SEGMENT, "condition": "poisoned"}, "Omit entity and condition"),
    ],
)
async def test_invalid_selectors_are_atomic(world, selectors, reason):
    async with battlefield(world) as call:
        before = await snapshot(world)
        with pytest.raises(ToolError, match=reason):
            await call("activate", id=GIFT, **selectors)
        assert await snapshot(world) == before


@pytest.mark.parametrize(
    "start,end,overlap,reason",
    [
        ((10, -16), (10, 15), None, "at most 30 feet"),
        ((31, -10), (31, 10), None, "nearest point"),
        ((0, 0), (0, 10), None, "cannot pass through"),
        ((20, -10), (20, 10), None, "cannot pass through Marauder"),
        ((10, -10), (10, 10), "guest", "cannot pass through Iris"),
        ((10, -10), (10, 10), "companion", "cannot pass through Companion"),
        ((10, 0), (10, 0), None, "horizontal extent"),
    ],
)
async def test_invalid_placement_is_atomic(world, start, end, overlap, reason):
    enemy = fighter("marauder")
    async with battlefield(world, enemy) as call:
        if overlap is not None:
            actor = world.ids[1] if overlap == "guest" else overlap
            world.ctx.userdata.combat_state.spatial["positions"][actor] = {"x": 10, "y": 10, "z": 0}
            await checkpoint(world)
        before = await snapshot(world)
        with pytest.raises(ToolError, match=reason):
            await call(
                "activate",
                id=GIFT,
                destination={
                    "start": {"x": start[0], "y": start[1], "z": 0},
                    "end": {"x": end[0], "y": end[1], "z": 0},
                },
            )
        assert await snapshot(world) == before


async def test_placement_can_cross_an_existing_structure(world):
    async with battlefield(world) as call:
        state = world.ctx.userdata.combat_state
        spatial = state.spatial
        add_wall(state, "stone", "Stone Wall", {"x": 5, "y": 0, "z": 0}, {"x": 15, "y": 0, "z": 0})
        assert position(spatial, "stone") == {"x": 10, "y": 0, "z": 0}
        await checkpoint(world)
        wall = (await call("activate", id=GIFT, destination=SEGMENT))["wall"]
        assert set(state.spatial["structures"]) == {"stone"}
        assert set(world.ctx.userdata.combat_state.spatial["structures"]) == {"stone", wall["id"]}
