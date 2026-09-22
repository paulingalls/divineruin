import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import AgentSession, llm
from livekit.agents.voice.events import CloseEvent, CloseReason

import event_types as E
from background_process import BackgroundProcess
from caster_state import ConcentrationState, ResonanceTrack
from exploration_agent import ExplorationAgent
from party_state import PartyMember
from session_data import SessionData
from session_tools import end_session
from warm_prompts import build_warm_layer


def party_session() -> SessionData:
    sd = SessionData(player_id="host", location_id="hall")
    sd.party.members.append(
        PartyMember(player_id="guest", resonance=ResonanceTrack(), concentration=ConcentrationState())
    )
    sd.cached_npc_names = ["Barkeep"]
    return sd


@pytest.mark.asyncio
async def test_hot_context_tracks_authenticated_speaker_on_each_turn():
    sd = party_session()
    agent = ExplorationAgent()
    players = {
        "host": {"name": "Ada", "hp": {"current": 9, "max": 10}},
        "guest": {"name": "Bryn", "hp": {"current": 4, "max": 12}},
    }
    quests = {
        "host": [{"quest_name": "Host Quest", "current_stage": 0, "stages": [{"objective": "Find host map"}]}],
        "guest": [{"quest_name": "Guest Quest", "current_stage": 0, "stages": [{"objective": "Find guest key"}]}],
    }
    activities = {"host": [{"activity_type": "crafting"}], "guest": [{"activity_type": "companion_errand"}]}

    async def get_player(pid):
        return players[pid]

    async def get_quests(pid):
        return quests[pid]

    async def get_activities(pid, status):
        assert status == "in_progress"
        return activities[pid]

    with (
        patch.object(ExplorationAgent, "session", property(lambda _: MagicMock(userdata=sd))),
        patch("exploration_agent.db_queries.get_player", side_effect=get_player),
        patch("exploration_agent.db_queries.get_active_player_quests", side_effect=get_quests),
        patch("exploration_agent.db_activity_queries.get_player_activities", side_effect=get_activities),
        patch(
            "exploration_agent.db_training.get_player_active_training_activities",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        contexts = []
        for pid in ("guest", "host", "guest"):
            if len(contexts) == 2:
                players["guest"]["hp"]["current"] = 3
                quests["guest"][0]["stages"][0]["objective"] = "Open guest door"
                activities["guest"] = [{"activity_type": "crafting"}]
            with sd._bind_authenticated_actor(pid, 1, lambda *_: None):
                ctx = llm.ChatContext()
                await agent.on_user_turn_completed(ctx, MagicMock())
                contexts.append(" ".join(str(m.content) for m in ctx.items if isinstance(m, llm.ChatMessage)))

    assert "Bryn" in contexts[0] and "4/12" in contexts[0]
    assert "Find guest key" in contexts[0] and "companion_errand" in contexts[0]
    assert "Ada" not in contexts[0] and "Host Quest" not in contexts[0]
    assert "[NPCs nearby: Barkeep]" in contexts[0]
    assert "Ada" in contexts[1] and "9/10" in contexts[1]
    assert "Find host map" in contexts[1] and "crafting" in contexts[1]
    assert "Bryn" not in contexts[1] and "Guest Quest" not in contexts[1]
    assert "3/12" in contexts[2] and "Open guest door" in contexts[2]
    assert "Find guest key" not in contexts[2]


def test_speaker_snapshot_handles_training_and_explicit_absence():
    agent = ExplorationAgent()
    player = {"name": "Bryn", "hp": {"current": 4, "max": 12}}
    training = [{"activity_type": "technique_base", "data": {"program_name": "Sword Drills"}}]
    assert "activity: Sword Drills" in agent._build_speaker_context(player, [], [], training)
    empty = agent._build_speaker_context(player, [], [], [])
    assert "quest step: none" in empty and "activity: none" in empty


@pytest.mark.asyncio
async def test_session_init_uses_host_during_guest_handback():
    sd = party_session()
    query = AsyncMock(return_value={"player_id": "host"})
    publish = AsyncMock()
    with (
        patch("exploration_agent.db_session_queries.get_session_init_payload", query),
        patch("exploration_agent.publish_game_event", publish),
    ):
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            task = asyncio.create_task(ExplorationAgent()._publish_session_init(sd))
            await task
    query.assert_awaited_once_with("host")
    assert publish.await_args is not None
    assert publish.await_args.args[1] == E.SESSION_INIT


@pytest.mark.asyncio
async def test_session_end_recap_survives_guest_close_task():
    sd = party_session()
    sd.room = MagicMock()
    sd.room.isconnected.return_value = True
    sd.room.local_participant.publish_data = AsyncMock()
    session = AgentSession(max_tool_steps=5, userdata=sd)
    background = BackgroundProcess(session, sd)
    summary = {"summary": "Party returned"}
    with (
        patch("session_end.generate_session_summary", new_callable=AsyncMock, return_value=summary),
        patch("session_end.db_mutations.save_session_summary", new_callable=AsyncMock) as save,
    ):
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            await end_session._func(MagicMock(userdata=sd), "goodbye")
            assert sd.ending_requested
            background._on_session_end(CloseEvent(reason=CloseReason.JOB_SHUTDOWN))
            assert sd.session_end_task is not None
            await sd.session_end_task
    save.assert_awaited_once_with("host", sd.session_id, summary)
    assert len([e for e in sd.event_bus.drain() if e.event_type == E.SESSION_END]) == 1


@pytest.mark.asyncio
async def test_warm_facts_belong_to_host_during_guest_turn():
    sd = party_session()
    sd.companion = MagicMock(
        name="Kael",
        is_present=True,
        is_conscious=True,
        emotional_state="steady",
        session_count=0,
        affinity=0,
        session_memories=[],
    )
    sd.companion.name = "Kael"
    location = {
        "name": "Hall",
        "region_type": "city",
        "exits": {"north": {"destination": "gate", "requires": "host_flag"}},
    }
    quests = [{"quest_name": "Host Quest", "current_stage": 0, "stages": [{"objective": "Find host map"}]}]
    training = [{"id": "host_training", "state": "running_first_half", "data": {"program_name": "Host Drill"}}]
    npc = [{"id": "keeper", "name": "Keeper", "role": "guide"}]
    with (
        patch(
            "db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={"keeper": "friendly"}
        ) as dispositions,
        patch("movement_tools._check_exit_requirement", new_callable=AsyncMock, return_value=False) as exit_check,
    ):
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            warm = await build_warm_layer(
                "hall",
                sd.primary_player_id,
                "evening",
                companion=sd.companion,
                quests=quests,
                location=location,
                npcs_raw=npc,
                training=training,
            )
    dispositions.assert_awaited_once_with(["keeper"], "host")
    exit_check.assert_awaited_once_with("host_flag", "host")
    assert "AFFORDANCES — host player host" in warm
    assert "Find host map" in warm and "Host Drill" in warm
    assert "friendly" in warm and "north (locked)" in warm
    assert "SESSION COMPANION — Kael (host player host)" in warm
    assert "guest" not in warm


@pytest.mark.asyncio
async def test_background_rebuild_reads_host_under_guest_binding():
    sd = party_session()
    session = MagicMock()
    background = BackgroundProcess(session, sd)
    quests = AsyncMock(return_value=[])
    training = AsyncMock(return_value=[])
    with (
        patch("background_process.db_queries.get_active_player_quests", quests),
        patch("background_process.db_training.get_player_active_training_activities", training),
        patch("background_process.db_content_queries.get_location", new_callable=AsyncMock, return_value=None),
        patch("background_process.db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=[]),
        patch("background_process.build_warm_layer", new_callable=AsyncMock, return_value="host warm") as build,
        patch.object(background, "_apply_warm", new_callable=AsyncMock),
    ):
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            task = asyncio.create_task(background._rebuild_warm_layer())
            await task
    quests.assert_awaited_once_with("host")
    training.assert_awaited_once_with("host")
    assert build.await_args is not None
    assert build.await_args.args[1] == "host"
