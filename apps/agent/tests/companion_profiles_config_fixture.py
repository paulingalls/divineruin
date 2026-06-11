"""Test fixture for the companion profiles catalog config.

Loads content/companions.json and populates companion_profiles._companion_profiles before
each test, so tests see the same catalog as production without running the async DB loader
(and so agent.py's guarded load_companion_profiles() sees is_loaded() True and skips the DB
fetch). Mirrors tests/role_archetypes_config_fixture.py.
"""

import json
from pathlib import Path

from companion_profiles import parse_companion_row, set_companion_profiles

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "companions.json"


def load_fixture_config() -> dict:
    """Read content/companions.json and return the typed companion dict."""
    raw = json.loads(_CONTENT_PATH.read_text())
    return {entry["id"]: parse_companion_row(entry["id"], entry) for entry in raw}


def setup_companion_profiles_config_fixture() -> None:
    """Populate companion_profiles._companion_profiles from the content JSON, mirroring the loader."""
    set_companion_profiles(load_fixture_config())
