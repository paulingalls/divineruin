"""Companion portrait parsing and session payload boundary tests."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

import db
from companion_profiles import parse_companion_row, set_companion_profiles

EXPECTED_PORTRAITS = {
    "companion_kael": ("companion_kael_primary", "companion_kael_alert"),
    "companion_lira": ("companion_lira_primary", "companion_lira_alert"),
    "companion_tam": ("companion_tam_primary", "companion_tam_alert"),
    "companion_sable": ("companion_sable_primary", "companion_sable_alert"),
}

CONTENT_PATH = Path(__file__).resolve().parents[4] / "content" / "companions.json"


def _raw_rows() -> list[dict]:
    return json.loads(CONTENT_PATH.read_text())


def _raw_row(companion_id: str) -> dict:
    rows = _raw_rows()
    return deepcopy(next(row for row in rows if row["id"] == companion_id))


def test_every_authored_companion_parses_its_portrait_pair():
    rows = _raw_rows()
    for row in rows:
        portrait = parse_companion_row(row["id"], row).portrait
        assert portrait is not None
        assert (portrait.primary, portrait.alert) == EXPECTED_PORTRAITS[row["id"]]


def test_absent_portrait_parses_to_none_and_emits_explicit_null():
    row = _raw_row("companion_sable")
    row.pop("portrait", None)
    profile = parse_companion_row(row["id"], row)
    set_companion_profiles({profile.id: profile})

    assert profile.portrait is None
    assert db._build_portraits(profile.id)["companion"] is None


@pytest.mark.parametrize(
    ("portrait", "field"),
    [
        ("companion_sable_primary", "portrait"),
        ({"primary": "companion_sable_primary"}, "portrait.alert"),
        ({"primary": 7, "alert": "companion_sable_alert"}, "portrait.primary"),
    ],
)
def test_malformed_portrait_pair_fails_loud_with_row_context(portrait: object, field: str):
    row = _raw_row("companion_sable")
    row["portrait"] = portrait

    with pytest.raises(ValueError, match=rf"companion_sable.*{field}"):
        parse_companion_row(row["id"], row)
