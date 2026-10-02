import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from seed_content import validate  # type: ignore[import-not-found]


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", [None, 0, 5, 1.5, "2"])
async def test_seed_rejects_invalid_enemy_tier(tier):
    from copy import deepcopy

    from sample_fixtures import TEST_CREATURES

    class Connection:
        async def fetch(self, query):
            if "FROM encounter_templates" in query and "data" in query:
                return [
                    {
                        "id": "bad_encounter",
                        "data": json.dumps(
                            {
                                "id": "bad_encounter",
                                "recommended_party_level": 1,
                                "enemies": [{"id": "bad_enemy", "creature_id": "fixture_goblin", "role": "standard"}],
                            }
                        ),
                    }
                ]
            if "FROM creatures" in query:
                creature = deepcopy(TEST_CREATURES["fixture_goblin"])
                if tier is None:
                    creature.pop("tier")
                else:
                    creature["tier"] = tier
                return [{"id": creature["id"], "data": json.dumps(creature)}]
            if "FROM loot_tables" in query:
                return [{"id": "loot_ok", "data": json.dumps({"drops": []})}]
            return []

    errors = await validate(Connection())
    assert any("bad_encounter" in error and "bad_enemy" in error and "tier" in error for error in errors)
