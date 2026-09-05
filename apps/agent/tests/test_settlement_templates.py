"""Tests for the settlement_templates content loader (Phase 6 M6.2 / story-002).

The loader mirrors apps/agent/role_archetypes.py + npcs.py: fail-loud parse of the
content/settlement_templates.json catalog, one module-global dict per kind (_tiers,
_personalities, _name_pools) with a set_* test seam, and a build-then-swap async DB loader. The
catalog is the template SSOT story-003 consumes — get_settlement_tier(size) for role
counts, get_settlement_personality(trait) for modifiers.

Catalog shape: a flat list of self-contained id/JSONB rows discriminated by `kind`:
4 tier rows (id == SettlementSize, role_counts of {min,max} ranges) + 8 personality
rows (role_frequency_modifiers, disposition_modifiers, price_modifier, inventory_modifier,
description) + 1 name_pool row (given names + surnames for generated rosters).
"""

import json
import re
from pathlib import Path

import pytest
from settlement_templates_config_fixture import load_fixture_config

import settlement_templates
from settlement_templates import (
    get_settlement_name_pool,
    get_settlement_personality,
    get_settlement_tier,
    is_loaded,
    parse_settlement_template_row,
    set_settlement_templates,
)
from voices import ROLE_VOICE_KEYS

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "settlement_templates.json"
_RAW = json.loads(_CONTENT_PATH.read_text())

_ARCHETYPE_PATH = Path(__file__).resolve().parents[3] / "content" / "role_archetypes.json"
_ARCHETYPE_IDS = {e["id"] for e in json.loads(_ARCHETYPE_PATH.read_text())}

_CONTENT_DIR = _CONTENT_PATH.parent
# Every word of every authored character name the DM voices. A generated roster name that
# collides with one of these makes the DM say a stranger's line in a known character's name.
# gods.json is in the list because six VOICES keys (GOD_MORTAEN, GOD_NYTHERA, GOD_ORENTHEL,
# GOD_THYRA, GOD_VALDRIS, GOD_ZHAEL) have no voice_registry row — their names live only there.
# The 19 per-role townsfolk voices (ROLE_GUARD, ROLE_MERCHANT_JEWELER, ...) are deliberately
# EXEMPT from all four: a role voice has no character name, so giving it a registry row would
# mean inventing one — enlarging this blocklist and shrinking the very name space generated
# rosters draw from. test_role_voices_have_no_authored_character_row pins the exemption.
_AUTHORED_NAME_FILES = ("voice_registry.json", "npcs.json", "companions.json", "gods.json")
# The three fields these four files key identity on: voice_registry.json has character_id and
# no id; npcs.json and companions.json have id; gods.json has god_id and no id.
_IDENTITY_KEYS = ("character_id", "id", "god_id")


def _identity(entry: dict, filename: str) -> str:
    """The row's identity, fail-loud when none of the three keys is present.

    A .get()-with-falsy-skip here would silently narrow the exemption guard below to
    voice_registry.json alone while it claims to walk all four files — and the injection
    (a ROLE_GUARD row appended to voice_registry.json) would still fire, so the narrowing
    would be invisible. A later schema change must red, not shrink the guard.
    """
    for key in _IDENTITY_KEYS:
        if key in entry:
            return entry[key]
    raise ValueError(f"{filename} row {entry.get('name')!r} has none of {_IDENTITY_KEYS}")


_AUTHORED_NAME_WORDS = {
    word.lower()
    for f in _AUTHORED_NAME_FILES
    for entry in json.loads((_CONTENT_DIR / f).read_text())
    for word in re.findall(r"[A-Za-z']+", entry["name"])
}

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


class TestCardinality:
    def test_four_tiers_eight_personalities_and_one_name_pool(self):
        tiers = {e["id"] for e in _RAW if e["kind"] == "tier"}
        personalities = {e["id"] for e in _RAW if e["kind"] == "personality"}
        name_pools = {e["id"] for e in _RAW if e["kind"] == "name_pool"}
        assert tiers == _TIER_IDS
        assert personalities == _PERSONALITY_IDS
        assert name_pools == {"default_names"}
        assert len(_RAW) == 13

    def test_ids_unique(self):
        ids = [e["id"] for e in _RAW]
        assert len(ids) == len(set(ids))


