"""Test fixture for archetype chassis config.

Loads content/archetypes.json and populates archetypes._archetypes before each
test, so tests see the same chassis as production without running the async DB
loader. Mirrors tests/training_config_fixture.py.
"""

import json
from pathlib import Path

from archetypes import parse_archetype_row, set_archetypes

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "archetypes.json"


def load_fixture_config() -> dict:
    """Read content/archetypes.json and return the typed chassis dict."""
    raw = json.loads(_CONTENT_PATH.read_text())
    return {entry["id"]: parse_archetype_row(entry["id"], entry) for entry in raw}


def setup_archetypes_config_fixture() -> None:
    """Populate archetypes._archetypes from the content JSON, mirroring the
    production loader."""
    set_archetypes(load_fixture_config())
