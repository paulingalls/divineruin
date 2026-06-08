"""Test fixture for the role archetype catalog config.

Loads content/role_archetypes.json and populates role_archetypes._role_archetypes
before each test, so tests see the same catalog as production without running the
async DB loader (and so agent.py / async_worker.py's guarded load_role_archetypes()
sees is_loaded() True and skips the DB fetch). Mirrors tests/mentor_variants_config_fixture.py.
"""

import json
from pathlib import Path

from role_archetypes import parse_role_archetype_row, set_role_archetypes

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "role_archetypes.json"


def load_fixture_config() -> dict:
    """Read content/role_archetypes.json and return the typed archetype dict."""
    raw = json.loads(_CONTENT_PATH.read_text())
    return {entry["id"]: parse_role_archetype_row(entry["id"], entry) for entry in raw}


def setup_role_archetypes_config_fixture() -> None:
    """Populate role_archetypes._role_archetypes from the content JSON, mirroring the loader."""
    set_role_archetypes(load_fixture_config())
