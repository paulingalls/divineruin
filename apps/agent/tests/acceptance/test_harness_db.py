"""Non-LLM infra test for the Postgres acceptance harness.

Proves the testcontainer migrates, content seeds, db.get_pool() targets the
container (reset_db_pool), and db_training round-trips — all without an Anthropic
key, so it runs on pre-push under REQUIRE_DOCKER while the LLM scenarios skip.
"""

from __future__ import annotations

from acceptance.seeds import clear_training_activities, seed_player

import db
import db_training


async def test_migrations_seed_and_training_roundtrip(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id="player_1")
    await clear_training_activities(pool, "player_1")
    program = await pool.fetchrow("SELECT data FROM training_programs WHERE id = $1", "combat_basics")

    # Content seed populated the training_programs table the tools read.
    assert program is not None

    activity_id = await db_training.create_training_activity(
        "player_1", "technique_base", "running_first_half", {"program_id": "combat_basics"}
    )
    assert activity_id.startswith("train_")

    row = await db_training.get_training_activity(activity_id)
    assert row is not None
    assert row["player_id"] == "player_1"
    assert row["state"] == "running_first_half"
    # _to_dict deserializes JSONB `data` to a real dict, matching how consumers
    # (async_worker.advance_training_cycles) index into it.
    assert row["data"]["program_id"] == "combat_basics"
