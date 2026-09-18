"""Test fixture for archetype chassis config.

Loads content/archetypes.json and populates archetypes._archetypes before each
test, so tests see the same chassis as production without running the async DB
loader. Mirrors tests/training_config_fixture.py.
"""

import json
from pathlib import Path

from archetypes import parse_archetype_row, set_archetypes

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "archetypes.json"


def load_archetype_rows() -> list[dict]:
    """Read content/archetypes.json with the floor constraint 12 demands of a corpus
    walk: a file that came back empty, or one with duplicate ids, must not read as a
    clean sweep. Every walk over the authored archetypes goes through here."""
    rows = json.loads(_CONTENT_PATH.read_text())
    assert rows, "content/archetypes.json came back empty"
    assert all(isinstance(row.get("id"), str) for row in rows)
    assert len({row["id"] for row in rows}) == len(rows), "content/archetypes.json has duplicate ids"
    return rows


def load_fixture_config() -> dict:
    """Read content/archetypes.json and return the typed chassis dict."""
    return {entry["id"]: parse_archetype_row(entry["id"], entry) for entry in load_archetype_rows()}


def setup_archetypes_config_fixture() -> None:
    """Populate archetypes._archetypes from the content JSON, mirroring the
    production loader."""
    set_archetypes(load_fixture_config())
