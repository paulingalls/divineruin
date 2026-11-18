"""Moderate Hollow encounters support a solo player and scaled companion."""

import json
from unittest.mock import AsyncMock

import pytest
from first_blood_harness import ARCHETYPES, win_counts
from sample_fixtures import CONTENT_ROOT

import db
import db_content_queries


@pytest.mark.parametrize(
    "encounter_id,level,policy",
    [
        ("hollowmoth_swarm", 3, "basic"),
        ("hollow_weaver_ambush", 10, "basic"),
        ("hollow_mawling_pack", 10, "caster"),
    ],
)
async def test_hollow_troops_balance(dev_db_pool, monkeypatch, encounter_id, level, policy):
    monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "_cache_set", AsyncMock())
    templates = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
    template = next(t for t in templates if t["id"] == encounter_id)
    assert template["recommended_party_level"] == level
    if encounter_id == "hollow_mawling_pack":
        assert template["difficulty"] == "moderate"
        assert [(r["creature_id"], r["role"]) for r in template["enemies"]] == [
            ("hollow_mawling", "standard"),
        ]
    victories, standing = await win_counts(dev_db_pool, encounter_id=encounter_id, player_level=level, policy=policy)
    assert set(victories) == set(standing) == set(ARCHETYPES)
    assert all(16 <= standing[key] <= victories[key] <= 20 for key in ARCHETYPES), (victories, standing)
    assert await db_content_queries.get_encounter_template(encounter_id) == template
