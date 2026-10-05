import conditions
from condition_restrictions import ENFORCED, NOT_ENFORCED, RESTRICTION_ENFORCERS


def _authored_restrictions() -> set[str]:
    catalog = {restriction for spec in conditions.CONDITION_CATALOG.values() for restriction in spec.restrictions}
    return catalog | conditions._hollowed_effects(3)[1]


def _authored_carriers(restriction: str) -> set[str]:
    carriers = {name for name, spec in conditions.CONDITION_CATALOG.items() if restriction in spec.restrictions}
    if restriction in conditions._hollowed_effects(3)[1]:
        carriers.add("hollowed")
    return carriers


def _assert_classified() -> None:
    deferred = set(NOT_ENFORCED)
    assert ENFORCED.isdisjoint(deferred)
    assert _authored_restrictions() == ENFORCED | deferred


def _assert_wait_metadata() -> None:
    for restriction, metadata in NOT_ENFORCED.items():
        assert isinstance(metadata, dict), restriction
        waits_on = metadata.get("waits_on")
        if waits_on == "producer":
            assert set(metadata) == {"waits_on", "carriers"}, restriction
            carriers = metadata["carriers"]
            assert isinstance(carriers, set) and carriers, restriction
            assert all(isinstance(carrier, str) and carrier for carrier in carriers), restriction
            assert carriers == _authored_carriers(restriction), restriction
        elif waits_on == "model":
            assert set(metadata) == {"waits_on", "model"}, restriction
            assert isinstance(metadata["model"], str) and metadata["model"].strip(), restriction
        else:
            raise AssertionError(restriction)


def test_every_authored_restriction_is_enforced_or_reasoned_debt():
    _assert_classified()


def test_every_deferred_restriction_names_what_it_waits_on():
    _assert_wait_metadata()


def test_only_positioning_may_wait_on_a_model():
    model_waiting = {restriction for restriction, metadata in NOT_ENFORCED.items() if metadata["waits_on"] == "model"}

    assert model_waiting == {"no_approach_source"}


def test_every_enforced_restriction_has_a_production_reader():
    for restriction, reader in RESTRICTION_ENFORCERS.items():
        carriers = [
            {"type": name} for name, spec in conditions.CONDITION_CATALOG.items() if restriction in spec.restrictions
        ]
        assert carriers
        contexts = {
            "no_hostile_source": {"target_ids": ["source"], "participant_ids": {"source"}},
            "auto_fail_hearing_perception": {"skill": "perception", "hearing_only": True},
        }
        assert all(reader([{**carrier, "source": "source"}], **contexts.get(restriction, {})) for carrier in carriers)


def test_prone_incoming_modes_are_enforced_only_for_prone():
    for restriction in ("incoming_melee_advantage", "incoming_ranged_disadvantage"):
        carriers = {name for name, spec in conditions.CONDITION_CATALOG.items() if restriction in spec.restrictions}
        assert restriction in ENFORCED
        assert carriers == {"prone"}


def test_grapple_and_speed_restriction_carriers_are_exactly_enforced():
    expected = {
        "costs_declaration": {"prone", "grappled"},
        "speed_0": {"grappled", "restrained"},
    }
    for restriction, expected_carriers in expected.items():
        carriers = {name for name, spec in conditions.CONDITION_CATALOG.items() if restriction in spec.restrictions}
        assert restriction in ENFORCED
        assert carriers == expected_carriers


def test_exact_restriction_partition_and_complete_spoken_corpus():
    import json
    from pathlib import Path

    assert (
        frozenset(
            {
                "skip_phase",
                "incoming_advantage",
                "incoming_melee_advantage",
                "incoming_melee_autocrit",
                "incoming_ranged_disadvantage",
                "costs_declaration",
                "speed_0",
                "consumed_on_use",
                "one_time",
                "no_hostile_source",
                "auto_fail_hearing_perception",
                "no_spoken_buffs",
            }
        )
        == ENFORCED
    )
    assert set(NOT_ENFORCED) == {
        "removed_from_combat",
        "damage_resistance_all",
        "immune_poison_disease",
        "damage_reduction",
        "no_approach_source",
        "reduced_max_hp",
        "source_specific_penalty",
        "hallucinations",
        "stat_drain",
    }
    rows = json.loads((Path(__file__).resolve().parents[4] / "content/archetype_abilities.json").read_text())
    assert len(rows) == 145
    assert {row["id"] for row in rows if row.get("applies_condition") == "inspired"} == {
        "bard_inspire",
        "bard_mass_inspire",
        "diplomat_inspire",
    }
