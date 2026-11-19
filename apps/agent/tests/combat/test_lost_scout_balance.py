"""The Lost Scout meets the level-four ruins balance bar."""

import json
from unittest.mock import AsyncMock

from first_blood_harness import ARCHETYPES, win_counts
from sample_fixtures import CONTENT_ROOT

import db
import db_content_queries


async def test_lost_scout_balance(dev_db_pool, monkeypatch):
    monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "_cache_set", AsyncMock())
    templates = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
    template = next(t for t in templates if t["id"] == "hollowed_scout")
    assert await db_content_queries.get_encounter_template(template["id"]) == template
    assert template["enemies"] and {e["creature_id"] for e in template["enemies"]} == {"hollowed_scout"}
    assert template["recommended_party_level"] == 4
    victories, standing = await win_counts(dev_db_pool, encounter_id=template["id"], player_level=4)
    assert set(victories) == set(standing) == set(ARCHETYPES)
    assert all(16 <= standing[key] <= victories[key] <= 20 for key in ARCHETYPES), (victories, standing)
