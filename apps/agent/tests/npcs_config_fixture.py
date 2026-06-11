"""Test fixture for the NPC catalog config.

Loads content/npcs.json and populates npcs._npcs before each test, so tests see the
same catalog as production without running the async DB loader (and so agent.py /
async_worker.py's guarded load_npcs() sees is_loaded() True and skips the DB fetch).
Mirrors tests/role_archetypes_config_fixture.py.
"""

import json
from pathlib import Path

from npcs import parse_npc_row, set_npcs

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "npcs.json"


def load_fixture_config() -> dict:
    """Read content/npcs.json and return the validated NPC dict keyed by id."""
    raw = json.loads(_CONTENT_PATH.read_text())
    return {entry["id"]: parse_npc_row(entry["id"], entry) for entry in raw}


def setup_npcs_config_fixture() -> None:
    """Populate npcs._npcs from the content JSON, mirroring the loader."""
    set_npcs(load_fixture_config())
