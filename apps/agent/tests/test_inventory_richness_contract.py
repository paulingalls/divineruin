"""inventory_richness is forward-wired: the producer ships before its economy reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from settlement_templates_config_fixture import load_fixture_config

from role_archetypes import parse_role_archetype_row, set_role_archetypes
from settlement_generation import instantiate_npc_from_template
from settlement_templates import (
    get_settlement_personality,
    set_settlement_templates,
)

_CONTENT = Path(__file__).resolve().parents[3] / "content"
_ARCHETYPES = json.loads((_CONTENT / "role_archetypes.json").read_text())


@pytest.fixture(autouse=True)
def _seed_catalogs():
    """Seed both content catalogs from the real JSON before each test (mirrors
    test_settlement_generation.py)."""
    set_settlement_templates(*load_fixture_config())
    set_role_archetypes({e["id"]: parse_role_archetype_row(e["id"], e) for e in _ARCHETYPES})


def test_inventory_richness_emitted_and_equals_personality_modifier():
    npc = instantiate_npc_from_template("innkeeper", "village", "prosperous")
    assert "inventory_richness" in npc
    assert npc["inventory_richness"] == get_settlement_personality("prosperous")["inventory_modifier"]


def test_inventory_richness_tracks_personality_not_constant():
    rich = instantiate_npc_from_template("innkeeper", "village", "prosperous")["inventory_richness"]
    lean = instantiate_npc_from_template("innkeeper", "village", "struggling")["inventory_richness"]
    assert rich == get_settlement_personality("prosperous")["inventory_modifier"]
    assert lean == get_settlement_personality("struggling")["inventory_modifier"]
    assert rich != lean


def test_inventory_richness_override_wins():
    npc = instantiate_npc_from_template("innkeeper", "village", "prosperous", {"inventory_richness": 3.0})
    assert npc["inventory_richness"] == 3.0