class TestParse:
    def test_all_rows_parse(self):
        parsed = [parse_settlement_template_row(e["id"], e) for e in _RAW]
        assert len(parsed) == 13

    @pytest.mark.parametrize("field", ["names", "surnames"])
    @pytest.mark.parametrize("values", [[], ["Alden", "Alden"], ["Alden", ""]])
    def test_name_pool_rejects_empty_duplicate_or_blank_names(self, field, values):
        with pytest.raises(ValueError, match=f"default_names.{field}"):
            parse_settlement_template_row("default_names", {**_row("default_names"), field: values})

    @pytest.mark.parametrize("field", ["names", "surnames"])
    def test_name_pool_missing_field_fails_loud(self, field):
        bad = {k: v for k, v in _row("default_names").items() if k != field}
        with pytest.raises(ValueError, match="default_names"):
            parse_settlement_template_row("default_names", bad)

    def test_name_pool_never_collides_with_an_authored_character(self):
        # Kael (the starting companion) and Marek (Bosun Marek Tideborn) both shipped in the
        # first pool; either would have the DM voice a random guard as a known character.
        pool = _row("default_names")
        for generated in (*pool["names"], *pool["surnames"]):
            assert generated.lower() not in _AUTHORED_NAME_WORDS, (
                f"generated name {generated!r} collides with an authored character"
            )

    def test_role_voices_have_no_authored_character_row(self):
        # Role ids are lowercase snake, but these files key on the VOICES-key form
        # (COMPANION_KAEL, GUILDMASTER_TORIN) — which is the shape a role row would take too.
        role_keys = set(ROLE_VOICE_KEYS)
        for filename in _AUTHORED_NAME_FILES:
            for entry in json.loads((_CONTENT_DIR / filename).read_text()):
                identity = _identity(entry, filename)
                assert identity not in role_keys, f"{filename} carries a role-voice row {identity!r}"

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

    def test_inventory_modifier_pins(self):
        # story-003 scope expansion: prosperous = fuller (>1.0), struggling = thinner (<1.0),
        # neutral personalities = 1.0. Forward-wired Phase-9 economy field (debt recorded).
        assert parse_settlement_template_row("prosperous", _row("prosperous"))["inventory_modifier"] > 1.0
        assert parse_settlement_template_row("struggling", _row("struggling"))["inventory_modifier"] < 1.0
        assert parse_settlement_template_row("military", _row("military"))["inventory_modifier"] == 1.0

    def test_personality_missing_inventory_modifier_fails_loud(self):
        bad = {k: v for k, v in _row("corrupt").items() if k != "inventory_modifier"}
        with pytest.raises(ValueError, match="corrupt"):
            parse_settlement_template_row("corrupt", bad)


class TestAccessors:
    def test_get_returns_loaded(self):
        set_settlement_templates(*load_fixture_config())
        assert is_loaded()
        assert get_settlement_tier("city")["kind"] == "tier"
        assert get_settlement_personality("corrupt")["kind"] == "personality"
        assert get_settlement_name_pool("default_names")["kind"] == "name_pool"

    def test_unknown_tier_fails_loud(self):
        set_settlement_templates(*load_fixture_config())
        with pytest.raises(ValueError, match="keldaran_hold"):
            get_settlement_tier("keldaran_hold")

    def test_unknown_personality_fails_loud(self):
        set_settlement_templates(*load_fixture_config())
        with pytest.raises(ValueError, match="bogus"):
            get_settlement_personality("bogus")

    def test_unknown_name_pool_fails_loud(self):
        set_settlement_templates(*load_fixture_config())
        with pytest.raises(ValueError, match="bogus"):
            get_settlement_name_pool("bogus")

    def test_set_seam_isolates_catalog(self):
        tiers, personalities, name_pools = load_fixture_config()
        set_settlement_templates({"city": tiers["city"]}, {"corrupt": personalities["corrupt"]}, name_pools)
        assert is_loaded()
        assert get_settlement_tier("city")["id"] == "city"
        with pytest.raises(ValueError):
            get_settlement_tier("village")
        # restore the full catalog for any later test in this module
        set_settlement_templates(*load_fixture_config())

    def test_catalog_without_name_pool_is_not_loaded(self):
        tiers, personalities, _ = load_fixture_config()
        set_settlement_templates(tiers, personalities, {})
        assert not is_loaded()
        set_settlement_templates(*load_fixture_config())

    def test_module_globals_present(self):
        assert hasattr(settlement_templates, "load_settlement_templates")
