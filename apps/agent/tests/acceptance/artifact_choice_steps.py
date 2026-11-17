"""Artifact and Millhaven choices through the active agent."""

from acceptance.quest_decision_walk import assert_choice, command, decision_walk, snapshot
from pytest_bdd import given, parsers, then, when


@given(parsers.parse("a decision session for {quest} at {stage:d}"))
def decision_session(harness, quest, stage):
    harness.state["decision"] = harness.run_sync(decision_walk(harness, quest, stage))


@then(parsers.parse("choosing {option} persists once and survives later advances"))
def chosen(harness, option):
    harness.run_sync(assert_choice(harness.state["decision"], option))


@when(parsers.parse("the decision receives {option}"))
def invalid(harness, option):
    async def check():
        arc = harness.state["decision"]
        before, events = await snapshot(arc), list(arc.events)
        receipt = await command(arc, 7, None if option == "omitted" else option)
        assert receipt.is_error
        assert all(o in receipt.output for o in ("keep_artifact", "show_companion"))
        assert await snapshot(arc) == before and arc.events == events

    harness.run_sync(check())


@then("an ordinary stage accepts omission and refuses an unexpected option")
def ordinary(harness):
    async def check():
        arc = harness.state["decision"]
        before, events = await snapshot(arc), list(arc.events)
        assert (await command(arc, 1, "watchtower")).is_error
        assert await snapshot(arc) == before and arc.events == events
        receipt = await command(arc, 1)
        assert not receipt.is_error, receipt.output
        arc.stage = 1
        await assert_choice(arc, "watchtower")

    harness.run_sync(check())


@then("showing without a bound companion refuses without writes")
def no_companion(harness):
    async def check():
        arc = harness.state["decision"]
        before, events = await snapshot(arc), list(arc.events)
        companion = arc.sd.companion
        arc.sd.companion = None
        receipt = await command(arc, 7, "show_companion")
        arc.sd.companion = companion
        assert receipt.is_error and "companion" in receipt.output
        assert await snapshot(arc) == before and arc.events == events

    harness.run_sync(check())


@then(parsers.parse("a {progress} second member keeps independent decision history"))
def party_choice(harness, progress):
    async def check():
        import json
        from uuid import uuid4

        from acceptance.seeds import seed_player

        import db_mutations
        import db_queries
        from party_state import PartyState

        arc = harness.state["decision"]
        guest = f"decision_{uuid4().hex}"
        await seed_player(arc.pool, player_id=guest, class_="warrior", location_id=arc.sd.location_id)
        harness.stack.callback(
            lambda: harness.run_sync(arc.pool.execute("DELETE FROM players WHERE player_id=$1", guest))
        )
        arc.sd.party.members.extend(PartyState.solo(guest).members)
        advanced = progress == "advanced"
        decisions = {"earlier": "guest", **({"artifact_choice": "keep_artifact"} if advanced else {})}
        await db_mutations.set_player_quest(
            guest, arc.quest, {"current_stage": 7 if advanced else 6, "decisions": decisions}
        )
        await db_mutations.set_player_flag(guest, "player_has_veythar_artifact", True)
        await db_mutations.set_npc_disposition(arc.sd.companion.id, guest, "hostile", "setup")
        before = await snapshot(arc, guest)
        receipt = await command(arc, 7, "show_companion")
        assert not receipt.is_error, receipt.output
        after = await snapshot(arc, guest)
        if advanced:
            assert after == before
        else:
            assert json.loads(after[1])["decisions"] == {"earlier": "guest", "artifact_choice": "show_companion"}
            assert json.loads(after[0])["flags"]["companion_knows_artifact"] is True
            assert after[2] == "friendly"
        host = await db_queries.get_player_quest(arc.player, arc.quest)
        assert host is not None
        assert host["decisions"] == {"artifact_choice": "show_companion"}
        host_snapshot, count = await snapshot(arc), len(arc.events)
        assert (await command(arc, 7, "keep_artifact", actor=guest)).is_error
        assert await snapshot(arc, guest) == after
        assert await snapshot(arc) == host_snapshot and len(arc.events) == count

    harness.run_sync(check())
