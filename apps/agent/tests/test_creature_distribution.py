"""Distribution of the authored natural bestiary."""

import json
from collections import Counter
from pathlib import Path

CREATURES = Path(__file__).resolve().parents[3] / "content/creatures.json"
REGIONS = {
    "greyvale": 8,
    "thornveld": 8,
    "drathian_steppe": 4,
    "keldaran_mountains": 10,
    "sunward_coast": 3,
    "underground": 5,
}


def test_natural_creature_distribution():
    assert CREATURES.is_file()
    rows = json.loads(CREATURES.read_text())
    assert isinstance(rows, list) and rows
    natural = [row for row in rows if row["category"] != "hollow"]
    assert natural and len(natural) == 19
    assert len({row["id"] for row in natural}) == len(natural)
    counts = Counter(region for row in natural for region in row["regions"])
    assert dict(counts) == REGIONS
    assert all(count >= 3 for count in counts.values())
    greyvale = [row for row in natural if row["home_region"] == "greyvale"]
    keldaran = [row for row in natural if row["home_region"] == "keldaran_mountains"]
    assert greyvale and all(row["tier"] == 1 for row in greyvale)
    assert keldaran and any(row["tier"] == 3 for row in keldaran)
    pairs = [(row["behavior"]["tactics"], row["behavior"]["morale"]) for row in natural]
    assert len(set(pairs)) == len(natural)
