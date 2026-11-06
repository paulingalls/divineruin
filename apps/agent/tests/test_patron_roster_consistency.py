"""content/gods.json is the patron roster authority (ADR 0001)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from _gods_content import load_gods
from creation_deities import DEITIES
from god_whisper_data import GOD_WHISPER_PROFILES

ROSTER = json.loads((Path(__file__).resolve().parents[3] / "packages/shared/fixtures/god_profiles.json").read_text())[
    "patron_ids"
]
EXPECTED_PATRON_IDS = frozenset(ROSTER)
assert len(ROSTER) == len(EXPECTED_PATRON_IDS) == 10


GODS_ENTRIES: list[dict] = load_gods()
GODS_BY_ID: dict[str, dict] = {entry["god_id"]: entry for entry in GODS_ENTRIES}


def test_gods_json_has_all_ten_patrons():
    assert set(GODS_BY_ID) == EXPECTED_PATRON_IDS


def test_creation_deities_has_all_ten_patrons_plus_unbound():
    ids = set(DEITIES.keys())
    assert ids == EXPECTED_PATRON_IDS | {"none"}


def test_god_whisper_profiles_has_all_ten_patrons():
    assert set(GOD_WHISPER_PROFILES.keys()) == EXPECTED_PATRON_IDS


def test_short_name_agrees_across_all_three_surfaces():
    for patron_id in EXPECTED_PATRON_IDS:
        gods_short = GODS_BY_ID[patron_id]["short_name"]
        deity_short = DEITIES[patron_id].name
        whisper_short = GOD_WHISPER_PROFILES[patron_id].short_name

        assert gods_short == deity_short == whisper_short, (
            f"Name mismatch for {patron_id}: "
            f"gods.json={gods_short!r}, DEITIES.name={deity_short!r}, "
            f"GOD_WHISPER_PROFILES.short_name={whisper_short!r}"
        )


def test_gods_json_name_matches_creation_deities_full_title():
    for patron_id in EXPECTED_PATRON_IDS:
        expected = f"{DEITIES[patron_id].name}, {DEITIES[patron_id].title}"
        actual = GODS_BY_ID[patron_id]["name"]
        assert actual == expected, (
            f"Title mismatch for {patron_id}: gods.json name={actual!r}, expected from DEITIES={expected!r}"
        )


def test_personality_prompt_embeds_canonical_short_name_and_title():
    for entry in GODS_ENTRIES:
        short_name = entry["short_name"]
        title = entry["title"]
        prompt = entry["whisper_profile"]["personality_prompt"]
        assert short_name in prompt, (
            f"{entry['god_id']}: personality_prompt missing canonical short_name {short_name!r}: {prompt[:120]!r}"
        )
        assert title in prompt, (
            f"{entry['god_id']}: personality_prompt missing canonical title {title!r}: {prompt[:120]!r}"
        )


def test_gods_json_does_not_contain_unbound_entry():
    """An unbound player must not acquire god-agent state."""
    assert "none" not in GODS_BY_ID, "content/gods.json must not contain god_id='none' — see ADR 0001"


def test_load_deities_rejects_none_god_id_in_gods_json(tmp_path, monkeypatch):
    import _gods_content
    import creation_deities as cd

    unbound = copy.deepcopy(GODS_ENTRIES[0])
    unbound["god_id"] = "none"
    for tier, ability in unbound["layer_3_tier_abilities"].items():
        ability["id"] = f"none_{tier}"
    poisoned = [*GODS_ENTRIES, unbound]
    poisoned_path = tmp_path / "gods.json"
    poisoned_path.write_text(json.dumps(poisoned))
    monkeypatch.setattr(_gods_content, "_GODS_JSON_PATH", poisoned_path)
    _gods_content.load_gods.cache_clear()
    try:
        with pytest.raises(ValueError, match="god_id='none'"):
            cd._load_deities()
    finally:
        # monkeypatch reverts the path, but the cached poisoned value would leak.
        _gods_content.load_gods.cache_clear()


def test_authored_layers_and_reserved_layer_four():
    for entry in GODS_ENTRIES:
        assert entry["layer_2_resonance"] is not None, entry["god_id"]
        assert entry["layer_3_tier_abilities"] is not None, entry["god_id"]
        assert entry["layer_4_synergy_matrix"] is None, entry["god_id"]
