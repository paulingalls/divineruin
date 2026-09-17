from dataclasses import replace

import pytest

import conditions
from condition_restrictions import ENFORCED, NOT_ENFORCED


def _authored_restrictions() -> set[str]:
    catalog = {restriction for spec in conditions.CONDITION_CATALOG.values() for restriction in spec.restrictions}
    return catalog | conditions._hollowed_effects(3)[1]


def _assert_classified() -> None:
    deferred = set(NOT_ENFORCED)
    assert ENFORCED.isdisjoint(deferred)
    assert _authored_restrictions() == ENFORCED | deferred
    assert all(reason.strip() for reason in NOT_ENFORCED.values())


def test_every_authored_restriction_is_enforced_or_reasoned_debt():
    _assert_classified()


def test_a_new_catalog_restriction_fails_the_classification_floor(monkeypatch):
    stunned = conditions.CONDITION_CATALOG["stunned"]
    monkeypatch.setitem(
        conditions.CONDITION_CATALOG,
        "stunned",
        replace(stunned, restrictions=(*stunned.restrictions, "new_restriction")),
    )

    with pytest.raises(AssertionError, match="new_restriction"):
        _assert_classified()


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
