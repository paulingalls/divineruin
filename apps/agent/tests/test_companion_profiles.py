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
from companion_scaling import (
    companion_attacks_to_action_pool,
    scale_companion_stats_to_player_level,
)
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

    def test_sable_non_verbal(self):
        sable = parse_companion_row("companion_sable", _row("companion_sable"))
        assert sable.non_verbal is True
        # sound_palette is owned solely by voice_registry.json now (B1, debt eb08ad17f6e2);
        # the companion entity no longer mirrors it.
        assert not hasattr(sable, "sound_palette")
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


class TestVoiceRegistration:
    def test_every_companion_voice_id_registered_in_voices(self):
        """Every companions.json voice_id must be a key in voices.VOICES (audio-first golden rule).

        get_voice_config does VOICES.get(character, DEFAULT_VOICE), so an unregistered voice_id
        silently falls back to DM_NARRATOR. This includes Sable's COMPANION_SABLE: she is
        non-verbal (empty env default), but the key must exist so the invariant holds uniformly.
        """
        from voices import VOICES

        for cid in _IDS:
            voice_id = get_companion_profile(cid).voice_id
            assert voice_id in VOICES, (
                f"{cid} voice_id {voice_id!r} not in voices.VOICES -> would fall back to DM_NARRATOR"
            )


class TestActionPool:
    """companion_attacks_to_action_pool translates the profile's NARRATIVE attack notation
    (damage "1d8+STR", hit "STR+prof") into the MECHANICAL action dicts the combat resolver
    consumes (plain dice + attributes-supply-the-mod). Attacks only — actives/reactions are
    DM-narrated. The per-attack governing_attribute (derived from the hit field) drives the
    resolver's hit stat (story-008); ranged:True is still emitted for ranged attacks (range/reach
    narration) but no longer determines the hit stat."""

    def test_kael_melee_attacks(self):
        kael = get_companion_profile("companion_kael")
        pool = companion_attacks_to_action_pool(kael)
        # hit "STR+prof" -> governing_attribute strength.
        assert pool == [
            {
                "name": "Longsword",
                "damage": "1d8",
                "damage_type": "slashing",
                "properties": [],
                "governing_attribute": "strength",
            },
            {
                "name": "Shield Bash",
                "damage": "1d4",
                "damage_type": "bludgeoning",
                "properties": [],
                "governing_attribute": "strength",
            },
        ]

    def test_lira_ranged_attack_sets_ranged_flag(self):
        lira = get_companion_profile("companion_lira")
        pool = companion_attacks_to_action_pool(lira)
        # Arcane Bolt is type=ranged -> top-level ranged:True. hit "INT+prof" -> governing INT
        # (the resolver uses INT, NOT the ranged-default DEX). damage strips +INT.
        assert pool == [
            {
                "name": "Arcane Bolt",
                "damage": "1d6",
                "damage_type": "force",
                "properties": [],
                "governing_attribute": "intelligence",
                "ranged": True,
            }
        ]

    def test_tam_mixed_melee_and_ranged(self):
        tam = get_companion_profile("companion_tam")
        pool = companion_attacks_to_action_pool(tam)
        by_name = {a["name"]: a for a in pool}
        assert by_name["Short Sword"].get("ranged") is None  # melee -> no ranged key
        assert by_name["Shortbow"]["ranged"] is True
        assert by_name["Short Sword"]["damage"] == "1d6"  # +DEX stripped
        # Both Tam attacks are DEX (hit "DEX+prof"); the melee short sword resolves on DEX, not STR.
        assert by_name["Short Sword"]["governing_attribute"] == "dexterity"
        assert by_name["Shortbow"]["governing_attribute"] == "dexterity"

    def test_every_companion_attack_yields_a_dice_term(self):
        for cid in _IDS:
            pool = companion_attacks_to_action_pool(get_companion_profile(cid))
            for action in pool:
                assert action["damage"], f"{cid} {action['name']} lost its dice term"

    def test_malformed_damage_without_dice_term_raises(self):
        # A pure-attribute damage expression has no dice/int term to keep -> fail loud.
        broken = copy.deepcopy(_row("companion_kael"))
        broken["attacks"][0]["damage"] = "STR"
        bad_profile = parse_companion_row("companion_kael", broken)
        with pytest.raises(ValueError, match="damage"):
            companion_attacks_to_action_pool(bad_profile)

    def test_malformed_hit_without_attribute_raises(self):
        # A hit expression with no recognized attribute token can't yield a governing stat -> fail loud.
        broken = copy.deepcopy(_row("companion_kael"))
        broken["attacks"][0]["hit"] = "prof"
        bad_profile = parse_companion_row("companion_kael", broken)
        with pytest.raises(ValueError, match="hit"):
            companion_attacks_to_action_pool(bad_profile)


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
