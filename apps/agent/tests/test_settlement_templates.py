"""Tests for the settlement_templates content loader (Phase 6 M6.2 / story-002).

The loader mirrors apps/agent/role_archetypes.py + npcs.py: fail-loud parse of the
content/settlement_templates.json catalog, a module-global pair of dicts (_tiers,
_personalities) with a set_* test seam, and a build-then-swap async DB loader. The
catalog is the template SSOT story-003 consumes — get_settlement_tier(size) for role
counts, get_settlement_personality(trait) for modifiers.

Catalog shape: a flat list of self-contained id/JSONB rows discriminated by `kind`:
4 tier rows (id == SettlementSize, role_counts of {min,max} ranges) + 8 personality
rows (role_frequency_modifiers, disposition_modifiers, price_modifier, description).
"""

import json
from pathlib import Path

import pytest

import settlement_templates
from settlement_templates import (
    get_settlement_personality,
    get_settlement_tier,
    is_loaded,
    parse_settlement_template_row,
    set_settlement_templates,
)

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "settlement_templates.json"
_RAW = json.loads(_CONTENT_PATH.read_text())

_ARCHETYPE_PATH = Path(__file__).resolve().parents[3] / "content" / "role_archetypes.json"
_ARCHETYPE_IDS = {e["id"] for e in json.loads(_ARCHETYPE_PATH.read_text())}

_TIER_IDS = {"hamlet", "village", "town", "city"}
_PERSONALITY_IDS = {
    "prosperous",
    "struggling",
    "military",
    "scholarly",
    "corrupt",
    "devout",
    "frontier",
    "refuge",
}


def _row(rid: str) -> dict:
    return next(e for e in _RAW if e["id"] == rid)


def _catalog() -> tuple[dict, dict]:
    tiers: dict[str, dict] = {}
    personalities: dict[str, dict] = {}
    for e in _RAW:
        row = parse_settlement_template_row(e["id"], e)
        (tiers if e["kind"] == "tier" else personalities)[e["id"]] = row
    return tiers, personalities


class TestCardinality:
    def test_four_tiers_and_eight_personalities(self):
        tiers = {e["id"] for e in _RAW if e["kind"] == "tier"}
        personalities = {e["id"] for e in _RAW if e["kind"] == "personality"}
        assert tiers == _TIER_IDS
        assert personalities == _PERSONALITY_IDS
        assert len(_RAW) == 12

    def test_ids_unique(self):
        ids = [e["id"] for e in _RAW]
        assert len(ids) == len(set(ids))


class TestParse:
    def test_all_rows_parse(self):
        parsed = [parse_settlement_template_row(e["id"], e) for e in _RAW]
        assert len(parsed) == 12

    def test_tier_role_count_keys_reference_real_archetypes(self):
        for e in (r for r in _RAW if r["kind"] == "tier"):
            for role_id in e["role_counts"]:
                assert role_id in _ARCHETYPE_IDS, f"tier {e['id']} role_counts references unknown archetype {role_id!r}"

    def test_personality_modifier_keys_reference_real_archetypes(self):
        for e in (r for r in _RAW if r["kind"] == "personality"):
            for field in ("role_frequency_modifiers", "disposition_modifiers"):
                for role_id in e[field]:
                    assert role_id in _ARCHETYPE_IDS, (
                        f"personality {e['id']}.{field} references unknown archetype {role_id!r}"
                    )

    def test_corrupt_pins(self):
        # AC for story-003: Corrupt raises Fence/Black-Market frequency + lowers Guard disposition.
        corrupt = parse_settlement_template_row("corrupt", _row("corrupt"))
        assert corrupt["role_frequency_modifiers"]["fence"] >= 1
        assert corrupt["role_frequency_modifiers"]["merchant_black_market"] >= 1
        assert corrupt["disposition_modifiers"]["guard"] == -1

    def test_unknown_kind_fails_loud(self):
        bad = {"id": "weird", "kind": "metropolis", "role_counts": {}}
        with pytest.raises(ValueError, match="weird"):
            parse_settlement_template_row("weird", bad)

    def test_tier_max_below_min_fails_loud(self):
        bad = {**_row("village"), "role_counts": {"guard": {"min": 4, "max": 2}}}
        with pytest.raises(ValueError, match="village"):
            parse_settlement_template_row("village", bad)

    def test_tier_missing_role_counts_fails_loud(self):
        bad = {k: v for k, v in _row("village").items() if k != "role_counts"}
        with pytest.raises(ValueError, match="village"):
            parse_settlement_template_row("village", bad)

    def test_personality_missing_field_fails_loud(self):
        bad = {k: v for k, v in _row("corrupt").items() if k != "price_modifier"}
        with pytest.raises(ValueError, match="corrupt"):
            parse_settlement_template_row("corrupt", bad)

    def test_non_int_count_fails_loud(self):
        bad = {**_row("village"), "role_counts": {"guard": {"min": "two", "max": 4}}}
        with pytest.raises(ValueError, match="village"):
            parse_settlement_template_row("village", bad)


class TestAccessors:
    def test_get_returns_loaded(self):
        set_settlement_templates(*_catalog())
        assert is_loaded()
        assert get_settlement_tier("city")["kind"] == "tier"
        assert get_settlement_personality("corrupt")["kind"] == "personality"

    def test_unknown_tier_fails_loud(self):
        set_settlement_templates(*_catalog())
        with pytest.raises(ValueError, match="keldaran_hold"):
            get_settlement_tier("keldaran_hold")

    def test_unknown_personality_fails_loud(self):
        set_settlement_templates(*_catalog())
        with pytest.raises(ValueError, match="bogus"):
            get_settlement_personality("bogus")

    def test_set_seam_isolates_catalog(self):
        tiers, personalities = _catalog()
        set_settlement_templates({"city": tiers["city"]}, {"corrupt": personalities["corrupt"]})
        assert is_loaded()
        assert get_settlement_tier("city")["id"] == "city"
        with pytest.raises(ValueError):
            get_settlement_tier("village")
        # restore the full catalog for any later test in this module
        set_settlement_templates(*_catalog())

    def test_module_globals_present(self):
        assert hasattr(settlement_templates, "load_settlement_templates")
