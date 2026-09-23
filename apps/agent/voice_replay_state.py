"""Seeded player state and persisted-inventory checks for voice replay rows."""

import json
from collections import Counter
from typing import Any


async def inventory_quantities(pool: Any, player_id: str) -> dict[str, int]:
    rows = await pool.fetch("SELECT item_id, data FROM player_inventory WHERE player_id = $1", player_id)
    return {row["item_id"]: json.loads(row["data"]).get("quantity", 0) for row in rows}


async def assert_inventory_result(
    pool: Any, player_id: str, before: dict[str, int], tool_output: dict[str, Any]
) -> dict[str, int]:
    materials = tool_output.get("materials")
    if not isinstance(materials, list) or not materials or any(not isinstance(item, str) for item in materials):
        raise AssertionError(f"gather tool returned an invalid material multiset: {materials!r}")
    after = await inventory_quantities(pool, player_id)
    changed = {
        item: after.get(item, 0) - before.get(item, 0)
        for item in set(before) | set(after)
        if after.get(item, 0) != before.get(item, 0)
    }
    expected = dict(Counter(materials))
    if changed != expected:
        raise AssertionError(f"inventory delta {changed!r} did not equal gather result {expected!r}")
    return changed


async def reset_seed(pool: Any, player_id: str) -> dict[str, int]:
    await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
    data = {
        "player_id": player_id,
        "name": "Voice Replay",
        "level": 2,
        "class": "skirmisher",
        "location_id": "greyvale_south_road",
        "attributes": {
            "strength": 12,
            "dexterity": 16,
            "constitution": 14,
            "intelligence": 10,
            "wisdom": 13,
            "charisma": 8,
        },
        "proficiencies": ["stealth", "perception"],
        "saving_throw_proficiencies": ["strength", "dexterity"],
        "hp": {"current": 28, "max": 28},
        "ac": 15,
    }
    await pool.execute("INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)", player_id, json.dumps(data))
    await pool.execute(
        "INSERT INTO skill_advancement (player_id, skill_id, tier, use_counter, narrative_moment_ready) "
        "VALUES ($1, 'survival', 'master', 0, FALSE)",
        player_id,
    )
    return await inventory_quantities(pool, player_id)
