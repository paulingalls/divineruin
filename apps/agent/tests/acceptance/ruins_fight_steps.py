"""BDD steps for the continuous ruins walk."""

from unittest.mock import patch

from acceptance._capstone_helpers import _d20
from acceptance.ruins_fight_walk import RuinsFightWalk
from pytest_bdd import given, parsers, then, when


@given(parsers.parse("a new road traveler who will finish the ruins through {route}"))
def ruins_traveler(harness, route):
    harness.stack.enter_context(patch("check_resolution.dice_roll", side_effect=lambda *_, **__: _d20(20)))
    harness.state["ruins"] = harness.run_sync(RuinsFightWalk().start(harness, route))


@when("they walk through Millhaven and the journal into the ruins fight")
def ruins_walk(harness):
    harness.run_sync(harness.state["ruins"].walk())


@then("the level three party wins and the ruins quest reward arrives once")
def ruins_reward(harness):
    harness.run_sync(harness.state["ruins"].rewarded_ruins())
