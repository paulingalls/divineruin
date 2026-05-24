"""Test fixture for training config.

Loads content/training_activity_types.json and populates
training_rules._activity_types before each test, so tests see the same data
as production without needing to run the async DB loader.
"""

import json
from pathlib import Path

from training_rules import (
    parse_activity_type_row,
    parse_recipe_study_cycles,
    set_recipe_study_cycles,
    set_training_activity_types,
)

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "training_activity_types.json"


def load_fixture_config() -> dict:
    """Read content/training_activity_types.json and return the typed config dict."""
    raw = json.loads(_CONTENT_PATH.read_text())
    return {entry["id"]: parse_activity_type_row(entry["id"], entry) for entry in raw}


def setup_training_config_fixture() -> None:
    """Populate training_rules._activity_types from the content JSON file, mirroring
    the production loader (incl. the recipe_study tier_cycles map)."""
    set_training_activity_types(load_fixture_config())
    raw = json.loads(_CONTENT_PATH.read_text())
    recipe_study = next((e for e in raw if e["id"] == "recipe_study"), None)
    if recipe_study is not None:
        set_recipe_study_cycles(parse_recipe_study_cycles(recipe_study))
