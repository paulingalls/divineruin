"""BDD entry points for the final Greyvale reveal."""

from acceptance.emris_reveal_walk import completed, setup
from pytest_bdd import given, parsers, then


@given(parsers.parse("an artifact bearer of {patron} meeting Emris at {location}"))
def emris_bearer(harness, patron, location):
    harness.state["emris"] = harness.run_sync(setup(harness, patron, location))


@then("Emris closes the quest once and the player's patron alone whispers")
def emris_completes(harness):
    harness.run_sync(completed(harness.state["emris"]))


@given("the continuous traveler follows Kaelen")
def traveler_patron(harness):
    from acceptance.emris_reveal_walk import set_patron

    harness.run_sync(set_patron(harness.state["ruins"], "kaelen"))


@then("the road traveler resumes with the tablet and closes every authored effect")
def traveler_finishes(harness):
    from acceptance.emris_reveal_walk import close_walk

    harness.run_sync(close_walk(harness.state["ruins"], harness))
