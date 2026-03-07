"""Tests for character creation rules — pure functions, deterministic."""

import json

import pytest

from creation_data import CLASSES, DEITIES, RACES
from creation_rules import (
    BASE_ATTRIBUTE,
    CULTURE_START_LOCATIONS,
    build_character_data,
    calculate_ac,
    calculate_starting_hp,
    generate_attributes,
    get_skill_proficiencies,
    get_starting_equipment,
    get_starting_location,
    infer_culture,
)

# --- Race attribute bonuses ---


class TestRaceAttributes:
    def test_draethar_bonuses(self):
        attrs = generate_attributes("draethar", "warrior")
        assert attrs["strength"] == BASE_ATTRIBUTE + 2
        assert attrs["constitution"] == BASE_ATTRIBUTE + 1

    def test_elari_bonuses(self):
        attrs = generate_attributes("elari", "mage")
        assert attrs["intelligence"] == BASE_ATTRIBUTE + 2
        assert attrs["wisdom"] == BASE_ATTRIBUTE + 1

    def test_korath_bonuses(self):
        attrs = generate_attributes("korath", "guardian")
        assert attrs["constitution"] == BASE_ATTRIBUTE + 2
        assert attrs["strength"] == BASE_ATTRIBUTE + 1

    def test_vaelti_bonuses(self):
        attrs = generate_attributes("vaelti", "rogue")
        assert attrs["dexterity"] == BASE_ATTRIBUTE + 2
        assert attrs["wisdom"] == BASE_ATTRIBUTE + 1

    def test_thessyn_adaptive_bonus_strength(self):
        """Thessyn gets +1 DEX, +1 CHA from race, +1 to class primary attr."""
        attrs = generate_attributes("thessyn", "warrior")
        assert attrs["dexterity"] == BASE_ATTRIBUTE + 1  # race
        assert attrs["charisma"] == BASE_ATTRIBUTE + 1  # race
        assert attrs["strength"] == BASE_ATTRIBUTE + 1  # adaptive (warrior primary)

    def test_thessyn_adaptive_bonus_intelligence(self):
        attrs = generate_attributes("thessyn", "mage")
        assert attrs["intelligence"] == BASE_ATTRIBUTE + 1  # adaptive (mage primary)
        assert attrs["dexterity"] == BASE_ATTRIBUTE + 1  # race
        assert attrs["charisma"] == BASE_ATTRIBUTE + 1  # race

    def test_human_plus_one_all(self):
        attrs = generate_attributes("human", "warrior")
        for attr_name in ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"):
            assert attrs[attr_name] == BASE_ATTRIBUTE + 1, f"{attr_name} should be {BASE_ATTRIBUTE + 1}"

    @pytest.mark.parametrize("race_id", list(RACES.keys()))
    def test_all_races_produce_valid_attributes(self, race_id):
        attrs = generate_attributes(race_id, "warrior")
        assert len(attrs) == 6
        for attr_name in ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"):
            assert attr_name in attrs
            assert attrs[attr_name] >= BASE_ATTRIBUTE  # bonuses only add


# --- Class HP, equipment, proficiencies ---


class TestClassMechanics:
    @pytest.mark.parametrize("class_id", list(CLASSES.keys()))
    def test_starting_hp(self, class_id):
        cls = CLASSES[class_id]
        hp = calculate_starting_hp(class_id, 10)  # CON 10 = +0 modifier
        assert hp["current"] == cls.hit_die
        assert hp["max"] == cls.hit_die
        assert hp["current"] == hp["max"]

    @pytest.mark.parametrize("class_id", list(CLASSES.keys()))
    def test_starting_hp_with_high_con(self, class_id):
        cls = CLASSES[class_id]
        hp = calculate_starting_hp(class_id, 14)  # CON 14 = +2 modifier
        assert hp["current"] == cls.hit_die + 2
        assert hp["max"] == cls.hit_die + 2

    def test_starting_hp_minimum_one(self):
        # A class with d6 and CON 1 (-5 modifier) should still have 1 HP
        hp = calculate_starting_hp("mage", 1)
        assert hp["current"] >= 1
        assert hp["max"] >= 1

    @pytest.mark.parametrize("class_id", list(CLASSES.keys()))
    def test_starting_equipment_shape(self, class_id):
        equip = get_starting_equipment(class_id)
        assert "main_hand" in equip
        assert "armor" in equip
        assert "shield" in equip

    @pytest.mark.parametrize("class_id", list(CLASSES.keys()))
    def test_skill_proficiencies_count(self, class_id):
        cls = CLASSES[class_id]
        profs = get_skill_proficiencies(class_id)
        assert len(profs) == cls.num_skill_choices

    @pytest.mark.parametrize("class_id", list(CLASSES.keys()))
    def test_skill_proficiencies_from_pool(self, class_id):
        cls = CLASSES[class_id]
        profs = get_skill_proficiencies(class_id)
        for p in profs:
            assert p in cls.skill_options, f"{p} not in {cls.skill_options}"


# --- AC calculation ---


