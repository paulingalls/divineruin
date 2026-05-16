"""Roster consistency across the three patron surfaces.

Source of truth: `content/gods.json` (see `docs/decisions/0001-patron-roster-sot.md`).
This test guards against drift between gods.json, `creation_deities.DEITIES`, and
`god_whisper_data.GOD_WHISPER_PROFILES`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from creation_deities import DEITIES
from god_whisper_data import GOD_WHISPER_PROFILES

GODS_JSON_PATH = Path(__file__).resolve().parents[3] / "content" / "gods.json"

EXPECTED_PATRON_IDS = frozenset(
    {
        "veythar",
        "kaelen",
        "aelora",
        "syrath",
        "thyra",
        "orenthel",
        "valdris",
        "mortaen",
        "nythera",
        "zhael",
    }
)


GODS_ENTRIES: list[dict] = json.loads(GODS_JSON_PATH.read_text())
GODS_BY_ID: dict[str, dict] = {entry["god_id"]: entry for entry in GODS_ENTRIES}


def test_gods_json_has_all_ten_patrons():
    assert set(GODS_BY_ID) == EXPECTED_PATRON_IDS


def test_creation_deities_has_all_ten_patrons_plus_unbound():
    ids = set(DEITIES.keys())
    assert ids == EXPECTED_PATRON_IDS | {"none"}


def test_god_whisper_profiles_has_all_ten_patrons():
    assert set(GOD_WHISPER_PROFILES.keys()) == EXPECTED_PATRON_IDS


def test_short_name_agrees_across_all_three_surfaces():
    """All 3 surfaces must carry the same authored short_name for each patron.

    Primary name = bare name, e.g. "Veythar" — not the full "Veythar, the Lorekeeper".
    Each surface reads short_name as an authored field; no derivation by string split.
    """
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
    """gods.json `name` field should be '<short_name>, <title>' from creation_deities."""
    for patron_id in EXPECTED_PATRON_IDS:
        expected = f"{DEITIES[patron_id].name}, {DEITIES[patron_id].title}"
        actual = GODS_BY_ID[patron_id]["name"]
        assert actual == expected, (
            f"Title mismatch for {patron_id}: gods.json name={actual!r}, expected from DEITIES={expected!r}"
        )


def test_personality_prompt_embeds_canonical_short_name_and_title():
    """Every whisper personality_prompt must embed the canonical short_name AND
    title so the LLM pronounces the same identity the HUD shows. Audio-first
    invariant — drift here ships into the voice path.
    """
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
    """Unbound (god_id='none') must not appear in gods.json — it is synthesized
    in creation_deities so it doesn't seed god_agent_state. ADR 0001 invariant."""
    assert "none" not in GODS_BY_ID, "content/gods.json must not contain god_id='none' — see ADR 0001"


def test_load_deities_rejects_none_god_id_in_gods_json(tmp_path, monkeypatch):
    """If a future change adds god_id='none' to gods.json, _load_deities raises."""
    import creation_deities as cd

    poisoned = [
        *GODS_ENTRIES,
        {
            "god_id": "none",
            "short_name": "Bogus",
            "title": "the Forbidden",
            "domain": "x",
            "description": "x",
            "card_description": "x",
            "synergy_classes": [],
        },
    ]
    poisoned_path = tmp_path / "gods.json"
    poisoned_path.write_text(json.dumps(poisoned))
    monkeypatch.setattr(cd, "_GODS_JSON_PATH", poisoned_path)

    with pytest.raises(ValueError, match="god_id='none'"):
        cd._load_deities()


def test_layer_2_through_4_placeholders_exist_and_are_null():
    """Phase 8 mechanical layers are reserved as null placeholders per ADR 0001.

    This test pins the contract that future Phase 8 sprints populate these slots —
    until then they must be present and null so authoring has one canonical place.
    """
    placeholders = (
        "layer_1_gift",
        "layer_2_resonance",
        "layer_3_tier_abilities",
        "layer_4_synergy_matrix",
    )
    for entry in GODS_ENTRIES:
        for key in placeholders:
            assert key in entry, f"{entry['god_id']} missing placeholder {key!r}"
            assert entry[key] is None, (
                f"{entry['god_id']} has non-null {key!r} — Phase 8 authoring "
                f"is out of scope for this ADR until a follow-up sprint"
            )
