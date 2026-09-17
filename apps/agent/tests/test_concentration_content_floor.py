"""Player-authored condition producers cannot silently gain an incapacitating effect."""

import json
from pathlib import Path

import pytest

from condition_restrictions import cannot_act

_CONTENT = Path(__file__).resolve().parents[3] / "content"
_CATALOGS = (("spell", "spells.json"), ("ability", "archetype_abilities.json"))


def _tagged_condition_producers():
    return [
        (kind, row)
        for kind, filename in _CATALOGS
        for row in json.loads((_CONTENT / filename).read_text())
        if row.get("applies_condition")
    ]


def _assert_no_incapacitating_producers(tagged_rows):
    offenders = [
        f"{kind}:{row['id']}:{row['applies_condition']}"
        for kind, row in tagged_rows
        if cannot_act(({"type": row["applies_condition"]},))
    ]
    assert offenders == [], f"incapacitating player condition producers need concentration wiring: {offenders}"


def test_player_condition_producers_are_not_incapacitating():
    _assert_no_incapacitating_producers(_tagged_condition_producers())


@pytest.mark.parametrize("producer_kind", ["spell", "ability"])
def test_each_catalog_is_included_in_the_floor(monkeypatch, producer_kind):
    tagged = _tagged_condition_producers()
    row = next((row for kind, row in tagged if kind == producer_kind), None)
    assert row is not None, f"no {producer_kind} condition producer loaded"
    monkeypatch.setitem(row, "applies_condition", "stunned")

    with pytest.raises(AssertionError, match=rf"{producer_kind}:{row['id']}:stunned"):
        _assert_no_incapacitating_producers(tagged)
