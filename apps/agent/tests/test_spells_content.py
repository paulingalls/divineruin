"""Content guard for content/spells.json — the M3.3 87-spell catalog (story-001).

The loader (spells.parse_spell_row) is strict per-row; this guard enforces the
catalog-wide invariants the loader cannot see: the exact 87-spell count, the
30/28/29 source partitions, unique ids, and that every authored row carries the
M3.3 fields and round-trips through the strict loader. It is the presence-enforcer
the merged story (loader + catalog) relies on — see decision spell-loader-strict-contract.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from spells import Spell, parse_spell_row

CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "spells.json"

_RAW = json.loads(CONTENT_PATH.read_text())

# The base + M3.3 fields every authored row must carry.
_REQUIRED_FIELDS = (
    "id",
    "name",
    "source",
    "spell_tier",
    "focus_cost",
    "mechanics",
    "narration_cue",
    "resonance_by_source",
    "terrain_effects",
    "audio_cue",
    "concentration",
    "level_requirement",
)


def test_catalog_has_exactly_87_spells():
    assert len(_RAW) == 87


def test_source_partitions_are_30_28_29():
    counts = Counter(row["source"] for row in _RAW)
    assert dict(counts) == {"arcane": 30, "divine": 28, "primal": 29}


def test_ids_are_unique():
    ids = [row["id"] for row in _RAW]
    assert len(ids) == len(set(ids)) == 87


@pytest.mark.parametrize("row", _RAW, ids=[r["id"] for r in _RAW])
def test_every_row_carries_all_required_fields(row):
    missing = [f for f in _REQUIRED_FIELDS if f not in row]
    assert not missing, f"{row.get('id')} missing {missing}"


@pytest.mark.parametrize("row", _RAW, ids=[r["id"] for r in _RAW])
def test_every_row_parses_through_the_strict_loader(row):
    # E2E: the authored catalog satisfies the strict parse_spell_row contract.
    assert isinstance(parse_spell_row(row["id"], row), Spell)


@pytest.mark.parametrize("row", _RAW, ids=[r["id"] for r in _RAW])
def test_resonance_is_keyed_by_the_rows_own_source(row):
    # resonance_by_source maps the spell's magic source to its catalog Resonance.
    assert row["source"] in row["resonance_by_source"]


@pytest.mark.parametrize("row", _RAW, ids=[r["id"] for r in _RAW])
def test_terrain_effects_nonempty_only_for_primal(row):
    # Terrain-variable Resonance is a Primal-only mechanic; non-Primal rows hold {}.
    if row["source"] != "primal":
        assert row["terrain_effects"] == {}, f"{row['id']} is {row['source']} but has terrain_effects"
