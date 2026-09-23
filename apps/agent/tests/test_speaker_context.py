import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import AgentSession, llm
from livekit.agents.voice.events import CloseEvent, CloseReason

import event_types as E
from background_process import BackgroundProcess
from bg_speech import PendingSpeech, SpeechPriority
from caster_state import ConcentrationState, ResonanceTrack
from combat_agent import CombatAgent
from exploration_agent import ExplorationAgent
from party_state import PartyMember
from session_data import SessionData
from session_tools import end_session
from speaker_context import build_speaker_context
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
        "host": [
            {
                "quest_id": "host",
                "quest_name": "Host Quest",
                "current_stage": 0,
                "stages": [{"objective": "Find host map"}],
            }
        ],
        "guest": [
            {
                "quest_id": "guest",
                "quest_name": "Guest Quest",
                "current_stage": 0,
                "stages": [{"objective": "Find guest key"}],
            }
        ],
    }
    activities = {"host": [{"activity_type": "crafting"}], "guest": [{"activity_type": "companion_errand"}]}

    async def get_player(pid):
        return players[pid]

    async def get_quests(pid):
        return quests[pid]

    async def get_activities(pid, status):
        assert status == "in_progress"
        return activities[pid]

    background = BackgroundProcess(MagicMock(), sd)
    with (
        patch.object(ExplorationAgent, "session", property(lambda _: MagicMock(userdata=sd))),
        patch("background_process.db_queries.get_player", side_effect=get_player),
        patch("background_process.db_queries.get_active_player_quests", side_effect=get_quests),
        patch("background_process.db_activity_queries.get_player_activities", side_effect=get_activities),
        patch(
            "background_process.db_training.get_player_active_training_activities",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("background_process.db_content_queries.get_location", new_callable=AsyncMock, return_value=None),
        patch(
            "background_process.db_queries.get_npcs_at_location",
            new_callable=AsyncMock,
            return_value=[{"name": "Barkeep"}],
        ),
        patch("background_process.build_warm_layer", new_callable=AsyncMock, return_value="host warm"),
        patch.object(background, "_apply_warm", new_callable=AsyncMock),
    ):
        await background._rebuild_warm_layer()
        contexts = []
        for pid in ("guest", "host", "guest"):
            if len(contexts) == 2:
                players["guest"]["hp"]["current"] = 3
                quests["guest"][0]["stages"][0]["objective"] = "Open guest door"
                activities["guest"] = [{"activity_type": "crafting"}]
                await background._rebuild_warm_layer()
            with sd._bind_authenticated_actor(pid, 1, lambda *_: None):
                ctx = llm.ChatContext()
                await agent.on_user_turn_completed(ctx, MagicMock())
                contexts.append(" ".join(str(m.content) for m in ctx.items if isinstance(m, llm.ChatMessage)))

    assert "Speaker: Bryn (player guest)" in contexts[0] and "4/12" in contexts[0]
    assert "Find guest key" in contexts[0] and "companion_errand" in contexts[0]
    assert "Ada" not in contexts[0] and "Host Quest" not in contexts[0]
    assert "[NPCs nearby: Barkeep]" in contexts[0]
    assert "Speaker: Ada (player host)" in contexts[1] and "9/10" in contexts[1]
    assert "Find host map" in contexts[1] and "crafting" in contexts[1]
    assert "Bryn" not in contexts[1] and "Guest Quest" not in contexts[1]
    assert "3/12" in contexts[2] and "Open guest door" in contexts[2]
    assert "Find guest key" not in contexts[2]


def test_speaker_snapshot_handles_training_and_explicit_absence():
    player = {"name": "Bryn", "hp": {"current": 4, "max": 12}}
    training = [{"activity_type": "technique_base", "data": {"program_name": "Sword Drills"}}]
    assert "activity: Sword Drills" in build_speaker_context("guest", player, [], [], training).render()
    empty = build_speaker_context("guest", player, [], [], []).render()
    assert "quest step: none" in empty and "activity: none" in empty


def test_speaker_quest_choice_is_stable_across_db_row_order():
    player = {"name": "Bryn", "hp": {"current": 4, "max": 12}}
    quests = [
        {"quest_id": "z", "quest_name": "Later", "current_stage": 0, "stages": [{"objective": "Last"}]},
        {"quest_id": "a", "quest_name": "First", "current_stage": 0, "stages": [{"objective": "First step"}]},
    ]
    first = build_speaker_context("guest", player, quests, [], []).render()
    assert first == build_speaker_context("guest", player, list(reversed(quests)), [], []).render()
    assert "First step" in first and "Last" not in first


@pytest.mark.asyncio
async def test_background_refresh_keeps_last_good_speaker_on_missing_row_and_io_error(caplog):
    sd = party_session()
    background = BackgroundProcess(MagicMock(), sd)
    guest = {"name": "Bryn", "hp": {"current": 4, "max": 12}}
    rows: dict[str, dict | Exception | None] = {
        "host": {"name": "Ada", "hp": {"current": 9, "max": 10}},
        "guest": guest,
    }

    async def get_player(pid):
        value = rows[pid]
        if isinstance(value, Exception):
            raise value
        return value

    with (
        patch("background_process.db_queries.get_player", side_effect=get_player),
        patch("background_process.db_activity_queries.get_player_activities", new_callable=AsyncMock, return_value=[]),
        patch("background_process.db_queries.get_active_player_quests", new_callable=AsyncMock, return_value=[]),
        patch(
            "background_process.db_training.get_player_active_training_activities",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        rows["guest"] = None
        await background._refresh_speakers([], [])
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            from speaker_context import speaker_line

            assert speaker_line(sd) == "[Speaker: player guest]"
        rows["guest"] = guest
        await background._refresh_speakers([], [])
        rows["guest"] = OSError("offline")
        await background._refresh_speakers([], [])
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            assert "Bryn" in speaker_line(sd)
        rows["guest"] = {"name": "broken"}
        with pytest.raises(KeyError, match="hp"):
            await background._refresh_speakers([], [])
    assert "Speaker player guest is missing" in caplog.text
    assert "Speaker refresh failed for guest" in caplog.text


@pytest.mark.asyncio
async def test_turn_hooks_use_cache_without_database_and_name_missing_speaker():
    sd = party_session()
    exploration = ExplorationAgent()
    combat = CombatAgent()
    with (
        patch.object(ExplorationAgent, "session", property(lambda _: MagicMock(userdata=sd))),
        patch.object(CombatAgent, "session", property(lambda _: MagicMock(userdata=sd))),
        patch("db.get_pool", side_effect=AssertionError("hot path queried DB")),
    ):
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            for agent in (exploration, combat):
                ctx = llm.ChatContext()
                await agent.on_user_turn_completed(ctx, MagicMock())
                assert "[Speaker: player guest]" in " ".join(
                    str(item.content) for item in ctx.items if isinstance(item, llm.ChatMessage)
                )


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
async def test_session_end_recap_survives_host_close_task():
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
        with sd._bind_authenticated_actor("host", 1, lambda *_: None):
            await end_session._func(MagicMock(userdata=sd), "goodbye")
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
    assert "Find host map" in warm and "Host player host\nACTIVE TRAINING" in warm
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
        patch(
            "background_process.db_queries.get_player",
            new_callable=AsyncMock,
            return_value={"name": "Name", "hp": {"current": 1, "max": 1}},
        ),
        patch("background_process.db_activity_queries.get_player_activities", new_callable=AsyncMock, return_value=[]),
        patch("background_process.db_content_queries.get_location", new_callable=AsyncMock, return_value=None),
        patch("background_process.db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=[]),
        patch("background_process.build_warm_layer", new_callable=AsyncMock, return_value="host warm") as build,
        patch.object(background, "_apply_warm", new_callable=AsyncMock),
    ):
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            task = asyncio.create_task(background._rebuild_warm_layer())
            await task
    assert [call.args[0] for call in quests.await_args_list] == ["host", "guest"]
    assert [call.args[0] for call in training.await_args_list] == ["host", "guest"]
    assert set(sd.speaker_summaries) == {"host", "guest"}
    assert build.await_args is not None
    assert build.await_args.args[1] == "host"


@pytest.mark.asyncio
async def test_favor_whisper_mark_uses_host_during_guest_turn():
    sd = party_session()
    background = BackgroundProcess(MagicMock(), sd)
    background._speech_queue.append(
        PendingSpeech(priority=SpeechPriority.IMPORTANT, instructions="A whisper", stinger_sound="divine")
    )
    with (
        patch("background_process.publish_companion_cue", new_callable=AsyncMock),
        patch("game_events.publish_game_event", new_callable=AsyncMock),
        patch("background_process.asyncio.sleep", new_callable=AsyncMock),
        patch("background_process.deliver_speech", new_callable=AsyncMock, return_value=True),
        patch(
            "background_process.db_activity_queries.get_divine_favor", new_callable=AsyncMock, return_value={"level": 2}
        ) as favor,
        patch("background_process.db_mutations_divine.mark_favor_whisper_level", new_callable=AsyncMock) as mark,
    ):
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            await background._deliver_speech()
    favor.assert_awaited_once_with("host")
    mark.assert_awaited_once_with("host", 2)