class TestACCalculation:
    def test_no_armor(self):
        ac = calculate_ac({"armor": None, "shield": None}, 14)  # DEX 14 = +2
        assert ac == 12

    def test_light_armor(self):
        ac = calculate_ac({"armor": {"ac_bonus": 11}, "shield": None}, 14)
        assert ac == 13  # 11 + 2

    def test_medium_armor_dex_cap(self):
        ac = calculate_ac({"armor": {"ac_bonus": 12}, "shield": None}, 18)  # DEX +4, capped at +2
        assert ac == 14  # 12 + 2

    def test_heavy_armor_no_dex(self):
        ac = calculate_ac({"armor": {"ac_bonus": 15}, "shield": None}, 18)
        assert ac == 15  # no dex bonus

    def test_shield_adds_bonus(self):
        ac = calculate_ac({"armor": {"ac_bonus": 13}, "shield": {"ac_bonus": 1}}, 12)
        assert ac == 15  # 13 + 1 (dex) + 1 (shield)


# --- build_character_data ---


class TestBuildCharacterData:
    def test_output_shape(self):
        data = build_character_data(
            name="Aric",
            race_id="human",
            class_id="warrior",
            deity_id="kaelen",
            backstory="A wandering sellsword.",
        )
        required_keys = {
            "name",
            "race",
            "class",
            "level",
            "xp",
            "location_id",
            "attributes",
            "hp",
            "ac",
            "proficiencies",
            "saving_throw_proficiencies",
            "equipment",
            "inventory",
            "gold",
            "backstory",
            "deity",
            "culture",
            "divine_favor",
        }
        assert required_keys.issubset(data.keys())

    def test_divine_favor_with_deity(self):
        data = build_character_data("Aric", "human", "warrior", "kaelen", "Test.")
        favor = data["divine_favor"]
        assert favor["patron"] == "kaelen"
        assert favor["level"] == 0
        assert favor["max"] == 100
        assert favor["last_whisper_level"] == 0

    def test_divine_favor_without_deity(self):
        data = build_character_data("Aric", "human", "warrior", None, "Test.")
        favor = data["divine_favor"]
        assert favor["patron"] == "none"

    def test_divine_favor_explicit_none(self):
        data = build_character_data("Aric", "human", "warrior", "none", "Test.")
        favor = data["divine_favor"]
        assert favor["patron"] == "none"

    def test_name_preserved(self):
        data = build_character_data("Aric", "human", "warrior", "kaelen", "Test.")
        assert data["name"] == "Aric"

    def test_race_and_class_stored(self):
        data = build_character_data("Aric", "draethar", "guardian", "valdris", "Test.")
        assert data["race"] == "draethar"
        assert data["class"] == "guardian"

    def test_level_one(self):
        data = build_character_data("Aric", "human", "warrior", None, "Test.")
        assert data["level"] == 1
        assert data["xp"] == 0

    def test_deity_stored(self):
        data = build_character_data("Aric", "human", "cleric", "orenthel", "Test.")
        assert data["deity"] == "orenthel"

    def test_deferred_deity_none(self):
        data = build_character_data("Aric", "human", "warrior", None, "Test.")
        assert data["deity"] is None

    def test_deity_none_explicit(self):
        data = build_character_data("Aric", "human", "warrior", "none", "Test.")
        assert data["deity"] == "none"

    def test_backstory_stored(self):
        data = build_character_data("Aric", "human", "warrior", None, "Born in the Accord.")
        assert data["backstory"] == "Born in the Accord."

    def test_gold_matches_class(self):
        for class_id, cls in CLASSES.items():
            data = build_character_data("Test", "human", class_id, None, "Test.")
            assert data["gold"] == cls.starting_gold

    def test_saving_throws_match_class(self):
        for class_id, cls in CLASSES.items():
            data = build_character_data("Test", "human", class_id, None, "Test.")
            assert data["saving_throw_proficiencies"] == list(cls.saving_throw_proficiencies)

    def test_invalid_race_raises(self):
        with pytest.raises(ValueError, match="Unknown race"):
            build_character_data("Aric", "invalid_race", "warrior", None, "Test.")

    def test_invalid_class_raises(self):
        with pytest.raises(ValueError, match="Unknown class"):
            build_character_data("Aric", "human", "invalid_class", None, "Test.")

    def test_invalid_deity_raises(self):
        with pytest.raises(ValueError, match="Unknown deity"):
            build_character_data("Aric", "human", "warrior", "fake_god", "Test.")

    def test_custom_skill_choices(self):
        data = build_character_data(
            "Aric",
            "human",
            "rogue",
            None,
            "Test.",
            skill_choices=["stealth", "perception", "investigation", "insight"],
        )
        assert data["proficiencies"] == ["stealth", "perception", "investigation", "insight"]

    def test_json_serializable(self):
        data = build_character_data("Aric", "human", "warrior", "kaelen", "Test.")
        serialized = json.dumps(data)
        roundtripped = json.loads(serialized)
        assert roundtripped == data


# --- Culture inference ---


