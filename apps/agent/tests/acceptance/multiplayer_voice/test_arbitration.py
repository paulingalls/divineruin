from __future__ import annotations

import asyncio
import json
import math
import uuid
from typing import Any

import pytest
from acceptance.multiplayer_voice._harness import (
    PLAYER_ONE_SPEECH,
    PLAYER_TWO_SPEECH,
    MultiplayerVoiceHarness,
    PlayTrace,
    SpeechFixture,
    normalized,
)
from livekit import rtc
from livekit.agents import Agent, AgentSession, RunContext, llm
from livekit.agents.llm import function_tool
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.plugins import deepgram

from multiplayer_input import MultiplayerInput
from participant_lifecycle import _setup_party_join
from session_data import SessionData
from session_startup import gameplay_room_options

STT_DOLLARS_PER_MINUTE = 0.0065


class ArbitrationLLMStream(llm.LLMStream):
    def __init__(self, model: ArbitrationLLM, **kwargs: Any) -> None:
        super().__init__(model, **kwargs)
        self.model = model

    async def _run(self) -> None:
        last = self.chat_ctx.items[-1]
        request_id = uuid.uuid4().hex
        if isinstance(last, llm.ChatMessage) and last.role == "user":
            text = last.text_content or ""
            call_id = f"probe-{request_id}"
            self.model.starts.append((self.model.phase, text, asyncio.get_running_loop().time()))
            self.model.calls[call_id] = (self.model.phase, text)
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[llm.FunctionToolCall(name="probe_actor", arguments="{}", call_id=call_id)],
            )
        else:
            self.model.completed += 1
            delta = llm.ChoiceDelta(role="assistant", content="Acknowledged.")
        self._event_ch.send_nowait(llm.ChatChunk(id=request_id, delta=delta))


class ArbitrationLLM(llm.LLM):
    def __init__(self) -> None:
        super().__init__()
        self.phase = "solo"
        self.starts: list[tuple[str, str, float]] = []
        self.calls: dict[str, tuple[str, str]] = {}
        self.completed = 0

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_kwargs):
        return ArbitrationLLMStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class Queries:
    async def get_player(self, player_id: str) -> dict[str, str]:
        return {"player_id": player_id}


class Resonance:
    async def read_player_resonance(self, _player_id: str) -> dict[str, int]:
        return {"current": 0, "flickering_bonus": 0}


class Concentration:
    async def read_player_concentration(self, _player_id: str) -> dict[str, None]:
        return {"spell_id": None}


def recognized_fixture(text: str) -> SpeechFixture:
    heard = set(normalized(text).split())
    fixtures = (PLAYER_ONE_SPEECH, PLAYER_TWO_SPEECH)
    scores = [len(heard & set(normalized(fixture.transcript).split())) for fixture in fixtures]
    assert max(scores) >= 3
    assert scores[0] != scores[1]
    return fixtures[scores.index(max(scores))]


def fixture_start(model: ArbitrationLLM, phase: str, fixture: SpeechFixture) -> float:
    matches = [
        started
        for seen_phase, text, started in model.starts
        if seen_phase == phase and recognized_fixture(text) is fixture
    ]
    assert len(matches) == 1
    return matches[0]


def trace_record(trace: PlayTrace, dm_start: float, *, queued: bool) -> dict[str, Any]:
    latency = dm_start - trace.speech_end
    cost = trace.frame_seconds / 60 * STT_DOLLARS_PER_MINUTE
    assert math.isfinite(latency) and latency >= 0
    assert cost == pytest.approx(trace.frame_seconds / 60 * 0.0065)
    return {
        "identity": trace.identity,
        "frame_seconds": round(trace.frame_seconds, 6),
        "speech_end_to_dm_start_seconds": round(latency, 6),
        "queued": queued,
        "stt_cost_usd": round(cost, 9),
    }


