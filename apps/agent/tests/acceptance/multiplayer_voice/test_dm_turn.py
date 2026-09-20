from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from acceptance.multiplayer_voice._harness import PLAYER_ONE_SPEECH, PLAYER_TWO_SPEECH, MultiplayerVoiceHarness
from livekit import rtc
from livekit.agents import Agent, AgentSession, RunContext, llm
from livekit.agents.llm import ToolContext, function_tool
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.plugins import deepgram

from multiplayer_input import MultiplayerInput
from participant_lifecycle import _setup_party_join
from session_data import SessionData
from session_startup import gameplay_room_options


class ProbeLLMStream(llm.LLMStream):
    def __init__(self, probe: ProbeLLM, **kwargs: Any) -> None:
        super().__init__(probe, **kwargs)
        self.probe = probe

    async def _run(self) -> None:
        last = self.chat_ctx.items[-1]
        request_id = uuid.uuid4().hex
        if isinstance(last, llm.ChatMessage) and last.role == "user":
            call = llm.FunctionToolCall(
                name="probe_actor",
                arguments="{}",
                call_id=f"probe-{request_id}",
            )
            delta = llm.ChoiceDelta(role="assistant", tool_calls=[call])
        else:
            self.probe.completed_turns += 1
            delta = llm.ChoiceDelta(role="assistant", content="Acknowledged.")
        self._event_ch.send_nowait(llm.ChatChunk(id=request_id, delta=delta))


class ProbeLLM(llm.LLM):
    def __init__(self) -> None:
        super().__init__()
        self.completed_turns = 0

    def chat(
        self,
        *,
        chat_ctx,
        tools=None,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        **_kwargs,
    ) -> llm.LLMStream:
        return ProbeLLMStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class Queries:
    async def get_player(self, player_id: str) -> dict[str, str]:
        return {"player_id": player_id}


class Resonance:
    async def read_player_resonance(self, _player_id: str) -> dict[str, Any]:
        return {"current": 0, "flickering_bonus": 0}


class Concentration:
    async def read_player_concentration(self, _player_id: str) -> dict[str, Any]:
        return {"spell_id": None}


async def test_dm_turn_routes_each_real_microphone_once_with_authenticated_actor(
    livekit_server: dict[str, str],
) -> None:
    harness = MultiplayerVoiceHarness(livekit_server)
    userdata = SessionData(player_id=harness.player_one_identity, location_id="acceptance")
    model = ProbeLLM()
    probes: list[str] = []
    dm_session: AgentSession | None = None
    multiplayer_input: MultiplayerInput | None = None
    lifecycle = None

    @function_tool()
    async def probe_actor(context: RunContext[SessionData]) -> str:
        await asyncio.sleep(0)
        probes.append(context.userdata.actor_player_id)
        return "actor recorded"

    schema = ToolContext([probe_actor]).parse_function_tools("anthropic", strict=True)[0]["input_schema"]
    assert schema["properties"] == {}
    assert schema.get("required", []) == []

    async def prepare_listener(room: rtc.Room):
        nonlocal dm_session, lifecycle
        lifecycle = _setup_party_join(
            room,
            userdata,
            queries=Queries(),
            resonance_mod=Resonance(),
            concentration_mod=Concentration(),
        )
        options = gameplay_room_options()
        assert options.get_audio_input_options() is None
        assert options.get_text_input_options() is None
        # A real STT on the DM session is what makes "the primary is not heard twice" a
        # BEHAVIOURAL claim: with linked audio input re-enabled this session would transcribe
        # player one itself, and the one-user-message-per-marker assertions below would red.
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
                room_options=options,
            )
        return lifecycle.authorize

    async def wait_for_turns(expected: int, marker: str) -> None:
        assert harness.manager is not None and dm_session is not None
        try:
            async with asyncio.timeout(30):
                while True:
                    users = [m.text_content or "" for m in dm_session.history.messages() if m.role == "user"]
                    if (
                        len(probes) >= expected
                        and model.completed_turns >= expected
                        and sum(marker in text.lower() for text in users) == 1
                    ):
                        return
                    await asyncio.sleep(0.02)
        except TimeoutError as exc:
            users = [m.text_content for m in dm_session.history.messages() if m.role == "user"]
            raise TimeoutError(
                f"DM turns stalled: expected={expected}, probes={probes}, completed={model.completed_turns}, "
                f"active={sorted(harness.manager.active_identities)}, users={users}"
            ) from exc

    try:
        await harness.start(prepare_listener)
        assert harness.manager is not None and dm_session is not None
        assert lifecycle is not None
        multiplayer_input = MultiplayerInput(harness.manager, lifecycle, dm_session, userdata)
        multiplayer_input.start()

        await harness.play(harness.player_two_identity, PLAYER_TWO_SPEECH)
        await wait_for_turns(1, PLAYER_TWO_SPEECH.marker)
        await harness.play(harness.player_one_identity, PLAYER_ONE_SPEECH)
        await wait_for_turns(2, PLAYER_ONE_SPEECH.marker)

        users = [m.text_content or "" for m in dm_session.history.messages() if m.role == "user"]
        assert sum(PLAYER_TWO_SPEECH.marker in text.lower() for text in users) == 1
        assert sum(PLAYER_ONE_SPEECH.marker in text.lower() for text in users) == 1
        assert probes == [harness.player_two_identity, harness.player_one_identity]
        with pytest.raises(RuntimeError, match="No actor"):
            _ = userdata.actor_player_id
    finally:
        if multiplayer_input is not None:
            await multiplayer_input.aclose()
        if dm_session is not None:
            await dm_session.aclose()
        await harness.aclose()
