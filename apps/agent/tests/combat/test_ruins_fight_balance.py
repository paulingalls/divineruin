"""The authored ruins fight is survivable at the conservative level-two target."""

import json
from time import perf_counter
from unittest.mock import AsyncMock

from first_blood_harness import ARCHETYPES, win_counts
from sample_fixtures import CONTENT_ROOT

import db
import db_content_queries
from encounter_budget import calculate_encounter_budget


async def test_ruins_fight_balance(dev_db_pool, monkeypatch):
    monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "_cache_set", AsyncMock())
    templates = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
    template = next(t for t in templates if t["id"] == "ruins_mawling_pair")
    assert await db_content_queries.get_encounter_template(template["id"]) == template
    assert template["enemies"] and {e["creature_id"] for e in template["enemies"]} == {"hollow_mawling_young"}
    assert template["recommended_party_level"] == 2
    report = calculate_encounter_budget(template["enemies"], 2)
    assert not any(report[flag] for flag in ("too_many_bosses", "all_minion", "over_budget"))
    started = perf_counter()
    victories, standing = await win_counts(dev_db_pool, encounter_id=template["id"], player_level=2)
    print(f"80 ruins fights: {perf_counter() - started:.3f}s")
    assert set(victories) == set(standing) == set(ARCHETYPES)
    assert all(16 <= standing[key] <= victories[key] <= 20 for key in ARCHETYPES), (victories, standing)
