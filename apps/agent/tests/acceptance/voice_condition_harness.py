"""Deterministic owned speech/model seams over the real LiveKit transport."""

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from acceptance._livekit_client import register_data_packet_collector, wait_for_audio_track
from acceptance.multiplayer_voice._harness import PLAYER_TWO_SPEECH
from acceptance.multiplayer_voice.test_guest_leaves import ToneTTS
from acceptance.multiplayer_voice.test_host_handoff import LocalSTT
from livekit import rtc
from livekit.agents import AgentSession, llm
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

from multiplayer_input import MultiplayerInput
from participant_lifecycle import PartyLifecycle, _setup_party_join
from session_startup import GameplayInputOwner, gameplay_room_options


class ScenarioStream(llm.LLMStream):
    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)
        self.model = model

    async def _run(self):
        model = self.model
        for item in self._chat_ctx.items:
            if isinstance(item, llm.FunctionCallOutput) and item.call_id in model.calls:
                model.receipts[item.call_id] = item
        if len(model.calls) < len(model.commands):
            name, arguments = model.commands[len(model.calls)]
            call_id = uuid.uuid4().hex
            model.calls[call_id] = name
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[
                    llm.FunctionToolCall(
                        name=name,
                        arguments=json.dumps(arguments),
                        call_id=call_id,
                    )
                ],
            )
        else:
            assert_receipt_floor(model)
            model.narrated = True
            refused = any(output.is_error for output in model.receipts.values())
            model.narration = "Your voice reaches me. You cannot speak here." if refused else "Your action resolves."
            delta = llm.ChoiceDelta(role="assistant", content=model.narration)
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid.uuid4().hex, delta=delta))


class ScenarioModel(llm.LLM):
    def __init__(self, commands):
        super().__init__()
        self.commands = commands
        self.calls = {}
        self.receipts = {}
        self.narrated = False
        self.narration = ""

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_kwargs):
        return ScenarioStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


def assert_receipt_floor(model):
    assert model.commands, "empty command manifest"
    assert len(model.calls) == len(model.commands), "missing executed command"
    assert set(model.receipts) == set(model.calls), "missing DM receipt"
    assert all(output.output.strip() for output in model.receipts.values()), "empty tool result"


def assert_hud_floor(events):
    assert events, "no received HUD events"

    def walk(value):
        if isinstance(value, dict):
            assert not {"x", "y", "z", "positions", "distances_ft", "resonance_generated", "resonance_current"} & set(
                value
            ), "mechanical HUD payload"
            for key, item in value.items():
                if key == "resonance":
                    assert not isinstance(item, (int, float)), "raw Resonance HUD payload"
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for event in events:
        walk(event)


async def run_voice_commands(harness, sd, model, agent, monkeypatch, *, speaker=None, require_hud=True):
    host, guest = harness.player_one_identity, harness.player_two_identity
    session = AgentSession(llm=model, tts=ToneTTS(), max_tool_steps=5, userdata=sd)
    lifecycle: PartyLifecycle | None = None
    multiplayer = None
    stream: rtc.AudioStream | None = None
    audio_task = None
    received_audio = []
    transcripts = []
    events = asyncio.Queue()

    async def prepare(room):
        nonlocal lifecycle
        sd.room = room
        lifecycle = _setup_party_join(room, sd)
        sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=lifecycle))
        with fake_job_context(room=room):
            await session.start(room=room, agent=agent, room_options=gameplay_room_options(sd))
        return lifecycle.authorize

    async def capture_audio():
        assert stream is not None
        async for event in stream:
            if max(abs(sample) for sample in event.frame.data) > 500:
                received_audio.append(event.frame.duration)

    with patch("base_agent._make_tts", return_value=ToneTTS()):
        try:
            await harness.start(prepare, transcribe=True, stt=LocalSTT())
            assert (
                lifecycle is not None
                and harness.manager is not None
                and harness.player_two is not None
                and harness.listener is not None
            )
            active_lifecycle = cast(PartyLifecycle, lifecycle)
            assert await active_lifecycle.authorize(guest) is not None
            register_data_packet_collector(harness.player_two, topic="game_events", queue=events)
            track = await wait_for_audio_track(harness.player_two, identity=harness.listener.local_participant.identity)
            stream = rtc.AudioStream(track)
            audio_task = asyncio.create_task(capture_audio())
            receive = harness.manager.receive

            async def record_receive():
                heard = await receive()
                transcripts.append(heard)
                return heard

            monkeypatch.setattr(harness.manager, "receive", record_receive)
            multiplayer = MultiplayerInput(harness.manager, active_lifecycle, session, sd)
            multiplayer.start()
            assert not model.calls, "gameplay command executed before microphone input"
            speaker = speaker or host
            await harness.play(speaker, PLAYER_TWO_SPEECH)
            try:
                async with asyncio.timeout(25):
                    while not model.narrated or sum(received_audio) < 0.2:
                        await asyncio.sleep(0.02)
            except TimeoutError as error:
                raise AssertionError("microphone command produced no complete gameplay/DM/audio receipt") from error
            assert any(turn.participant_identity == speaker and turn.text == "continue second" for turn in transcripts)
            assert_receipt_floor(model)
            hud = []
            async with asyncio.timeout(5):
                if require_hud and events.empty():
                    data, identity = await events.get()
                    assert identity == harness.listener.local_participant.identity
                    hud.append(json.loads(data))
            while not events.empty():
                data, identity = events.get_nowait()
                assert identity == harness.listener.local_participant.identity
                hud.append(json.loads(data))
            return hud
        finally:
            if multiplayer is not None:
                await multiplayer.aclose()
            if audio_task is not None:
                audio_task.cancel()
                await asyncio.gather(audio_task, return_exceptions=True)
            if stream is not None:
                await stream.aclose()
            await session.aclose()
            if lifecycle is not None:
                await cast(PartyLifecycle, lifecycle).aclose()
            await harness.aclose()
