"""Disposition packets and companion speech from registered tools."""

import json
from typing import cast
from uuid import uuid4

import pytest
from acceptance.disposition_event_assertions import assert_named_disposition, listen
from acceptance.greyvale_finish_line import start_warm
from acceptance.quest_decision_walk import DecisionWalk, command, decision_walk
from acceptance.seeds import seed_player
from sample_fixtures import make_context, make_mock_room, published_payloads

import db
import db_mutations
import db_queries
from background_process import BackgroundProcess
from exploration_agent import EXPLORATION_TOOLS
from party_state import PartyState

TORIN = "guildmaster_torin"


async def test_session_disposition_names_the_present_npc(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player = "session_disposition"
    location = "accord_guild_hall"
    await seed_player(pool, player_id=player, class_="warrior", location_id=location)
    room = make_mock_room()
    ctx = make_context(player, location_id=location, room=room)
    bus = listen(ctx.userdata)
    tool = next(tool for tool in EXPLORATION_TOOLS if tool.__name__ == "update_npc_disposition")

    await tool(ctx, npc_id=TORIN, delta=1, reason="Returned the scouts' report", grievance="none")

    assert await db_queries.get_npc_disposition(TORIN, player) == "friendly"
    assert_named_disposition(
        BackgroundProcess(ctx.session, ctx.userdata),
        bus,
        published_payloads(room),
        npc_id=TORIN,
        npc_name="Guildmaster Torin",
        previous="neutral",
        new="friendly",
        reason="Returned the scouts' report",
    )


def test_artifact_choice_names_the_bound_companion(harness) -> None:
    async def run() -> None:
        arc = await decision_walk(harness)
        bus = listen(arc.sd)
        await db_mutations.set_npc_disposition("companion_sable", arc.player, "hostile", "setup")

        receipt = await command(arc, 7, "show_companion")

        assert not receipt.is_error, receipt.output
        assert await db_queries.get_npc_disposition("companion_sable", arc.player) == "friendly"
        assert_named_disposition(
            BackgroundProcess(arc.session, arc.sd),
            bus,
            arc.events,
            npc_id="companion_sable",
            npc_name="Sable",
            previous="hostile",
            new="friendly",
            reason="world_effect: companion_disposition +3",
        )

    harness.run_sync(run())


@pytest.mark.parametrize(
    ("target", "companion_present"),
    [
        pytest.param("companion_sable", True, id="bound"),
        pytest.param("companion_kael", True, id="unbound"),
        pytest.param("companion_sable", False, id="no-companion"),
    ],
)
def test_stage_effect_publishes_the_acting_guests_disposition(harness, target: str, companion_present: bool) -> None:
    async def run() -> None:
        arc = cast(DecisionWalk, await start_warm(harness))
        arc.quest = f"disposition_{uuid4().hex}"
        guest = f"guest_{uuid4().hex}"
        await seed_player(arc.pool, player_id=guest, class_="warrior", location_id=arc.sd.location_id)
        arc.sd.party.members.extend(PartyState.solo(guest).members)
        room = make_mock_room()
        arc.sd.room = room
        bus = listen(arc.sd)
        if not companion_present:
            arc.sd.companion = None
        await arc.pool.execute(
            "INSERT INTO quests (id, data) VALUES ($1, $2::jsonb)",
            arc.quest,
            json.dumps(
                {
                    "name": "Report to Torin",
                    "stages": [
                        {
                            "objective": "Report to Torin",
                            "completion_conditions": {"type": "npc_interaction", "npc": TORIN, "topic": "scouts"},
                            "on_complete": {"world_effects": [f"{target}_disposition +1"]},
                        }
                    ],
                }
            ),
        )

        async def cleanup() -> None:
            await arc.pool.execute("DELETE FROM player_quests WHERE quest_id=$1", arc.quest)
            await arc.pool.execute("DELETE FROM quests WHERE id=$1", arc.quest)
            await arc.pool.execute("DELETE FROM players WHERE player_id=$1", guest)

        harness.stack.callback(lambda: harness.run_sync(cleanup()))
        await arc.quest_row(arc.quest)
        await db_mutations.set_player_quest(guest, arc.quest, {"current_stage": 0})
        await db_mutations.set_npc_disposition(target, arc.player, "neutral", "setup")
        await db_mutations.set_npc_disposition(target, guest, "hostile", "setup")

        receipt = await command(arc, 1, actor=guest)

        if not companion_present or target == "companion_kael":
            assert await db_queries.get_npc_disposition(target, arc.player) == "neutral"
            assert await db_queries.get_npc_disposition(target, guest) == "hostile"
            assert receipt.is_error and f"Unknown NPC '{target}'." in receipt.output
            return

        assert not receipt.is_error, receipt.output
        assert await db_queries.get_npc_disposition(target, arc.player) == "friendly"
        assert await db_queries.get_npc_disposition(target, guest) == "unfriendly"
        assert_named_disposition(
            BackgroundProcess(arc.session, arc.sd),
            bus,
            published_payloads(room),
            npc_id=target,
            npc_name="Sable",
            previous="hostile",
            new="unfriendly",
            reason=f"world_effect: {target}_disposition +1",
        )

    harness.run_sync(run())
