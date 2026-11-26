"""Arcane Revelation through registered checks, worker completion and session init."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from _unbound_path_fixtures import MilestoneWalk

import db_training
from _gods_content import engine_implementations, load_gods
from async_worker_training import advance_training_cycles
from conditions import apply_condition
from dialogue_parser import Segment
from exploration_agent import ExplorationAgent


async def _setup(
    walk: MilestoneWalk, *, archetype: str = "cleric", patron: str = "veythar", inspired: bool = False
) -> None:
    await walk.patch(
        **{"class": archetype},
        divine_favor={"patron": patron, "level": 0, "max": 100},
        level=1,
        attributes={"intelligence": 10},
        proficiencies=[],
        conditions=apply_condition([], "inspired") if inspired else [],
    )
    walk.stack.push_async_callback(walk.pool.execute, "DELETE FROM skill_advancement WHERE player_id=$1", walk.player)
    walk.stack.enter_context(patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=11)))


async def _check(walk: MilestoneWalk, skill: str = "arcana", difficulty: str = "moderate") -> dict:
    return await walk.command(
        "check",
        {
            "roll": {
                "kind": "skill",
                "synergy_context": "none",
                "skill": skill,
                "difficulty": difficulty,
                "hearing_only": False,
                "context_description": "Read the magical trace",
            }
        },
    )


async def arcane_revelation(world: SimpleNamespace) -> None:
    async with MilestoneWalk(world.pool) as walk:
        await _setup(walk)
        receipt = await _check(walk)
        assert (receipt["roll"], receipt["modifier"], receipt["total"]) == (11, 3, 14)
        assert receipt["skill_tier"] == "trained"


SCENARIOS = {"veythar_arcane_revelation": ("rules_engine:_get_skill_tier", arcane_revelation, [()])}


async def test_tier_gated_arcana_receipt_reports_training(dev_db_pool: asyncpg.Pool) -> None:
    async with MilestoneWalk(dev_db_pool) as walk:
        await _setup(walk)
        receipt = await _check(walk, difficulty="extreme")
        assert (receipt["outcome"], receipt["roll"]) == ("automatic_failure", 0)
        assert receipt["skill_tier"] == "trained"


async def _seed_arcana(walk: MilestoneWalk, tier: str, counter: int = 0) -> None:
    await walk.pool.execute(
        "INSERT INTO skill_advancement (player_id, skill_id, tier, use_counter) VALUES ($1, 'arcana', $2, $3)",
        walk.player,
        tier,
        counter,
    )


async def _arcana_progress(walk: MilestoneWalk) -> tuple:
    row = await walk.pool.fetchrow(
        "SELECT tier, use_counter FROM skill_advancement WHERE player_id=$1 AND skill_id='arcana'",
        walk.player,
    )
    assert row is not None
    return tuple(row)


async def _complete_practice(walk: MilestoneWalk) -> None:
    activity_id = await db_training.create_training_activity(
        walk.player,
        "skill_practice",
        "running_second_half",
        {"skill": "arcana", "stat": "intelligence", "dc": 12, "decision_id": "fundamentals"},
        transition_at=datetime.now(UTC) - timedelta(seconds=1),
        conn=walk.pool,
    )
    walk.stack.push_async_callback(walk.pool.execute, "DELETE FROM training_activities WHERE id=$1", activity_id)
    walk.stack.push_async_callback(
        walk.pool.execute, "DELETE FROM training_cycle_accruals WHERE activity_id=$1", activity_id
    )
    real_due = db_training.get_due_training_transitions

    async def due_for_activity() -> list[dict]:
        return [row for row in await real_due() if row["id"] == activity_id]

    with (
        patch.object(db_training, "get_due_training_transitions", side_effect=due_for_activity),
        patch(
            "async_worker_training.generate_activity_narration",
            AsyncMock(return_value=([Segment("DM_NARRATOR", "neutral", "You practice Arcana.")], "Practice.", "Done.")),
        ),
        patch("async_worker_training.synthesize_segments", new_callable=AsyncMock),
        patch("async_worker_training.generate_notification_hook", new_callable=AsyncMock),
        patch("async_worker_training.send_push_notification", new_callable=AsyncMock),
    ):
        assert await advance_training_cycles() == 1
    activity = await db_training.get_training_activity(activity_id, conn=walk.pool)
    assert activity is not None and activity["state"] == "complete"


async def _published_character(walk: MilestoneWalk) -> dict:
    room = cast(MagicMock, walk.sd.room)
    await ExplorationAgent()._publish_session_init(walk.sd)
    send = room.local_participant.publish_data.await_args
    assert send is not None
    return json.loads(send.args[0])["character"]


@pytest.mark.parametrize(
    ("initial_counter", "inspired", "earned"),
    [
        pytest.param(0, False, "untrained", id="ordinary"),
        pytest.param(0, True, "untrained", id="inspired"),
        pytest.param(6, False, "trained", id="earned-training"),
    ],
)
async def test_arcana_progress_survives_patron_change(
    dev_db_pool: asyncpg.Pool, initial_counter: int, inspired: bool, earned: str
) -> None:
    async with MilestoneWalk(dev_db_pool) as walk:
        await _setup(walk, inspired=inspired)
        if initial_counter:
            await _seed_arcana(walk, "untrained", initial_counter)
        if inspired:
            walk.stack.enter_context(patch("condition_bonus.dice_roll", return_value=SimpleNamespace(total=2)))
        receipt = await _check(walk)
        assert await _arcana_progress(walk) == ("untrained", initial_counter + 1)
        assert receipt["skill_tier"] == "trained"
        assert receipt["total"] == (16 if inspired else 14)

        await _complete_practice(walk)
        assert await _arcana_progress(walk) == (earned, initial_counter + 3)
        await walk.patch(divine_favor={"patron": "kaelen", "level": 0, "max": 100})
        receipt = await _check(walk)
        assert (receipt["skill_tier"], receipt["modifier"]) == (earned, 3 if earned == "trained" else 0)

        raw = json.loads(await walk.pool.fetchval("SELECT data FROM players WHERE player_id=$1", walk.player))
        assert raw["proficiencies"] == []
        assert "arcana" not in raw.get("skill_tiers", {})
        if earned == "untrained":
            character = await _published_character(walk)
            assert character.get("skill_tiers", {}).get("arcana", "untrained") == "untrained"
            assert "arcana" not in character["proficiencies"]


@pytest.mark.parametrize(
    ("archetype", "patron", "skill", "tier", "modifier"),
    [
        ("cleric", "veythar", "arcana", "expert", 5),
        ("cleric", "veythar", "arcana", "master", 6),
        ("cleric", "kaelen", "arcana", "untrained", 0),
        ("mage", "veythar", "arcana", "untrained", 0),
        ("cleric", "veythar", "history", "untrained", 0),
    ],
)
async def test_arcana_grant_respects_earned_tier_and_scope(
    dev_db_pool: asyncpg.Pool, archetype: str, patron: str, skill: str, tier: str, modifier: int
) -> None:
    async with MilestoneWalk(dev_db_pool) as walk:
        await _setup(walk, archetype=archetype, patron=patron)
        if tier != "untrained":
            await _seed_arcana(walk, tier)
        receipt = await _check(walk, skill)
        assert (receipt["roll"], receipt["modifier"], receipt["total"]) == (11, modifier, 11 + modifier)
        assert receipt["skill_tier"] == tier
        if tier != "untrained":
            assert await _arcana_progress(walk) == (tier, 1)


@pytest.mark.parametrize(
    ("proficiencies", "stored_tier", "expected_proficiencies"),
    [
        pytest.param([], None, ["arcana"], id="grant"),
        pytest.param(["arcana"], None, ["arcana"], id="already-proficient"),
        pytest.param([], "expert", [], id="earned-expert"),
    ],
)
async def test_session_init_projects_only_the_arcana_grant(
    dev_db_pool: asyncpg.Pool,
    proficiencies: list[str],
    stored_tier: str | None,
    expected_proficiencies: list[str],
) -> None:
    async with MilestoneWalk(dev_db_pool) as walk:
        await _setup(walk)
        await walk.patch(proficiencies=proficiencies)
        if stored_tier:
            await _seed_arcana(walk, stored_tier)
        character = await _published_character(walk)
        assert character["proficiencies"] == expected_proficiencies
        tier = character.get("skill_tiers", {}).get("arcana", "trained" if "arcana" in proficiencies else None)
        assert tier == (stored_tier or "trained")


def test_arcane_revelation_catalog() -> None:
    veythar = next(god for god in load_gods() if god["god_id"] == "veythar")
    assert veythar["layer_4_synergy_matrix"]["cleric"]["clauses"] == [
        {
            "effect": "Arcana as bonus starting skill.",
            "status": "active",
            "resolution": "engine",
            "implementation_id": "veythar_arcane_revelation",
        },
        {
            "effect": "Divine magic auto-identifies magical effects (no check)",
            "status": "active",
            "resolution": "narrated",
        },
    ]
    assert engine_implementations()["veythar_arcane_revelation"] == "rules_engine:_get_skill_tier"
