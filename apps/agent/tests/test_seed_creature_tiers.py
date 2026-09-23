import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from seed_content import validate  # type: ignore[import-not-found]


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", [None, 0, 5, 1.5, "2"])
async def test_seed_rejects_invalid_enemy_tier(tier):
    class Connection:
        async def fetch(self, query):
            if "FROM encounter_templates" in query and "data" in query:
                enemy = {"id": "bad_enemy", "category": "humanoid", "loot_table_id": "loot_ok"}
                if tier is not None:
                    enemy["tier"] = tier
                return [{"id": "bad_encounter", "data": json.dumps({"enemies": [enemy]})}]
            if "FROM loot_tables" in query:
                return [{"id": "loot_ok", "data": json.dumps({"drops": []})}]
            return []

    errors = await validate(Connection())
    assert any("bad_encounter" in error and "bad_enemy" in error and "tier" in error for error in errors)
