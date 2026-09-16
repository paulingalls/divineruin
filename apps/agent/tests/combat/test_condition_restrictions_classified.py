import importlib
import importlib.util
from dataclasses import replace

import pytest

import conditions


def _subject():
    assert importlib.util.find_spec("condition_restrictions") is not None, (
        "condition_restrictions must classify every authored restriction"
    )
    return importlib.import_module("condition_restrictions")


def _authored_restrictions() -> set[str]:
    catalog = {restriction for spec in conditions.CONDITION_CATALOG.values() for restriction in spec.restrictions}
    return catalog | conditions._hollowed_effects(3)[1]


def _assert_classified() -> None:
    subject = _subject()
    deferred = set(subject.NOT_ENFORCED)
    assert subject.ENFORCED.isdisjoint(deferred)
    assert _authored_restrictions() == subject.ENFORCED | deferred
    assert all(reason.strip() for reason in subject.NOT_ENFORCED.values())


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
