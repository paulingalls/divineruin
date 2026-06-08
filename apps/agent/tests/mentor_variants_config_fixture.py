"""Test fixture for mentor variant catalog config.

Loads content/mentor_variants.json and populates mentor_variants._mentor_variants
before each test, so tests see the same catalog as production without running the
async DB loader (and so dm_session's guarded load_mentor_variants() sees
is_loaded() True and skips the DB fetch). Mirrors tests/spells_config_fixture.py.
"""

import json
from pathlib import Path

from mentor_variants import parse_mentor_variant_row, set_mentor_variants

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "mentor_variants.json"


def load_fixture_config() -> dict:
    """Read content/mentor_variants.json and return the typed variant dict."""
    raw = json.loads(_CONTENT_PATH.read_text())
    return {entry["id"]: parse_mentor_variant_row(entry["id"], entry) for entry in raw}


def setup_mentor_variants_config_fixture() -> None:
    """Populate mentor_variants._mentor_variants from the content JSON, mirroring the loader."""
    set_mentor_variants(load_fixture_config())
