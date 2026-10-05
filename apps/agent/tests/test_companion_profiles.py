"""The loader tests isolate parsing and scaling; stored loading needs real Postgres."""

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
    select_companion_for_archetype,
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

    def test_ability_bucket_cardinality(self):
        for e in _RAW:
            c = parse_companion_row(e["id"], e)
            assert 2 <= len(c.attacks) <= 4, f"{c.id} attacks"
            assert 2 <= len(c.passives) <= 3, f"{c.id} passives"
            assert 2 <= len(c.actives) <= 3, f"{c.id} actives"
            assert len(c.reactions) <= 1, f"{c.id} reactions"

    def test_every_row_declares_errand_injury_reduction(self):
        parsed = {e["id"]: parse_companion_row(e["id"], e) for e in _RAW}
        assert parsed["companion_kael"].errand_injury_reduction == 5
        assert {c.errand_injury_reduction for cid, c in parsed.items() if cid != "companion_kael"} == {0}

    def test_missing_errand_injury_reduction_rejects(self):
        row = {k: v for k, v in _row("companion_lira").items() if k != "errand_injury_reduction"}
        with pytest.raises(ValueError):
            parse_companion_row("companion_lira", row)

    def test_every_row_declares_a_known_gender(self):
        """Sable selection must not depend on gender."""
        for e in _RAW:
            c = parse_companion_row(e["id"], e)
            assert c.gender in {"male", "female", "nonbinary"}, f"{c.id}.gender {c.gender!r}"

    def test_missing_gender_rejects(self):
        row = {k: v for k, v in _row("companion_sable").items() if k != "gender"}
        with pytest.raises(ValueError):
            parse_companion_row("companion_sable", row)

    def test_sable_non_verbal(self):
        sable = parse_companion_row("companion_sable", _row("companion_sable"))
        assert sable.non_verbal is True
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
        for cid in _IDS:
            assert get_companion_profile(cid).id == cid

    def test_is_loaded(self):
        assert is_loaded() is True

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown companion"):
            get_companion_profile("companion_nobody")


class TestScaling:
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
        """An empty registered voice intentionally falls back to the narrator."""
        from voices import VOICES

        for cid in _IDS:
            voice_id = get_companion_profile(cid).voice_id
            assert voice_id in VOICES, (
                f"{cid} voice_id {voice_id!r} not in voices.VOICES -> would fall back to DM_NARRATOR"
            )


class TestActionPool:
    """Parsed governing attributes drive hit math; ranged delivery retains its range meaning."""

    def test_kael_melee_attacks(self):
        kael = get_companion_profile("companion_kael")
        pool = companion_attacks_to_action_pool(kael)
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
        assert pool == [
            {
                "name": "Arcane Bolt",
                "damage": "1d6",
                "damage_type": "force",
                "properties": [],
                "governing_attribute": "intelligence",
                "ranged": True,
            },
            {
                "name": "Radiant Mote",
                "damage": "1d4",
                "damage_type": "radiant",
                "properties": [],
                "governing_attribute": "intelligence",
                "ranged": True,
            },
        ]

    def test_tam_mixed_melee_and_ranged(self):
        tam = get_companion_profile("companion_tam")
        pool = companion_attacks_to_action_pool(tam)
        by_name = {a["name"]: a for a in pool}
        assert by_name["Short Sword"].get("ranged") is None  # melee -> no ranged key
        assert by_name["Shortbow"]["ranged"] is True
        assert by_name["Short Sword"]["damage"] == "1d6"  # +DEX stripped
        assert by_name["Short Sword"]["governing_attribute"] == "dexterity"
        assert by_name["Shortbow"]["governing_attribute"] == "dexterity"

    def test_every_companion_attack_yields_a_dice_term(self):
        for cid in _IDS:
            pool = companion_attacks_to_action_pool(get_companion_profile(cid))
            for action in pool:
                assert action["damage"], f"{cid} {action['name']} lost its dice term"

    def test_malformed_damage_without_dice_term_raises(self):
        broken = copy.deepcopy(_row("companion_kael"))
        broken["attacks"][0]["damage"] = "STR"
        bad_profile = parse_companion_row("companion_kael", broken)
        with pytest.raises(ValueError, match="damage"):
            companion_attacks_to_action_pool(bad_profile)

    def test_malformed_hit_without_attribute_raises(self):
        broken = copy.deepcopy(_row("companion_kael"))
        broken["attacks"][0]["hit"] = "prof"
        bad_profile = parse_companion_row("companion_kael", broken)
        with pytest.raises(ValueError, match="hit"):
            companion_attacks_to_action_pool(bad_profile)


class TestLoader:
    async def test_load_does_not_wipe_catalog_on_bad_row(self, monkeypatch):
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


_ARCHETYPES_PATH = Path(__file__).resolve().parents[3] / "content" / "archetypes.json"
_ARCHETYPE_IDS = sorted(e["id"] for e in json.loads(_ARCHETYPES_PATH.read_text()))

_EXPECTED = {a: e["id"] for e in _RAW for a in e["complements"]}


def _catalog_with(complements_by_id: dict[str, list[str]]) -> dict[str, Companion]:
    """Fixture catalog with the given companions' `complements` overridden."""
    return {
        e["id"]: parse_companion_row(e["id"], {**e, "complements": complements_by_id.get(e["id"], e["complements"])})
        for e in _RAW
    }


class TestSelectCompanionForArchetype:
    def test_complements_partition_the_archetypes(self):
        listed = [a for e in _RAW for a in e["complements"]]
        assert sorted(listed) == _ARCHETYPE_IDS
        assert len(listed) == len(set(listed))

    @pytest.mark.parametrize("archetype_id", _ARCHETYPE_IDS)
    def test_every_archetype_selects_its_one_companion(self, archetype_id):
        assert select_companion_for_archetype(archetype_id) == _EXPECTED[archetype_id]

    def test_zero_match_fails_loud(self):
        kael = [a for a in _row("companion_kael")["complements"] if a != "mage"]
        set_companion_profiles(_catalog_with({"companion_kael": kael}))
        with pytest.raises(ValueError, match="mage"):
            select_companion_for_archetype("mage")

    def test_multi_match_fails_loud(self):
        lira = [*_row("companion_lira")["complements"], "mage"]
        set_companion_profiles(_catalog_with({"companion_lira": lira}))
        with pytest.raises(ValueError, match="mage") as exc:
            select_companion_for_archetype("mage")
        assert "companion_kael" in str(exc.value) and "companion_lira" in str(exc.value)

    def test_unknown_archetype_fails_loud(self):
        with pytest.raises(ValueError, match="necromancer"):
            select_companion_for_archetype("necromancer")
