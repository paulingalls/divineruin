"""Aelora's craft snapshot through registered creation and worker polling."""

import json
import random
from dataclasses import asdict
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from livekit.agents.llm import ToolError

import async_worker as worker
import db_activity_queries
import db_mutations
import recipes
from activity_templates import build_narration_prompt
from dialogue_parser import Segment
from dispatch_agent import DispatchAgent
from quality_outcomes import get_quality_outcomes

BLESSING = {"id": "aelora_craft_blessing", "name": "Craft Blessing", "patron": "aelora"}
TIERS = [
    (39, 100, "Acknowledged"),
    (40, 100, "Devoted"),
    (74, 100, "Devoted"),
    (75, 100, "Exalted"),
    (24, 61, "Acknowledged"),
    (25, 61, "Devoted"),
    (45, 61, "Devoted"),
    (46, 61, "Exalted"),
]


async def prepare(world, recipe_id: str, patron: str, level: int, maximum: int) -> None:
    await configure(
        world,
        patron,
        "warrior",
        divine_favor={"patron": patron, "level": level, "max": maximum},
        attributes={"intelligence": 10},
        proficiencies=["crafting"],
    )
    pid = world.ids[0]
    recipe = await recipes.get_recipe(recipe_id)
    assert recipe is not None
    await db_mutations.add_player_known_recipe(pid, recipe_id, "test", conn=world.pool)
    for material in recipe["materials"]:
        await db_mutations.add_inventory_item(
            pid, material["material_id"], material["quantity"], tainted=False, conn=world.pool
        )
    if recipe["workspace_required"] == "forge":
        await db_mutations.create_workspace_rental(
            pid, world.ctx.userdata.location_id, "forge", "standing", None, conn=world.pool
        )


async def create(world, recipe_id: str) -> dict:
    call = game_tools(world.ctx.userdata, agent=DispatchAgent())
    result = await call("begin_activity", activity={"kind": "crafting", "recipe_id": recipe_id})
    row = await db_activity_queries.get_activity(result["activity_id"])
    assert row is not None
    return row


def assert_creation(row: dict, bounds: tuple[int, int], tier: str | None) -> None:
    assert (row["duration_min_seconds"], row["duration_max_seconds"]) == bounds
    wait = datetime.fromisoformat(row["resolve_at"]) - datetime.fromisoformat(row["start_time"])
    assert bounds[0] <= wait.total_seconds() <= bounds[1]
    if tier is None:
        assert "craft_blessing" not in row["parameters"]
    else:
        assert row["parameters"]["craft_blessing"] == {**BLESSING, "tier": tier}


async def poll(world, row: dict, seed: int) -> tuple[dict, str, random.Random]:
    activity_id = row["id"]
    await world.pool.execute(
        "UPDATE async_activities SET data=jsonb_set(data, '{resolve_at}', to_jsonb($2::text)) WHERE id=$1",
        activity_id,
        "2025-01-01T00:00:00Z",
    )
    rng = random.Random(seed)
    original_due = db_activity_queries.get_due_activities
    original_resolve = worker.resolve_crafting_outcome
    segment = Segment("DM_NARRATOR", "neutral", "The work is finished.")
    prompts = []

    async def due() -> list[dict]:
        return [activity for activity in await original_due() if activity["id"] == activity_id]

    async def resolve(activity: dict, player: dict) -> dict:
        return await original_resolve(activity, player, rng=rng)

    async def narrate(outcome: dict, player: dict, activity: dict) -> tuple[list[Segment], str, str]:
        prompt, _ = build_narration_prompt(activity["activity_type"], outcome)
        prompts.append(prompt)
        return [segment], segment.text, "Finished."

    tts = AsyncMock()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(db_activity_queries, "get_due_activities", due)
        patch.setattr(worker, "resolve_crafting_outcome", resolve)
        patch.setattr(worker, "generate_activity_narration", narrate)
        patch.setattr(worker, "synthesize_segments", tts)
        for name in (
            "_backfill_progress_snippets",
            "generate_world_news",
            "generate_notification_hook",
            "send_push_notification",
        ):
            patch.setattr(worker, name, AsyncMock())
        await worker.resolve_due_activities()

    saved = await db_activity_queries.get_activity(activity_id)
    assert saved is not None and saved["status"] == "resolved"
    assert saved["narration_text"] == segment.text
    assert saved["narration_segments"] == [asdict(segment)]
    (audio_call,) = tts.await_args_list
    assert audio_call.args[0] == [segment]
    (prompt,) = prompts
    return saved["outcome"], prompt, rng


