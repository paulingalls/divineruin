"""Test fixture for the settlement templates catalog config.

Loads content/settlement_templates.json and populates
settlement_templates._tiers / ._personalities before each test, so tests see the same
catalog as production without running the async DB loader (and so agent.py's guarded
load_settlement_templates() sees is_loaded() True and skips the DB fetch). Mirrors
tests/role_archetypes_config_fixture.py.
"""

import json
from pathlib import Path

from settlement_templates import parse_settlement_template_row, set_settlement_templates

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "settlement_templates.json"


def load_fixture_config() -> tuple[dict, dict]:
    """Read content/settlement_templates.json and return the (tiers, personalities) dicts."""
    raw = json.loads(_CONTENT_PATH.read_text())
    tiers: dict[str, dict] = {}
    personalities: dict[str, dict] = {}
    for entry in raw:
        row = parse_settlement_template_row(entry["id"], entry)
        (tiers if entry["kind"] == "tier" else personalities)[entry["id"]] = row
    return tiers, personalities


def setup_settlement_templates_config_fixture() -> None:
    """Populate the settlement-templates catalog from the content JSON, mirroring the loader."""
    set_settlement_templates(*load_fixture_config())
