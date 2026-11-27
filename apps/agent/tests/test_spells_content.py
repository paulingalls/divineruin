import json
from collections import Counter
from pathlib import Path

import pytest

from spells import SPELL_SOUND_KEYS, Spell, parse_spell_row

CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "spells.json"

_RAW = json.loads(CONTENT_PATH.read_text())

_REQUIRED_FIELDS = (
    "id",
    "name",
    "source",
    "spell_tier",
    "focus_cost",
    "mechanics",
    "narration_cue",
    "verbal",
    "hostile",
    "resonance_by_source",
    "audio_cue",
    "concentration",
    "sound_id",
)


def test_catalog_has_exactly_87_spells():
    assert len(_RAW) == 87


def test_source_partitions_are_30_28_29():
    counts = Counter(row["source"] for row in _RAW)
    assert dict(counts) == {"arcane": 30, "divine": 28, "primal": 29}


def test_ids_are_unique():
    ids = [row["id"] for row in _RAW]
    assert len(ids) == len(set(ids)) == 87


_DURATIONS = {
    "primal_tsunami": 36,
    "arcane_hold_person": 60,
    "arcane_haste": 60,
    "arcane_slow": 60,
    "divine_bless": 60,
    "divine_beacon_of_hope": 60,
    "divine_banishment": 60,
    "divine_holy_aura": 60,
    "primal_entangle": 60,
    "primal_faerie_fire": 60,
    "primal_guardian_of_nature": 60,
    "primal_earthquake": 60,
    "primal_storm_of_vengeance": 60,
    "arcane_detect_magic": 600,
    "arcane_fly": 600,
    "arcane_wall_of_force": 600,
    "arcane_maze": 600,
    "divine_detect_hollow": 600,
    "primal_call_lightning": 600,
    "primal_protection_from_hollow": 600,
    "primal_wall_of_thorns": 600,
    "arcane_invisibility": 3600,
    "arcane_arcane_eye": 3600,
    "primal_conjure_animals": 3600,
    "primal_animal_shapes": 86400,
}


@pytest.mark.parametrize("value", [None, True, -1, 0, 1.5])
def test_concentration_requires_positive_integer_duration(value: object) -> None:
    row = next(row for row in _RAW if row["id"] == "divine_bless")
    with pytest.raises(ValueError, match="concentration_duration_seconds"):
        parse_spell_row(row["id"], {**row, "concentration_duration_seconds": value})


def test_concentration_requires_duration() -> None:
    row = dict(next(row for row in _RAW if row["id"] == "divine_bless"))
    row.pop("concentration_duration_seconds", None)
    with pytest.raises(ValueError, match="concentration_duration_seconds"):
        parse_spell_row(row["id"], row)


@pytest.mark.parametrize("row", _RAW, ids=[r["id"] for r in _RAW])
def test_every_row_carries_all_required_fields(row):
    missing = [f for f in _REQUIRED_FIELDS if f not in row]
    assert not missing, f"{row.get('id')} missing {missing}"


@pytest.mark.parametrize("row", _RAW, ids=[r["id"] for r in _RAW])
def test_every_row_parses_through_the_strict_loader(row):
    parsed = parse_spell_row(row["id"], row)
    assert isinstance(parsed, Spell)
    assert parsed.concentration_duration_seconds == _DURATIONS.get(row["id"])


@pytest.mark.parametrize("row", _RAW, ids=[r["id"] for r in _RAW])
def test_every_row_has_a_nonempty_audio_cue(row):
    # audio_cue is the DM's free-text audio-direction cue, voiced/directed on cast (returned in
    # the cast packet, spell_casting.py) — NOT a literal client SFX code (nothing maps it to real
    # SFX yet). Every spell has a sensory signature, so every row must carry a non-empty cue; an
    # empty string is a content gap that ships a silent spell (concern e3af222251df).
    assert row["audio_cue"].strip(), f"{row['id']} has an empty audio_cue"


@pytest.mark.parametrize("row", _RAW, ids=[r["id"] for r in _RAW])
def test_resonance_is_keyed_by_the_rows_own_source(row):
    assert row["source"] in row["resonance_by_source"]


@pytest.mark.parametrize("row", _RAW, ids=[r["id"] for r in _RAW])
def test_every_row_has_a_valid_sound_id(row):
    assert row["sound_id"] in SPELL_SOUND_KEYS, f"{row['id']} sound_id {row.get('sound_id')!r} not in palette"
