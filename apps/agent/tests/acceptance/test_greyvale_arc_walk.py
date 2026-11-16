"""Greyvale arc through the registered CLI agent tools and real reward authority."""

import json

from acceptance.greyvale_arc_walk_harness import ROAD, TOWN, ArcWalk
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/greyvale_arc_walk.feature")


@given(parsers.parse("a road quest holder using {tool}"))
def road_holder(harness, tool):
    harness.state["arc"] = harness.run_sync(ArcWalk().start(harness, tool))


@when("they arrive in Millhaven")
def arrive(harness):
    arc = harness.state["arc"]
    harness.state["result"] = harness.run_sync(arc.arrive())


@then("the road reward and next objective reach the DM")
def reward(harness):
    harness.run_sync(harness.state["arc"].rewarded(harness.state["result"]))


@then("later arrivals leave rewards and unrelated stages unchanged")
def repeats(harness):
    async def check():
        arc = harness.state["arc"]
        await arc.arrive(ROAD)
        await arc.unchanged_arrival()
        for stage, status in [(1, "active"), (None, "active"), (6, "completed")]:
            other = await ArcWalk().start(harness, arc.tool, stage, status)
            await other.unchanged_arrival()

    harness.run_sync(check())


@given("private quests with different completion conditions")
def conditions(harness):
    async def setup():
        arc = await ArcWalk().start(harness, "move_player", stage=None)
        ids = {}
        for kind in ["combat_completed", "item_discovered", "npc_interaction", "decision_made", "knowledge_acquired"]:
            ids[kind] = await arc.private_quest(harness, {"type": kind, "location": TOWN}, TOWN)
        ids["control"] = await arc.private_quest(harness, {"type": "location_reached", "location": TOWN}, ROAD)
        ids["target_only"] = await arc.private_quest(harness, {"type": "location_reached", "location": ROAD}, TOWN)
        harness.state.update(arc=arc, private=ids, before=await arc.snapshot())

    harness.run_sync(setup())


@then("only the matching location condition advances")
def matching(harness):
    async def check():
        rows, xp, disposition = await harness.state["arc"].snapshot()
        ids = harness.state["private"]
        before = {row["quest_id"]: row["data"] for row in harness.state["before"][0]}
        for row in rows:
            assert json.loads(row["data"])["current_stage"] == (1 if row["quest_id"] == ids["control"] else 0)
            if row["quest_id"] != ids["control"]:
                assert row["data"] == before[row["quest_id"]]
        assert xp == 50 and disposition is None
        updates = harness.state["result"]["quest_updates"]
        assert [u["quest_id"] for u in updates] == [ids["control"]]

    harness.run_sync(check())


@then("the target alone does not complete a location stage")
def target_only(harness):
    assert harness.state["private"]["target_only"] not in [
        u["quest_id"] for u in harness.state["result"]["quest_updates"]
    ]
