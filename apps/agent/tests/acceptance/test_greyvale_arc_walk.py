"""Greyvale arc through the registered CLI agent tools and real reward authority."""

import json

import pytest
from acceptance.greyvale_arc_walk_harness import ROAD, TOWN, ArcWalk
from acceptance.greyvale_finish_line import (
    assert_finish,
    enter_surfaced_combat,
    quest_corpus,
    refresh,
    scene_hint,
    start_warm,
)
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


@pytest.fixture
def mock_combat_agent_factory():
    return None


@given(parsers.parse("an active Greyvale warm session at stage {stage:d}"))
def warm_stage(harness, stage):
    harness.state["arc"] = harness.run_sync(start_warm(harness))
    harness.state["stage"] = stage


@then("its scene hint reaches the silent player")
def hint_reaches(harness):
    harness.run_sync(scene_hint(harness.state["arc"], harness.state["stage"]))


@given("a warm session walking the complete quest corpus")
def corpus_session(harness):
    harness.state["arc"] = harness.run_sync(start_warm(harness))


@then("every stage renders its finish line and the surfaced combat starts")
def finish_lines(harness):
    async def check():
        arc = harness.state["arc"]
        combat_line = None
        for quest in quest_corpus():
            seeded = json.loads(await arc.pool.fetchval("SELECT data FROM quests WHERE id=$1", quest["id"]))
            assert seeded["stages"] == quest["stages"]
            for index in range(len(quest["stages"])):
                line = await refresh(arc, quest["id"], index)
                assert_finish(line, quest, index)
                if quest["id"] == "greyvale_anomaly" and index == 2:
                    combat_line = line
        assert combat_line is not None
        await enter_surfaced_combat(arc, combat_line)

    harness.run_sync(check())


@then("an unknown condition fails the warm refresh loudly")
def unknown_condition(harness):
    async def check():
        arc = harness.state["arc"]
        quest = await arc.private_quest(harness, {"type": "unwritten_condition"}, TOWN)
        with pytest.raises(ValueError, match=f"{quest}.*0.*unwritten_condition"):
            await refresh(arc, quest, 0)

    harness.run_sync(check())


@given(parsers.parse("a First Blood fight ending through {route}"))
def first_blood(harness, route):
    from unittest.mock import patch

    from acceptance._capstone_helpers import _d20
    from acceptance.first_blood_walk import FirstBloodWalk

    harness.stack.enter_context(patch("check_resolution.dice_roll", side_effect=lambda *_, **__: _d20(20)))
    arc = harness.run_sync(FirstBloodWalk().start(harness, route))
    harness.state["blood"] = arc
    harness.run_sync(arc.prepare())


@given(parsers.parse("a First Blood exclusion {case}"))
def first_blood_exclusion(harness, case):
    from acceptance.first_blood_walk import FirstBloodWalk

    options = {
        "wrong": {"encounter": "shadeling_cluster"},
        "defeat": {"outcome": "defeat"},
        "fled": {"outcome": "fled"},
        "deescalated": {"outcome": "deescalated"},
        "standing": {"cleared": False},
        "dead": {"alive": False},
        "progressed": {"stage": 3},
    }
    route = "resolve_phase" if case == "deescalated" else "end_combat"
    arc = harness.run_sync(FirstBloodWalk().start(harness, route, **options[case]))
    harness.state.update(blood=arc, blood_stage=3 if case == "progressed" else 2)
    harness.run_sync(arc.prepare())


@when("the fight ends")
def first_blood_ends(harness):
    harness.state["blood_result"] = harness.run_sync(harness.state["blood"].end())


@then("First Blood rewards and the dungeon objective reach the DM once")
def first_blood_reward(harness):
    async def check():
        arc = harness.state["blood"]
        await arc.rewarded(harness.state["blood_result"])
        await arc.replay_refused()
        await arc.fresh_encounter()

    harness.run_sync(check())


@then("First Blood stays unpaid")
def first_blood_unpaid(harness):
    async def check():
        import db_queries
        import event_types as E

        arc = harness.state["blood"]
        marker = await db_queries.get_player_quest(arc.player, "greyvale_anomaly")
        assert marker is not None and marker["current_stage"] == harness.state["blood_stage"]
        assert not [e for e in arc.events if e["type"] in {E.QUEST_UPDATED, E.WORLD_EVENT}]
        assert not [e for e in arc.events if e["type"] == E.XP_AWARDED and "Quest" in e["reason"]]
        assert await db_queries.get_npc_disposition("elder_yanna", arc.player) is None

    harness.run_sync(check())
