"""Tests for the companion profiles loader + scaler (Phase 6 M6.4 / story-002).

The loader mirrors role_archetypes.py: fail-loud parse of content/companions.json into frozen
Companion dataclasses, a module-global dict with a set_* test seam, and a build-then-swap async
DB loader. companion_scaling.scale_companion_stats_to_player_level is the pure level-scaler.
These tests own the parse + accessor + scaling contract; the real-DB load is exercised by the
story-005 capstone.
"""

import copy
import json
from pathlib import Path

import pytest

import companion_profiles
from companion_profiles import (
    Companion,
    get_companion_profile,
    is_loaded,
    load_companion_profiles,
    parse_companion_row,
    set_companion_profiles,
)
from companion_scaling import scale_companion_stats_to_player_level
from hp_scaling import calculate_max_hp

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "companions.json"
_RAW = json.loads(_CONTENT_PATH.read_text())

_IDS = {"companion_kael", "companion_lira", "companion_tam", "companion_sable"}


def _row(rid: str) -> dict:
    return next(e for e in _RAW if e["id"] == rid)


class TestParse:
    def test_all_4_rows_parse(self):
        parsed = [parse_companion_row(e["id"], e) for e in _RAW]
        assert len(parsed) == 4
        assert all(isinstance(c, Companion) for c in parsed)

    def test_ids(self):
        assert {e["id"] for e in _RAW} == _IDS

    def test_save_proficiencies_exactly_two(self):
        for e in _RAW:
            c = parse_companion_row(e["id"], e)
            assert len(c.save_proficiencies) == 2

    def test_sable_non_verbal_with_palette(self):
        sable = parse_companion_row("companion_sable", _row("companion_sable"))
        assert sable.non_verbal is True
        assert sable.sound_palette is not None and len(sable.sound_palette) == 6
        assert sable.reactions == ()

    def test_bad_disposition_raises(self):
        bad = copy.deepcopy(_row("companion_kael"))
        bad["default_disposition"] = "smitten"
        with pytest.raises(ValueError, match="default_disposition"):
            parse_companion_row("companion_kael", bad)

    def test_bad_tactical_preference_raises(self):
        bad = copy.deepcopy(_row("companion_kael"))
        bad["tactical_preference"] = "berserk"
        with pytest.raises(ValueError, match="tactical_preference"):
            parse_companion_row("companion_kael", bad)

    def test_wrong_save_count_raises(self):
        bad = copy.deepcopy(_row("companion_kael"))
        bad["save_proficiencies"] = ["strength"]
        with pytest.raises(ValueError, match="exactly 2"):
            parse_companion_row("companion_kael", bad)

    def test_bad_attribute_scaling_target_raises(self):
        bad = copy.deepcopy(_row("companion_kael"))
        bad["scaling_rules"]["attribute_scaling"][0]["attribute"] = "luck"
        with pytest.raises(ValueError, match="attribute"):
            parse_companion_row("companion_kael", bad)

    def test_missing_field_raises_with_row_id(self):
        bad = copy.deepcopy(_row("companion_kael"))
        del bad["base_attributes"]
        with pytest.raises(ValueError, match="companion_kael"):
            parse_companion_row("companion_kael", bad)


class TestAccessor:
    def test_get_returns_each_companion(self):
        # autouse fixture seeds the catalog from content
        for cid in _IDS:
            assert get_companion_profile(cid).id == cid

    def test_is_loaded(self):
        assert is_loaded() is True

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown companion"):
            get_companion_profile("companion_nobody")


class TestScaling:
    # A representative player line: warrior chassis, CON +2.
    ARCHETYPE = "warrior"
    CON_MOD = 2
    LEVELS = (1, 5, 10, 15, 20)

    def test_hp_is_fraction_of_player_max_hp(self):
        from math import floor

        for cid in _IDS:
            comp = get_companion_profile(cid)
            factor = comp.scaling_rules.hp_factor
            for level in self.LEVELS:
                player_hp = calculate_max_hp(self.ARCHETYPE, level, self.CON_MOD)
                scaled = scale_companion_stats_to_player_level(comp, player_hp, level)
                assert scaled.hp == floor(player_hp * factor), f"{cid} L{level}"

    def test_hp_factors_match_spec(self):
        assert get_companion_profile("companion_kael").scaling_rules.hp_factor == 0.75
        assert get_companion_profile("companion_lira").scaling_rules.hp_factor == 0.75
        assert get_companion_profile("companion_tam").scaling_rules.hp_factor == 0.75
        assert get_companion_profile("companion_sable").scaling_rules.hp_factor == 0.5

    def test_kael_ac_threshold_steps_at_l10(self):
        kael = get_companion_profile("companion_kael")
        # Kael: AC 15 base, 17 at L10+.
        assert scale_companion_stats_to_player_level(kael, 100, 1).ac == 15
        assert scale_companion_stats_to_player_level(kael, 100, 9).ac == 15
        assert scale_companion_stats_to_player_level(kael, 100, 10).ac == 17
        assert scale_companion_stats_to_player_level(kael, 100, 20).ac == 17

    def test_sable_flat_ac(self):
        sable = get_companion_profile("companion_sable")
        for level in self.LEVELS:
            assert scale_companion_stats_to_player_level(sable, 100, level).ac == 14

    def test_kael_strength_accumulates(self):
        kael = get_companion_profile("companion_kael")
        # Base STR 15; +1 at L4, +1 at L12.
        assert scale_companion_stats_to_player_level(kael, 100, 1).attributes["strength"] == 15
        assert scale_companion_stats_to_player_level(kael, 100, 4).attributes["strength"] == 16
        assert scale_companion_stats_to_player_level(kael, 100, 12).attributes["strength"] == 17

    def test_scaling_does_not_mutate_base_attributes(self):
        kael = get_companion_profile("companion_kael")
        before = dict(kael.base_attributes)
        scale_companion_stats_to_player_level(kael, 100, 20)
        assert kael.base_attributes == before


class TestLoader:
    async def test_load_does_not_wipe_catalog_on_bad_row(self, monkeypatch):
        """A malformed DB row fails loud WITHOUT wiping the already-loaded catalog (atomic swap)."""
        import db

        class _BadPool:
            async def fetch(self, _query):
                return [{"id": "companion_broken", "data": {"name": "Broken"}}]

        async def _fake_get_pool():
            return _BadPool()

        monkeypatch.setattr(db, "get_pool", _fake_get_pool)
        assert is_loaded()  # seeded by the autouse fixture
        with pytest.raises(ValueError, match="companion_broken"):
            await load_companion_profiles()
        # catalog intact — the swap never happened
        assert get_companion_profile("companion_kael").name == "Kael"

    async def test_load_populates_from_pool(self, monkeypatch):
        import db

        rows = [{"id": e["id"], "data": e} for e in _RAW]

        class _GoodPool:
            async def fetch(self, _query):
                return rows

        async def _fake_get_pool():
            return _GoodPool()

        set_companion_profiles({})
        assert not is_loaded()
        monkeypatch.setattr(db, "get_pool", _fake_get_pool)
        await load_companion_profiles()
        assert {c for c in _IDS} <= set(companion_profiles._companion_profiles.keys())
