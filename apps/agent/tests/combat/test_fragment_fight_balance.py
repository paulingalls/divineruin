"""The contained first fight uses the shared fixed-seed combat policy."""

import json

import first_blood_harness as harness
from sample_fixtures import CONTENT_ROOT

import db_content_queries
from encounter_budget import calculate_encounter_budget


async def test_fragment_fight_balance(dev_db_pool, monkeypatch):
    authored = next(
        row
        for row in json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
        if row["id"] == "fragment_shadeling"
    )
    template = await db_content_queries.get_encounter_template("fragment_shadeling")
    assert template is not None
    assert template == authored
    assert template["difficulty"] == "easy" and template["recommended_party_level"] == 1
    assert [(e["creature_id"], e["role"]) for e in template["enemies"]] == [("hollow_shadeling", "standard")]
    report = calculate_encounter_budget(template["enemies"], 1)
    assert not any(report[key] for key in ("all_minion", "over_budget", "too_many_bosses"))
    print(f"fragment budget={report}")
    counts, standing = await harness.win_counts(dev_db_pool, encounter_id="fragment_shadeling")
    assert set(counts) == set(standing) == set(harness.ARCHETYPES)
    assert all(count >= 16 for count in counts.values()), counts