class TestCultureInference:
    def test_elari_arcane_veythar(self):
        cultures = infer_culture("elari", "mage", "veythar")
        assert "aelindran_diaspora" in cultures[:2]

    def test_draethar_martial_kaelen(self):
        cultures = infer_culture("draethar", "warrior", "kaelen")
        assert "drathian_clans" in cultures[:2]

    def test_korath_any_aelora(self):
        cultures = infer_culture("korath", "artificer", "aelora")
        assert "keldaran_holds" in cultures[:2]

    def test_human_any_none_default(self):
        cultures = infer_culture("human", "warrior", None)
        assert len(cultures) >= 1

    def test_vaelti_shadow_syrath(self):
        cultures = infer_culture("vaelti", "rogue", "syrath")
        assert "marsh_kindred" in cultures[:2]

    def test_divine_class_orenthel(self):
        cultures = infer_culture("human", "cleric", "orenthel")
        assert "dawnsworn" in cultures[:2]

    def test_primal_thyra(self):
        cultures = infer_culture("elari", "druid", "thyra")
        assert "thornwardens" in cultures[:2]

    def test_thessyn_nythera(self):
        cultures = infer_culture("thessyn", "beastcaller", "nythera")
        assert "tidecallers" in cultures[:2]

    def test_returns_one_to_three(self):
        cultures = infer_culture("human", "warrior", None)
        assert 1 <= len(cultures) <= 3

    @pytest.mark.parametrize("race_id", list(RACES.keys()))
    def test_all_races_produce_valid_culture(self, race_id):
        cultures = infer_culture(race_id, "warrior", None)
        assert len(cultures) >= 1
        for c in cultures:
            assert c in CULTURE_START_LOCATIONS

    @pytest.mark.parametrize(
        "race_id,class_id,deity_id",
        [
            ("human", "warrior", "kaelen"),
            ("elari", "mage", "veythar"),
            ("korath", "guardian", "valdris"),
            ("vaelti", "rogue", "syrath"),
            ("draethar", "paladin", "kaelen"),
            ("thessyn", "bard", "aelora"),
            ("human", "cleric", "orenthel"),
            ("elari", "druid", "thyra"),
            ("vaelti", "spy", "syrath"),
            ("thessyn", "oracle", "zhael"),
            ("human", "diplomat", None),
            ("draethar", "warden", "thyra"),
            ("korath", "artificer", "aelora"),
            ("human", "seeker", "veythar"),
            ("elari", "whisper", "syrath"),
            ("vaelti", "beastcaller", "nythera"),
            ("thessyn", "skirmisher", "kaelen"),
            ("human", "mage", "none"),
            ("draethar", "warrior", None),
            ("korath", "cleric", "mortaen"),
        ],
    )
    def test_culture_inference_parameterized(self, race_id, class_id, deity_id):
        cultures = infer_culture(race_id, class_id, deity_id)
        assert 1 <= len(cultures) <= 3
        for c in cultures:
            assert c in CULTURE_START_LOCATIONS


# --- Starting locations ---


class TestStartingLocations:
    @pytest.mark.parametrize("culture_id", list(CULTURE_START_LOCATIONS.keys()))
    def test_all_cultures_have_valid_start(self, culture_id):
        loc = get_starting_location(culture_id)
        assert isinstance(loc, str)
        assert len(loc) > 0

    def test_unknown_culture_defaults(self):
        loc = get_starting_location("nonexistent_culture")
        assert loc == "accord_market_square"


# --- Data integrity ---


class TestDataIntegrity:
    def test_six_races(self):
        assert len(RACES) == 6

    def test_seventeen_classes(self):
        assert len(CLASSES) == 17

    def test_eleven_deities(self):
        # 10 gods + "none"
        assert len(DEITIES) == 11

    def test_all_class_categories(self):
        categories = {c.category for c in CLASSES.values()}
        assert categories == {"martial", "arcane", "primal", "divine", "shadow", "support"}

    def test_all_deity_synergy_classes_valid(self):
        for deity_id, deity in DEITIES.items():
            for cls_id in deity.synergy_classes:
                assert cls_id in CLASSES, f"Deity {deity_id} synergy class {cls_id} not in CLASSES"

    def test_all_class_primary_attributes_valid(self):
        valid_attrs = {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}
        for class_id, cls in CLASSES.items():
            assert cls.primary_attribute in valid_attrs, f"{class_id} has invalid primary attr"

    def test_all_class_saving_throws_valid(self):
        valid_attrs = {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}
        for class_id, cls in CLASSES.items():
            for st in cls.saving_throw_proficiencies:
                assert st in valid_attrs, f"{class_id} has invalid saving throw {st}"

    @pytest.mark.parametrize(
        "race_id,class_id",
        [(r, c) for r in RACES for c in CLASSES],
    )
    def test_every_race_class_combo_builds(self, race_id, class_id):
        """Every race + class combination produces a valid character."""
        data = build_character_data(
            name="TestChar",
            race_id=race_id,
            class_id=class_id,
            deity_id=None,
            backstory="Test backstory.",
        )
        assert data["name"] == "TestChar"
        assert data["level"] == 1
        assert data["hp"]["current"] >= 1
        assert data["ac"] >= 10
        assert len(data["proficiencies"]) > 0
