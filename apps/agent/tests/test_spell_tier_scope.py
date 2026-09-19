import pytest
from archetypes_config_fixture import load_archetype_rows

from archetypes import parse_archetype_row
from leveling import SPELL_TIERS, is_spell_tier_unlocked, min_level_for_tier

DEFAULT_CASTER_FLOORS: dict[str, int | None] = {
    "cantrip": 1,
    "minor": 1,
    "standard": 3,
    "major": 5,
    "supreme": 9,
}
EXPECTED_TIER_FLOORS: dict[str, dict[str, int | None]] = {
    "mage": DEFAULT_CASTER_FLOORS,
    "artificer": DEFAULT_CASTER_FLOORS,
    "seeker": DEFAULT_CASTER_FLOORS,
    "druid": DEFAULT_CASTER_FLOORS,
    "beastcaller": DEFAULT_CASTER_FLOORS,
    "warden": DEFAULT_CASTER_FLOORS,
    "cleric": DEFAULT_CASTER_FLOORS,
    "oracle": DEFAULT_CASTER_FLOORS,
    "bard": {"cantrip": 1, "minor": 1, "standard": 3, "major": 5, "supreme": 10},
    "paladin": {"cantrip": None, "minor": 3, "standard": 5, "major": 9, "supreme": None},
    "diplomat": {"cantrip": None, "minor": 3, "standard": 5, "major": 9, "supreme": None},
    "marshal": {"cantrip": None, "minor": 3, "standard": 5, "major": 9, "supreme": None},
    "whisper": {"cantrip": None, "minor": 1, "standard": 4, "major": 7, "supreme": 13},
}


class TestSpellTierGate:
    def test_every_authored_archetype_and_tier_matches_spec(self) -> None:
        rows = load_archetype_rows()
        parsed = {row["id"]: parse_archetype_row(row["id"], row) for row in rows}
        assert len(parsed) == len(rows)
        assert {row.id for row in parsed.values() if row.magic_source is not None} == set(EXPECTED_TIER_FLOORS)
        checked = set()

        for archetype_id, chassis in parsed.items():
            for tier in SPELL_TIERS:
                checked.add((archetype_id, tier))
                if chassis.magic_source is None:
                    with pytest.raises(ValueError, match="spellcasting archetype"):
                        min_level_for_tier(archetype_id, tier)
                    with pytest.raises(ValueError, match="spellcasting archetype"):
                        is_spell_tier_unlocked(archetype_id, tier, 20)
                    continue
                floor = EXPECTED_TIER_FLOORS[archetype_id][tier]
                assert min_level_for_tier(archetype_id, tier) == floor
                if floor is None:
                    assert is_spell_tier_unlocked(archetype_id, tier, 1) is False
                    assert is_spell_tier_unlocked(archetype_id, tier, 20) is False
                else:
                    assert is_spell_tier_unlocked(archetype_id, tier, floor) is True
                    if floor > 1:
                        assert is_spell_tier_unlocked(archetype_id, tier, floor - 1) is False

        assert checked == {(row["id"], tier) for row in rows for tier in SPELL_TIERS}
        assert len(checked) == len(rows) * len(SPELL_TIERS)

    def test_spell_tiers_vocab_is_the_five_canonical_tiers(self) -> None:
        assert frozenset({"cantrip", "minor", "standard", "major", "supreme"}) == SPELL_TIERS

    def test_unknown_tier_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="tier"):
            is_spell_tier_unlocked("mage", "legendary", 20)
        with pytest.raises(ValueError, match="tier"):
            min_level_for_tier("mage", "legendary")

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda row: row.pop("spell_tier_min_levels", None),
            lambda row: row.update(spell_tier_min_levels={"legendary": 1}),
            lambda row: row.update(spell_tier_min_levels={"minor": True}),
            lambda row: row.update(spell_tier_min_levels={"minor": 1.5}),
            lambda row: row.update(spell_tier_min_levels={"minor": 0}),
            lambda row: row.update(spell_tier_min_levels={"minor": 21}),
            lambda row: row.update(spell_tier_min_levels={}),
        ],
    )
    def test_caster_tier_map_is_required_and_strict(self, mutate) -> None:
        mage = next(dict(row) for row in load_archetype_rows() if row["id"] == "mage")
        mutate(mage)
        with pytest.raises(ValueError, match="spell_tier_min_levels"):
            parse_archetype_row("mage", mage)

    def test_martial_tier_map_must_be_empty(self) -> None:
        warrior = next(dict(row) for row in load_archetype_rows() if row["id"] == "warrior")
        warrior["spell_tier_min_levels"] = {"minor": 1}
        with pytest.raises(ValueError, match="spell_tier_min_levels"):
            parse_archetype_row("warrior", warrior)
