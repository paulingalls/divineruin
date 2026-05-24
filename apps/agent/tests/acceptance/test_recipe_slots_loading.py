"""Real-DB acceptance proof for the Python recipe_slots accessor (story-007, M5.1).

Migrates a Postgres testcontainer (migration 019 seeds recipe_slots inline), then
drives recipe_slots.get_recipe_slots against it via the reset_db_pool fixture. This
is the load-path half of concern d125d022f084: it pins the LOADED caps to the actual
migration-019 INSERT, not a hand-typed in-test copy. If someone edits the migration
seed (expert 15->12, master null->20, an untrained null typo), this fails where the
mocked unit test cannot. Runs on pre-push under REQUIRE_DOCKER; skips when Docker is
down (see tests/acceptance/conftest.py).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import recipe_slots

_MIGRATION_019 = Path(__file__).parents[4] / "scripts" / "migrations" / "019_recipes.sql"


def _seeded_caps_from_migration() -> dict[str, dict]:
    """Parse the recipe_slots INSERT rows straight out of migration 019.

    The expectation is derived from the migration source itself (not duplicated by
    hand), so editing the seed updates both the DB and this expectation together —
    the assertion only passes when the loaded caps match what the migration writes.
    """
    sql = _MIGRATION_019.read_text()
    block = re.search(r"INSERT INTO recipe_slots .*?VALUES\s*(.*?);", sql, re.DOTALL)
    assert block is not None, "recipe_slots INSERT not found in migration 019"
    caps: dict[str, dict] = {}
    for row_id, payload in re.findall(r"\('([^']+)',\s*'(\{.*?\})'\)", block.group(1)):
        caps[row_id] = json.loads(payload)
    assert caps, "no recipe_slots rows parsed from migration 019"
    return caps


async def test_get_recipe_slots_loads_migration_seed(reset_db_pool: str) -> None:
    """Loaded caps equal the migration-019 seed exactly — every tier, every cap."""
    expected = _seeded_caps_from_migration()

    loaded = await recipe_slots.get_recipe_slots()

    assert loaded == expected


async def test_master_cap_is_unlimited_and_others_capped(reset_db_pool: str) -> None:
    """Master loads as null (unlimited); the lower tiers load as concrete int caps."""
    loaded = await recipe_slots.get_recipe_slots()

    assert loaded["master"]["known_recipe_slots"] is None
    for tier in ("untrained", "trained", "expert"):
        cap = loaded[tier]["known_recipe_slots"]
        assert isinstance(cap, int) and not isinstance(cap, bool) and cap > 0
