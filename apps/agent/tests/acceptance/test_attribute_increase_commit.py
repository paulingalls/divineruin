"""Attribute increases reach the registered quest command and committed client snapshot."""

import json

from acceptance.attribute_increase_walk import IncreaseWalk

import event_types as E


def test_award_commits_attributes_and_produces_redirect(harness):
    async def check():
        walk = await IncreaseWalk().setup(harness)
        before = await walk.row()
        receipt = await walk.command("update_quest", {"quest_id": "greyvale_anomaly", "new_stage_id": 8})
        assert not receipt.is_error, receipt.output
        row = await walk.row()
        assert row["attributes"]["strength"] == 19
        assert row["hp"] == {"current": 5, "max": 32}
        assert row["stamina"]["max"] == 14
        assert row["attributes"] == {**before["attributes"], "strength": 19}
        (offer,) = json.loads(receipt.output)["attribute_increases"]
        assert offer["choice_id"] == "attribute_increase_4"
        assert offer["scores"]["strength"] == 19
        assert offer["redirect_until"] == "next_long_rest"
        assert offer["resolve_with"] == "select" and "wisdom" in offer["options"]
        assert [e for e in walk.events if e["type"] == E.SESSION_INIT]
        walk.events.clear()
        completed_stage_request = await walk.command(
            "update_quest", {"quest_id": "greyvale_anomaly", "new_stage_id": 8}
        )
        assert completed_stage_request.is_error and "Cannot go backward" in completed_stage_request.output
        assert await walk.row() == row and not walk.events

    harness.run_sync(check())


def test_reload_redirect_and_long_rest_deadline(harness):
    async def check():
        walk = await IncreaseWalk().setup(harness)
        paid = await walk.command("update_quest", {"quest_id": "greyvale_anomaly", "new_stage_id": 8})
        assert not paid.is_error, paid.output
        await walk.reload(harness)
        query = await walk.command("query_info", {"kind": "abilities"})
        assert not query.is_error, query.output
        (offer,) = json.loads(query.output)["attribute_increases"]
        choice = offer["choice_id"]
        redirect = await walk.command(
            "select", {"choice_id": choice, "option": "wisdom"}, "Put them in Wisdom instead."
        )
        assert not redirect.is_error, redirect.output
        row = await walk.row()
        assert row["attributes"]["strength"] == 17 and row["attributes"]["wisdom"] == 15
        assert row["attribute_increases"]["4"] == {"allocation": {"wisdom": 2}, "locked": False}
        await walk.reload(harness)
        short = await walk.command("rest", {"rest_type": "short"})
        assert not short.is_error, short.output
        redirected = await walk.command("select", {"choice_id": choice, "option": "constitution"})
        assert not redirected.is_error, redirected.output
        assert (await walk.row())["hp"] == {"current": 5, "max": 36}
        long = await walk.command("rest", {"rest_type": "long"})
        assert not long.is_error, long.output
        before = await walk.row()
        assert before["attribute_increases"]["4"]["locked"]
        await walk.reload(harness)
        refused = await walk.command("select", {"choice_id": choice, "option": "wisdom"})
        assert refused.is_error and "long rest" in refused.output.lower()
        assert await walk.row() == before
        query = await walk.command("query_info", {"kind": "abilities"})
        assert json.loads(query.output)["attribute_increases"] == []

    harness.run_sync(check())


def test_combat_exit_surfaces_guest_increase_and_private_snapshot(harness, monkeypatch):
    from acceptance.voice_condition_harness import ScenarioModel
    from livekit.agents import Agent, AgentSession

    import db_mutations
    from combat_end import end_combat
    from session_data import CombatParticipant, CombatState, SessionData

    async def check():
        walk = await IncreaseWalk().setup(harness)
        guest = walk.player + "_guest"
        guest_row = await walk.row()
        await db_mutations.create_player(guest, None, guest_row)
        await walk.seed(1)
        walk.sd.party.members.append(SessionData(player_id=guest, location_id="millhaven_inn").party.primary)
        parts = [
            CombatParticipant(id=pid, name=pid, type="player", initiative=15, hp_current=5, hp_max=26, ac=14)
            for pid in (walk.player, guest)
        ]
        parts.append(
            CombatParticipant(
                id="increase_enemy",
                name="Enemy",
                type="enemy",
                initiative=1,
                hp_current=0,
                hp_max=10,
                ac=10,
                xp_value=400,
                is_fallen=True,
            )
        )
        state = CombatState("increase_combat", parts, [p.id for p in parts], location_id="millhaven_inn")
        walk.sd.combat_state = state
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        await walk.session.aclose()
        walk.model = ScenarioModel([])
        walk.session = AgentSession(llm=walk.model, userdata=walk.sd)
        await walk.session.start(Agent(instructions="End the fight.", tools=[end_combat]))
        monkeypatch.setattr("combat_end._build_handoff_agent", lambda *_: Agent(instructions="Narrate the rewards."))
        receipt = await walk.command("end_combat", {"outcome": "victory"})
        assert not receipt.is_error, receipt.output
        result = json.loads(receipt.output)
        (offer,) = result["attribute_increases"]
        assert offer["player_id"] == guest and offer["scores"]["strength"] == 19
        import db_queries

        guest_saved = await db_queries.get_player(guest)
        assert guest_saved is not None and guest_saved["attributes"]["strength"] == 19
        assert (await walk.row())["attributes"]["strength"] == 17
        snapshots = [e["character"]["player_id"] for e in walk.events if e["type"] == E.SESSION_INIT]
        assert sorted(snapshots) == sorted([walk.player, guest])
        assert walk.sd.combat_state is None

    harness.run_sync(check())
