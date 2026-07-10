"""Fast-lane contract guard for the forward-wired `inventory_richness` NPC field (M23 / story-006).

`settlement_generation.instantiate_npc_from_template` stamps
`npc["inventory_richness"] = pers["inventory_modifier"]` onto every generated settlement NPC,
but nothing READS `inventory_richness` until the Phase-9 economy lands (SMM risk 477619e6238e —
close-with-guard). This pins the producer contract so the shape/value a Phase-9 reader will depend
on cannot drift silently before the consumer exists: the field is emitted, equals the personality's
inventory_modifier, and an explicit override wins.

Pure fast-lane (no DB, no LLM) — mirrors tests/test_settlement_generation.py's catalog-seeding
fixture, exercising the shipped content/*.json data rather than hand-rolled stubs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from role_archetypes import parse_role_archetype_row, set_role_archetypes
from settlement_generation import instantiate_npc_from_template
from settlement_templates import (
    get_settlement_personality,
    parse_settlement_template_row,
    set_settlement_templates,
)

_CONTENT = Path(__file__).resolve().parents[3] / "content"
_TEMPLATES = json.loads((_CONTENT / "settlement_templates.json").read_text())
_ARCHETYPES = json.loads((_CONTENT / "role_archetypes.json").read_text())


@pytest.fixture(autouse=True)
def _seed_catalogs():
    """Seed both content catalogs from the real JSON before each test (mirrors
    test_settlement_generation.py)."""
    tiers: dict[str, dict] = {}
    personalities: dict[str, dict] = {}
    for e in _TEMPLATES:
        row = parse_settlement_template_row(e["id"], e)
        (tiers if e["kind"] == "tier" else personalities)[e["id"]] = row
    set_settlement_templates(tiers, personalities)
    set_role_archetypes({e["id"]: parse_role_archetype_row(e["id"], e) for e in _ARCHETYPES})


def test_inventory_richness_emitted_and_equals_personality_modifier():
    # A generated NPC carries inventory_richness set to its settlement personality's
    # inventory_modifier — the exact producer contract a Phase-9 economy reader will consume.
    npc = instantiate_npc_from_template("innkeeper", "village", "prosperous")
    assert "inventory_richness" in npc
    assert npc["inventory_richness"] == get_settlement_personality("prosperous")["inventory_modifier"]


def test_inventory_richness_tracks_personality_not_constant():
    # A second personality proves the value tracks the personality modifier (prosperous>1.0 fuller,
    # struggling<1.0 thinner), not a hardcoded constant.
    rich = instantiate_npc_from_template("innkeeper", "village", "prosperous")["inventory_richness"]
    lean = instantiate_npc_from_template("innkeeper", "village", "struggling")["inventory_richness"]
    assert rich == get_settlement_personality("prosperous")["inventory_modifier"]
    assert lean == get_settlement_personality("struggling")["inventory_modifier"]
    assert rich != lean


def test_inventory_richness_override_wins():
    # An explicit caller override beats the personality default (the "overrides WIN" contract).
    npc = instantiate_npc_from_template("innkeeper", "village", "prosperous", {"inventory_richness": 3.0})
    assert npc["inventory_richness"] == 3.0
