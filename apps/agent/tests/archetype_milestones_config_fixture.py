"""Test fixture for archetype milestone config.

Loads content/archetype_milestones.json and populates milestones._milestones
before each test, so tests see the same milestones as production without running
the async DB loader. Mirrors tests/archetype_abilities_config_fixture.py.
"""

import json
from pathlib import Path

from milestones import parse_milestone_row, set_milestones

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "archetype_milestones.json"


def load_fixture_config() -> dict:
    """Read content/archetype_milestones.json and return the typed milestone dict."""
    raw = json.loads(_CONTENT_PATH.read_text())
    return {entry["id"]: parse_milestone_row(entry["id"], entry) for entry in raw}


def setup_archetype_milestones_config_fixture() -> None:
    """Populate milestones._milestones from the content JSON, mirroring the
    production loader."""
    set_milestones(load_fixture_config())
