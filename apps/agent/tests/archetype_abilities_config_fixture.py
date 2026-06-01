"""Test fixture for archetype ability config.

Loads content/archetype_abilities.json and populates abilities._abilities before
each test, so tests see the same abilities as production without running the
async DB loader. Mirrors tests/archetypes_config_fixture.py.
"""

import json
from pathlib import Path

from abilities import parse_ability_row, set_abilities

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "archetype_abilities.json"


def load_fixture_config() -> dict:
    """Read content/archetype_abilities.json and return the typed ability dict."""
    raw = json.loads(_CONTENT_PATH.read_text())
    return {entry["id"]: parse_ability_row(entry["id"], entry) for entry in raw}


def setup_archetype_abilities_config_fixture() -> None:
    """Populate abilities._abilities from the content JSON, mirroring the
    production loader."""
    set_abilities(load_fixture_config())