async def test_real_overlapping_speech_serializes_authenticated_tool_turns(
    livekit_server: dict[str, str],
) -> None:
    harness = MultiplayerVoiceHarness(livekit_server)
    userdata = SessionData(player_id=harness.player_one_identity, location_id="acceptance")
    model = ArbitrationLLM()
    probes: list[tuple[str, str, str]] = []
    gate_enabled = False
    gate_started = asyncio.Event()
    gate_release = asyncio.Event()
    handles = []
    dm_session: AgentSession | None = None
    multiplayer_input: MultiplayerInput | None = None
    lifecycle = None

    @function_tool()
    async def probe_actor(context: RunContext[SessionData]) -> str:
        phase, text = model.calls[context.function_call.call_id]
        probes.append((phase, text, context.userdata.actor_player_id))
        if gate_enabled and not gate_started.is_set():
            gate_started.set()
            await gate_release.wait()
        return "actor recorded"

    async def prepare_listener(room: rtc.Room):
        nonlocal dm_session, lifecycle
        lifecycle = _setup_party_join(
            room,
            userdata,
            queries=Queries(),
            resonance_mod=Resonance(),
            concentration_mod=Concentration(),
        )
        dm_session = AgentSession(
            llm=model,
            stt=deepgram.STT(model="nova-3", language="en-US", endpointing_ms=300),
            max_tool_steps=5,
            userdata=userdata,
        )
        dm_session.output.set_audio_enabled(False)
        with fake_job_context(room=room):
            await dm_session.start(
                room=room,
                agent=Agent(instructions="Always call probe_actor once, then acknowledge.", tools=[probe_actor]),
                room_options=gameplay_room_options(userdata),
            )
        original_generate_reply = dm_session.generate_reply

        def track_reply(**kwargs):
            handle = original_generate_reply(**kwargs)
            handles.append(handle)
            return handle

        dm_session.generate_reply = track_reply
        return lifecycle.authorize

    async def wait_until(predicate, message: str) -> None:
        assert harness.manager is not None and dm_session is not None
        try:
            async with asyncio.timeout(30):
                while not predicate():
                    await asyncio.sleep(0.02)
        except TimeoutError as exc:
            users = [item.text_content for item in dm_session.history.messages() if item.role == "user"]
            raise TimeoutError(
                f"{message}: starts={model.starts}, probes={probes}, completed={model.completed}, "
                f"queue={harness.manager._queue.qsize()}/{harness.manager._queue.maxsize}, users={users}"
            ) from exc

    try:
        await harness.start(prepare_listener)
        assert harness.manager is not None and dm_session is not None and lifecycle is not None
        pending_queue = harness.manager._queue
        multiplayer_input = MultiplayerInput(harness.manager, lifecycle, dm_session, userdata)
        multiplayer_input.start()

        solo_trace = await harness.play(harness.player_two_identity, PLAYER_TWO_SPEECH)
        await wait_until(lambda: model.completed == 1, "solo turn stalled")
        solo_start = fixture_start(model, "solo", PLAYER_TWO_SPEECH)
        assert len(probes) == 1
        assert probes[0][0] == "solo"
        assert probes[0][2] == harness.player_two_identity
        assert recognized_fixture(probes[0][1]) is PLAYER_TWO_SPEECH

        assert PLAYER_ONE_SPEECH.utterance_id.split("-", 1)[0] == "1272"
        assert PLAYER_TWO_SPEECH.utterance_id.split("-", 1)[0] == "1272"
        model.phase = "overlap"
        gate_enabled = True
        one_frames = PLAYER_ONE_SPEECH.frames()
        two_frames = PLAYER_TWO_SPEECH.frames()
        one_seconds = sum(frame.samples_per_channel / frame.sample_rate for frame in one_frames)
        two_seconds = sum(frame.samples_per_channel / frame.sample_rate for frame in two_frames)
        first = asyncio.create_task(harness.play(harness.player_one_identity, PLAYER_ONE_SPEECH))
        await asyncio.sleep(one_seconds - two_seconds)
        second = asyncio.create_task(harness.play(harness.player_two_identity, PLAYER_TWO_SPEECH))
        one_trace, two_trace = await asyncio.gather(first, second)

        await wait_until(gate_started.is_set, "first overlapping tool did not start")
        await wait_until(lambda: pending_queue.qsize() >= 1, "second overlapping turn was not queued")
        overlap_starts = [entry for entry in model.starts if entry[0] == "overlap"]
        assert len(overlap_starts) == 1
        assert len(handles) == 2
        assert handles[-1].interrupted is False

        gate_release.set()
        await wait_until(lambda: model.completed == 3, "serialized overlapping turns stalled")
        overlap_probes = [entry for entry in probes if entry[0] == "overlap"]
        assert len(overlap_probes) == 2
        expected = {
            PLAYER_ONE_SPEECH: harness.player_one_identity,
            PLAYER_TWO_SPEECH: harness.player_two_identity,
        }
        for _phase, text, actor in overlap_probes:
            assert actor == expected[recognized_fixture(text)]
        users = [item.text_content or "" for item in dm_session.history.messages() if item.role == "user"]
        assert len(users) == 3
        recognized = [recognized_fixture(text) for text in users]
        assert recognized.count(PLAYER_ONE_SPEECH) == 1, (users, probes)
        assert recognized.count(PLAYER_TWO_SPEECH) == 2, (users, probes)

        first_fixture = recognized_fixture(overlap_starts[0][1])
        records = [trace_record(solo_trace, solo_start, queued=False)]
        for trace, fixture in ((one_trace, PLAYER_ONE_SPEECH), (two_trace, PLAYER_TWO_SPEECH)):
            records.append(
                trace_record(
                    trace,
                    fixture_start(model, "overlap", fixture),
                    queued=fixture is not first_fixture,
                )
            )
        print("MULTIPLAYER_ARBITRATION_MEASUREMENT=" + json.dumps(records, sort_keys=True))
    finally:
        gate_release.set()
        if multiplayer_input is not None:
            await multiplayer_input.aclose()
        if dm_session is not None:
            await dm_session.aclose()
        await harness.aclose()
