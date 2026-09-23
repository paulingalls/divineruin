"""A real room switches its linked primary while multiplayer audio stays on the transcriber."""

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from acceptance.multiplayer_voice._harness import PLAYER_TWO_SPEECH, MultiplayerVoiceHarness
from acceptance.multiplayer_voice.test_guest_leaves import ScriptedModel, ToneTTS, TranscriptQueue
from acceptance.seeds import seed_player_with_pools
from livekit import rtc
from livekit.agents import AgentSession, stt
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

import db
import db_queries
from exploration_agent import ExplorationAgent
from multiplayer_input import MultiplayerInput
from multiplayer_transcription import AuthenticatedTranscript
from participant_lifecycle import PartyLifecycle, _setup_party_join
from session_data import SessionData
from session_startup import GameplayInputOwner, gameplay_room_options


class LocalStream(stt.RecognizeStream):
    async def _run(self):
        samples = 0
        emitted = False
        async for frame in self._input_ch:
            if emitted or not isinstance(frame, rtc.AudioFrame):
                continue
            if max(abs(sample) for sample in frame.data) < 500:
                continue
            samples += frame.samples_per_channel
            if samples < 12000:
                continue
            emitted = True
            self._event_ch.send_nowait(stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH))
            self._event_ch.send_nowait(
                stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    request_id=uuid.uuid4().hex,
                    alternatives=[stt.SpeechData(language=cast(Any, "en"), text="continue second")],
                )
            )
            self._event_ch.send_nowait(stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH))


class LocalSTT(stt.STT):
    def __init__(self):
        super().__init__(capabilities=stt.STTCapabilities(streaming=True, interim_results=False))

    async def _recognize_impl(self, buffer, *, language, conn_options):
        raise AssertionError("streaming STT should not use one-shot recognition")

    def stream(self, *, language="en", conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return LocalStream(stt=self, conn_options=conn_options)


@pytest.mark.asyncio
async def test_host_goodbye_links_p2_and_p2_audio_reaches_dm(livekit_server, reset_db_pool, monkeypatch):
    for key, value in (
        ("LIVEKIT_URL", livekit_server["ws_url"]),
        ("LIVEKIT_API_KEY", livekit_server["api_key"]),
        ("LIVEKIT_API_SECRET", livekit_server["api_secret"]),
    ):
        monkeypatch.setenv(key, value)
    harness = MultiplayerVoiceHarness(livekit_server)
    host, p2, p3 = harness.player_one_identity, harness.player_two_identity, harness.player_three_identity
    pool = await db.get_pool()
    for identity in (host, p2, p3):
        await seed_player_with_pools(pool, player_id=identity)
    sd = SessionData(player_id=host, location_id="accord_guild_hall")
    model = ScriptedModel()
    session = AgentSession(llm=model, tts=ToneTTS(), max_tool_steps=5, userdata=sd)
    transcripts = TranscriptQueue()
    lifecycle: PartyLifecycle | None = None
    multiplayer_input: MultiplayerInput | None = None

    async def background_wait(_self):
        await asyncio.Event().wait()

    async def prepare(room):
        nonlocal lifecycle
        sd.room = room
        lifecycle = _setup_party_join(room, sd)
        sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=lifecycle))
        with fake_job_context(room=room):
            await session.start(room=room, agent=ExplorationAgent(), room_options=gameplay_room_options(sd))
        return lifecycle.authorize

    with (
        patch("base_agent._make_tts", return_value=ToneTTS()),
        patch("exploration_agent.BackgroundProcess._run", background_wait),
        patch("exploration_agent.ExplorationAgent._publish_session_init", new_callable=AsyncMock),
        patch("exploration_agent.start_specialization_tap"),
        patch("session_end.generate_session_summary", new_callable=AsyncMock, return_value={"summary": "host recap"}),
        patch("background_process.BackgroundProcess._rebuild_warm_layer", new_callable=AsyncMock),
    ):
        try:
            await harness.start(prepare, transcribe=True, third_player=True, stt=LocalSTT())
            assert lifecycle is not None
            for identity in (p2, p3):
                assert await lifecycle.authorize(identity) is not None
            assert gameplay_room_options(sd).get_audio_input_options() is None
            multiplayer_input = MultiplayerInput(transcripts, lifecycle, session, sd)
            multiplayer_input.start()
            host_generation = await lifecycle.authorize(host)
            assert host_generation is not None
            await transcripts.queue.put(AuthenticatedTranscript(host, "goodbye", host_generation))
            async with asyncio.timeout(25):
                while sd.departure_task is None:
                    await asyncio.sleep(0.02)
                await sd.departure_task
            assert session.room_io.linked_participant is not None
            assert session.room_io.linked_participant.identity == p2
            assert sd.party.member_ids == [p2, p3]
            row = await db_queries.get_last_session_summary(host)
            assert row is not None and row["summary"] == "host recap"
            await multiplayer_input.aclose()
            assert harness.manager is not None
            heard_turns = []
            receive = harness.manager.receive

            async def record_receive():
                heard = await receive()
                heard_turns.append(heard)
                return heard

            monkeypatch.setattr(harness.manager, "receive", record_receive)
            multiplayer_input = MultiplayerInput(harness.manager, lifecycle, session, sd)
            multiplayer_input.start()
            await harness.play(p2, PLAYER_TWO_SPEECH)
            async with asyncio.timeout(20):
                while model.turns < 2:
                    await asyncio.sleep(0.02)
            assert any(turn.participant_identity == p2 and turn.text == "continue second" for turn in heard_turns)
            await harness.play(p3, PLAYER_TWO_SPEECH)
            async with asyncio.timeout(20):
                while model.turns < 3:
                    await asyncio.sleep(0.02)
            assert any(turn.participant_identity == p3 and turn.text == "continue second" for turn in heard_turns)
        finally:
            if multiplayer_input is not None:
                await multiplayer_input.aclose()
            await session.aclose()
            if lifecycle is not None:
                await lifecycle.aclose()
            await harness.aclose()
