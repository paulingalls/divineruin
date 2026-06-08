"""Test fixture for spell catalog config.

Loads content/spells.json and populates spells._spells before each test, so tests
see the same elective spell catalog as production without running the async DB
loader. Mirrors tests/archetype_abilities_config_fixture.py.
"""

import json
from pathlib import Path

from spells import parse_spell_row, set_spells

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "spells.json"


def load_fixture_config() -> dict:
    """Read content/spells.json and return the typed spell dict."""
    raw = json.loads(_CONTENT_PATH.read_text())
    return {entry["id"]: parse_spell_row(entry["id"], entry) for entry in raw}


def setup_spells_config_fixture() -> None:
    """Populate spells._spells from the content JSON, mirroring the production loader."""
    set_spells(load_fixture_config())