async def set_patron(world, patron: str) -> None:
    await world.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{divine_favor,patron}', $2::jsonb) WHERE player_id=$1",
        world.ids[0],
        json.dumps(patron),
    )


async def blessing_lifecycle(world, seed: int, tier: str) -> None:
    await prepare(world, "wooden_club", "aelora", 0, 100)
    row = await create(world, "wooden_club")
    if seed == 36:
        await set_patron(world, "none")
    outcome, prompt, rng = await poll(world, row, seed)
    assert outcome["tier"] == tier
    ctx = outcome["narrative_context"]
    expected_rng = random.Random(seed)
    expected_rng.randint(1, 20)
    if tier == "success":
        expected_rng.random()
    if seed == 0:
        assert outcome["bonus_property"] is None
        assert "craft_blessing" not in ctx and "Aelora" not in prompt
    else:
        table = await get_quality_outcomes("weapon")
        assert table is not None
        bonus = expected_rng.choice(table["bonus_properties"])
        assert outcome["bonus_property"] == ctx["bonus_property"] == bonus
        assert bonus["name"] in prompt and bonus["description"] in prompt
        if tier == "success":
            assert ctx["craft_blessing"] == {**BLESSING, "tier": "Acknowledged"}
            assert "Aelora's Craft Blessing" in prompt and "Exceptional touch" not in prompt
        else:
            assert "craft_blessing" not in ctx and "Exceptional touch" in prompt
    assert rng.getstate() == expected_rng.getstate()
    assert_creation(row, (675, 1350), "Acknowledged")


SCENARIOS = {
    BLESSING["id"]: (
        "async_rules:resolve_crafting",
        blessing_lifecycle,
        [(36, "success"), (0, "success"), (5, "exceptional")],
    )
}


@pytest.mark.parametrize("level,maximum,tier", TIERS)
async def test_voice_captures_canonical_tier(world, level: int, maximum: int, tier: str) -> None:
    await prepare(world, "iron_sword", "aelora", level, maximum)
    assert_creation(await create(world, "iron_sword"), (10800, 21600), tier)


@pytest.mark.parametrize("patron", ["none", "veythar", None])
async def test_unblessed_creation_and_legacy_resolution(world, patron: str | None) -> None:
    await prepare(world, "wooden_club", patron or "none", 0, 100)
    if patron is None:
        await world.pool.execute("UPDATE players SET data=data - 'divine_favor' WHERE player_id=$1", world.ids[0])
    row = await create(world, "wooden_club")
    assert_creation(row, (900, 1800), None)
    if patron == "none":
        await set_patron(world, "aelora")
        outcome, prompt, rng = await poll(world, row, 36)
        assert outcome["tier"] == "success" and outcome["bonus_property"] is None
        assert "craft_blessing" not in outcome["narrative_context"] and "Aelora" not in prompt
        expected_rng = random.Random(36)
        expected_rng.randint(1, 20)
        assert rng.getstate() == expected_rng.getstate()


@pytest.mark.parametrize("level,maximum", [(101, 100), (0, 0), (-1, 100)])
async def test_voice_refuses_invalid_favor(world, level: int, maximum: int) -> None:
    await prepare(world, "wooden_club", "aelora", level, maximum)
    with pytest.raises(ToolError, match="invalid divine favor"):
        await create(world, "wooden_club")
    assert not await world.pool.fetchval("SELECT 1 FROM async_activities WHERE player_id=$1", world.ids[0])
