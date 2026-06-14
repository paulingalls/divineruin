"""Test fixture for the racial Resonance bonus table config.

Loads content/racial_resonance_bonuses.json and populates racial_resonance._bonuses
before each test, so tests see the same per-race modifier table as production without
running the async DB loader. Mirrors tests/spells_config_fixture.py.
"""

import json
from pathlib import Path

from racial_resonance import parse_racial_resonance_row, set_racial_bonuses

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "racial_resonance_bonuses.json"


def load_fixture_config() -> dict:
    """Read content/racial_resonance_bonuses.json and return the typed bonus dict."""
    raw = json.loads(_CONTENT_PATH.read_text())
    return {entry["id"]: parse_racial_resonance_row(entry["id"], entry) for entry in raw}


def setup_racial_resonance_config_fixture() -> None:
    """Populate racial_resonance._bonuses from the content JSON, mirroring the production loader."""
    set_racial_bonuses(load_fixture_config())
