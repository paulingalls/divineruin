"""A real room keeps the host after the guest's spoken goodbye."""

import asyncio
import json
import math
import struct
import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from acceptance._livekit_client import register_data_packet_collector, wait_for_audio_track
from acceptance.multiplayer_voice._harness import MultiplayerVoiceHarness
from acceptance.seeds import seed_player_with_pools
from livekit import rtc
from livekit.agents import AgentSession, llm, tts
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


class ToneStream(tts.ChunkedStream):
    async def _run(self, output_emitter) -> None:
        samples = [int(12000 * math.sin(2 * math.pi * 440 * i / 24000)) for i in range(18000)]
        output_emitter.initialize(
            request_id=uuid.uuid4().hex, sample_rate=24000, num_channels=1, mime_type="audio/pcm", stream=False
        )
        output_emitter.push(struct.pack(f"<{len(samples)}h", *samples))
        output_emitter.flush()


class ToneTTS(tts.TTS):
    def __init__(self) -> None:
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=24000, num_channels=1)

    def synthesize(self, text: str, *, conn_options=DEFAULT_API_CONNECT_OPTIONS) -> ToneStream:
        return ToneStream(tts=self, input_text=text, conn_options=conn_options)


class ScriptedStream(llm.LLMStream):
    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)
        self.model = model

    async def _run(self) -> None:
        self.model.calls += 1
        if self.model.calls == 1:
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[
                    llm.FunctionToolCall(
                        name="end_session", arguments=json.dumps({"reason": "goodbye"}), call_id=uuid.uuid4().hex
                    )
                ],
            )
        else:
            self.model.turns += 1
            delta = llm.ChoiceDelta(
                role="assistant", content="Farewell, friend." if self.model.turns == 1 else "We continue."
            )
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid.uuid4().hex, delta=delta))


class ScriptedModel(llm.LLM):
    def __init__(self):
        super().__init__()
        self.turns = 0
        self.calls = 0

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_kwargs):
        return ScriptedStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class TranscriptQueue:
    def __init__(self):
        self.queue = asyncio.Queue()

    async def receive(self):
        return await self.queue.get()


@pytest.mark.asyncio
async def test_guest_goodbye_audio_precedes_disconnect_and_host_continues(livekit_server, reset_db_pool, monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", livekit_server["ws_url"])
    monkeypatch.setenv("LIVEKIT_API_KEY", livekit_server["api_key"])
    monkeypatch.setenv("LIVEKIT_API_SECRET", livekit_server["api_secret"])
    harness = MultiplayerVoiceHarness(livekit_server)
    host, guest = harness.player_one_identity, harness.player_two_identity
    pool = await db.get_pool()
    for player_id in (host, guest):
        await seed_player_with_pools(pool, player_id=player_id)
    sd = SessionData(player_id=host, location_id="accord_guild_hall")
    model = ScriptedModel()
    transcripts = TranscriptQueue()
    session = AgentSession(llm=model, tts=ToneTTS(), max_tool_steps=5, userdata=sd)
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
        patch(
            "session_end.generate_session_summary", new_callable=AsyncMock, return_value={"summary": "Guest's journey"}
        ),
    ):
        try:
            await harness.start(prepare, transcribe=False)
            assert lifecycle is not None and harness.player_two is not None and harness.listener is not None
            generation = await lifecycle.authorize(guest)
            assert generation is not None
            guest_events = asyncio.Queue()
            register_data_packet_collector(harness.player_two, topic="game_events", queue=guest_events)
            track = await wait_for_audio_track(harness.player_two, identity=harness.listener.local_participant.identity)
            stream = rtc.AudioStream(track)
            audio_seconds = 0.0
            audio_at_disconnect = None
            disconnected = asyncio.Event()

            def on_disconnect():
                nonlocal audio_at_disconnect
                audio_at_disconnect = audio_seconds
                disconnected.set()

            harness.player_two.on("disconnected", on_disconnect)

            async def collect_audio():
                nonlocal audio_seconds
                async for event in stream:
                    audio_seconds += event.frame.duration
                    if disconnected.is_set():
                        break

            audio_task = asyncio.create_task(collect_audio())
            multiplayer_input = MultiplayerInput(transcripts, lifecycle, session, sd)
            multiplayer_input.start()
            await transcripts.queue.put(AuthenticatedTranscript(guest, "goodbye", generation))
            try:
                async with asyncio.timeout(15):
                    while sd.departure_task is None:
                        await asyncio.sleep(0.02)
                    await sd.departure_task
                    await disconnected.wait()
            except TimeoutError as exc:
                raise AssertionError(
                    f"Departure stalled: calls={model.calls}, turns={model.turns}, pending={sd.departing_player_id}, "
                    f"history={[type(item).__name__ for item in session.history.items]}, input={multiplayer_input._task!r}"
                ) from exc
            assert audio_at_disconnect is not None and audio_at_disconnect >= 0.5
            events = []
            while not guest_events.empty():
                events.append(json.loads((await guest_events.get())[0]))
            assert any(e.get("type") == "session_end" and e.get("player_id") == guest for e in events)
            assert sd.party.member_ids == [host]
            assert await lifecycle.authorize(guest) is None
            assert sd.background is not None and sd.background._task is not None and not sd.background._task.done()
            row = await db_queries.get_last_session_summary(guest)
            assert row is not None and row["summary"] == "Guest's journey"
            assert await db_queries.get_last_session_summary(host) is None
            host_generation = await lifecycle.authorize(host)
            assert host_generation is not None
            await transcripts.queue.put(AuthenticatedTranscript(host, "continue", host_generation))
            async with asyncio.timeout(20):
                while model.turns < 2:
                    await asyncio.sleep(0.02)
            assert harness.player_one is not None
            assert session.current_agent is not None and harness.player_one.isconnected()
        finally:
            if "stream" in locals():
                await stream.aclose()
            if "audio_task" in locals():
                audio_task.cancel()
                await asyncio.gather(audio_task, return_exceptions=True)
            if multiplayer_input is not None:
                await multiplayer_input.aclose()
            await session.aclose()
            if lifecycle is not None:
                await lifecycle.aclose()
            await harness.aclose()
