"""The authored first quest fight is survivable with basic attacks at level one."""

import json
from time import perf_counter
from unittest.mock import AsyncMock

from first_blood_harness import PATROL, win_counts
from sample_fixtures import CONTENT_ROOT

import db
import db_content_queries
from encounter_budget import calculate_encounter_budget


async def test_first_blood_balance(dev_db_pool, monkeypatch):
    monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "_cache_set", AsyncMock())
    started = perf_counter()
    counts = await win_counts(dev_db_pool)
    print(f"80 fights: {perf_counter() - started:.3f}s")
    assert all(count >= 16 for count in counts.values()), counts
    templates = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
    template = next(t for t in templates if t["id"] == PATROL)
    assert await db_content_queries.get_encounter_template(PATROL) == template
    assert template["recommended_party_level"] == 1
    report = calculate_encounter_budget(template["enemies"], 1)
    assert not any(report[flag] for flag in ("too_many_bosses", "all_minion", "over_budget"))
