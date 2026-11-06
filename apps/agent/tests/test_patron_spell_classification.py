"""Strict authored predicates cannot silently turn off a patron's modifier."""

import json
from pathlib import Path

import pytest

from spells import parse_spell_row


@pytest.mark.parametrize("field", ["combat_aid", "healing"])
@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_classification_requires_boolean(field, value):
    row = json.loads((Path(__file__).resolve().parents[3] / "content/spells.json").read_text())[0]
    row[field] = value
    with pytest.raises(ValueError, match=field):
        parse_spell_row(row["id"], row)


@pytest.mark.parametrize("field", ["combat_aid", "healing"])
def test_classification_is_required(field):
    row = json.loads((Path(__file__).resolve().parents[3] / "content/spells.json").read_text())[0]
    del row[field]
    with pytest.raises(ValueError, match=field):
        parse_spell_row(row["id"], row)
