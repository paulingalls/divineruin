"""Creation and legacy rows supply every pool required by their archetype."""

import json
from datetime import UTC, datetime
from pathlib import Path

from acceptance.rest_walk import RestWalk

import db_mutations
from creation_classes import CLASSES
from creation_rules import build_character_data
from resource_costs import gate_pool
from rules_engine import attribute_modifier, calculate_max_pools

MIGRATION = Path(__file__).resolve().parents[4] / "scripts/migrations/063_player_resource_pools.sql"


def test_created_and_legacy_characters_can_recover_their_declared_pools(harness):
    async def check():
        walk = await RestWalk().setup(harness)
        await walk.solo()
        assert len(CLASSES) == 18
        for archetype in CLASSES:
            data = build_character_data(
                "Rest Tester", "human", archetype, None, "", created_at=datetime(2026, 11, 15, tzinfo=UTC)
            )
            data["location_id"] = walk.sd.location_id
            maxima = calculate_max_pools(
                archetype, data["level"], {key: attribute_modifier(value) for key, value in data["attributes"].items()}
            )
            for key in ("stamina", "focus"):
                maximum = getattr(maxima, key)
                if maximum is None:
                    assert key not in data
                else:
                    assert data[key] == {"current": maximum, "max": maximum}
                    data[key]["current"] = 0
            await db_mutations.create_player(walk.player, None, data)
            receipt = await walk.command("long")
            assert not receipt.is_error, receipt.output
            row = await walk.row(walk.player)
            for key in ("stamina", "focus"):
                maximum = getattr(maxima, key)
                if maximum is None:
                    assert key not in row
                else:
                    assert row[key] == {"current": maximum, "max": maximum}
                    gate_pool(row, key, 1, label="post-rest action")
            legacy = {key: value for key, value in data.items() if key not in ("stamina", "focus")}
            legacy["level"] = 7
            legacy["attributes"] = {key: 7 for key in legacy["attributes"]}
            legacy_maxima = calculate_max_pools(archetype, 7, {key: -2 for key in legacy["attributes"]})
            await walk.pool.execute(
                "UPDATE players SET data=$2::jsonb WHERE player_id=$1", walk.player, json.dumps(legacy)
            )
            before = await walk.row(walk.player)
            receipt = await walk.command("long")
            assert receipt.is_error
            assert await walk.row(walk.player) == before
            await walk.pool.execute(MIGRATION.read_text())
            repaired = await walk.row(walk.player)
            for key in ("stamina", "focus"):
                maximum = getattr(legacy_maxima, key)
                if maximum is not None:
                    assert repaired[key] == {"current": maximum, "max": maximum}
                else:
                    assert key not in repaired
            # Existing spent pools must survive replay of the backfill.
            await db_mutations.create_player(walk.player, None, data)
            await walk.pool.execute(MIGRATION.read_text())
            assert await walk.row(walk.player) == data
            walk.events.clear()

    harness.run_sync(check())
