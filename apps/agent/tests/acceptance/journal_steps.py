"""BDD steps for engine-driven item discovery."""

import json

from acceptance.greyvale_arc_walk_harness import QUEST
from acceptance.journal_walk import ITEM, PLACE, JournalWalk
from pytest_bdd import given, parsers, then, when

import db
import db_content_queries
import db_mutations
import db_queries
import event_types as E


@given("a journal search at the ruins")
def journal_search(harness):
    harness.state["journal"] = harness.run_sync(JournalWalk().start(harness))


@when("the player searches the research station")
def search(harness):
    harness.state["journal_result"] = harness.run_sync(harness.state["journal"].discover())


@then("the journal and its quest rewards arrive once")
def journal_rewards(harness):
    async def check():
        arc = harness.state["journal"]
        await arc.rewarded(harness.state["journal_result"])
        before = await arc.durable()
        await arc.discover()
        arc.sd.attempted_discoveries.clear()
        await arc.discover()
        assert await arc.durable() == before
        await arc.discover(actor=arc.guest)
        assert await arc.quantity(actor=arc.guest) == 1
        assert await arc.quantity() == 1
        player = await db_queries.get_player(arc.player)
        assert player is not None
        assert player["xp"] == 200
        assert await arc.quantity("veythar_sealed_artifact") == 1
        assert arc.sd.corruption_level == 1
        assert (
            len([e for e in arc.events if e["type"] == E.WORLD_EVENT and e["event_id"] == "ruins_discovery_ripple"])
            == 1
        )
        before = await arc.durable()
        arc.events.clear()
        result = await arc.discover(skill="arcana", target="archway")
        assert result["element_id"] == "veythar_seal_mark"
        assert not [e for e in arc.events if e["type"] in {E.INVENTORY_UPDATED, E.QUEST_UPDATED}]
        after = await arc.durable()
        assert after[1:] == before[1:]
        for old, new in zip(before[0], after[0], strict=True):
            old_data, new_data = json.loads(old["data"]), json.loads(new["data"])
            if old["player_id"] == arc.player:
                assert new_data["flags"].pop("veythar_seal_mark.discovered") is True
            assert new_data == old_data
        other = await JournalWalk().start(harness)
        await other.discover(actor=other.guest)
        assert await other.quantity() == 0 and await other.quantity(actor=other.guest) == 1
        assert await other.marker() == 4

    harness.run_sync(check())


@given(parsers.parse("an earlier journal discovery with {holding}"))
def earlier(harness, holding):
    async def setup():
        arc = await JournalWalk().start(harness, 2)
        if holding == "unflagged":
            await db_mutations.add_inventory_item(arc.player, ITEM, 1, tainted=False)
        else:
            await arc.discover()
            if holding == "removed":
                await arc.remove_journal()
        harness.state["journal"] = arc

    harness.run_sync(setup())


@when("the quest enters the journal stage")
def enter(harness):
    arc = harness.state["journal"]
    harness.state["journal_result"] = harness.run_sync(
        arc.command("update_quest", {"quest_id": QUEST, "new_stage_id": 3})
    )


@then(parsers.parse("its final stage is {stage:d}"))
def final_stage(harness, stage):
    async def check():
        arc = harness.state["journal"]
        result = harness.state["journal_result"]
        assert await arc.marker() == result["new_stage"] == stage
        player = await db_queries.get_player(arc.player)
        assert player is not None
        assert player["xp"] == (350 if stage == 4 else 150)
        if stage == 4:
            quest = await db_content_queries.get_quest(QUEST)
            assert quest is not None
            assert result["narrative_beat"] == "\n".join(
                s["on_complete"]["narrative_beat"] for s in quest["stages"][2:4]
            )
            assert arc.sd.session_xp_earned == 350

    harness.run_sync(check())


@given("a private search requiring two items")
def two_items(harness):
    async def setup():
        arc = await JournalWalk().start(harness, None)
        second = "aldric_strange_stone"
        quest = await arc.private_items(harness, items=[ITEM, second])
        location = await db_content_queries.get_location(PLACE)
        assert location is not None
        location["hidden_elements"].append({"id": second, "discover_skill": "perception", "dc": 1})
        await arc.pool.execute("UPDATE locations SET data=$2::jsonb WHERE id=$1", PLACE, json.dumps(location))
        redis = await db.get_redis()
        await redis.delete("location:" + PLACE)
        harness.state.update(journal=arc, item_quest=quest)

    harness.run_sync(setup())


@then("one find cannot finish it and the second finishes it once")
def both_items(harness):
    async def check():
        arc, quest = harness.state["journal"], harness.state["item_quest"]
        exclusions = []
        for cc in [
            {"type": "item_discovered", "items": [ITEM], "location": "millhaven"},
            {"type": "item_discovered", "items": ["veythar_sealed_artifact"], "location": PLACE},
            {"type": "decision_made", "items": [ITEM], "location": PLACE},
        ]:
            exclusions.append(await arc.private_quest(harness, cc, PLACE))
        await arc.discover()
        assert await arc.marker(quest) == 0
        arc.add_guest()
        await arc.hold("aldric_strange_stone", actor=arc.guest)
        # Enter a separate two-item stage: one member cannot borrow the other's holdings.
        entry = await arc.private_items(harness, items=[ITEM, "aldric_strange_stone"], chained=True)
        await arc.command("update_quest", {"quest_id": entry, "new_stage_id": 0})
        assert await arc.marker(entry) == 0
        await arc.discover(skill="perception", target="scattered papers")
        assert await arc.marker(quest) == 1
        assert await arc.marker(entry) == 2
        assert all([await arc.marker(q) == 0 for q in exclusions])

    harness.run_sync(check())


@then("starting an already satisfied item quest pays each stage once")
def chain(harness):
    async def check():
        arc = harness.state["journal"]
        await arc.discover(actor=arc.guest)
        quest = await arc.private_items(harness, chained=True)
        result = await arc.command("update_quest", {"quest_id": quest, "new_stage_id": 0})
        assert result["new_stage"] == await arc.marker(quest) == 2
        assert sum(r["amount"] for r in result["rewards_applied"] if r["type"] == "xp") == 82
        assert arc.sd.corruption_level == 3
        assert arc.sd.member_state(arc.guest).corruption_level == 3
        before = await arc.durable()
        await arc.command("update_quest", {"quest_id": quest, "new_stage_id": 0}, error=True)
        assert await arc.durable() == before

    harness.run_sync(check())
