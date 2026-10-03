"""Owned deterministic speech/model seams; commands remain on public gameplay dispatch."""

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from acceptance.multiplayer_voice._harness import PLAYER_TWO_SPEECH, SpeechFixture
from acceptance.multiplayer_voice.test_guest_leaves import ToneTTS
from acceptance.seeds import seed_player_with_pools
from acceptance.test_voice_condition_commands import commands, scene
from acceptance.voice_condition_harness import ScenarioModel
from livekit import rtc
from livekit.agents import AgentSession, llm, stt
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

import db
import db_mutations
import db_queries
from combat_agent import CombatAgent
from multiplayer_input import MultiplayerInput
from participant_lifecycle import _setup_party_join
from session_data import SessionData
from session_startup import GameplayInputOwner, gameplay_room_options


class RecordedCommandBurst(SpeechFixture):
    def frames(self):
        recording = super().frames()
        start = next((i for i, frame in enumerate(recording) if max(map(abs, frame.data)) >= 500), None)
        if start is None:
            raise ValueError("command recording has no voiced audio")
        voiced = recording[start : start + 18]
        if len(voiced) != 18 or any(max(map(abs, frame.data)) < 500 for frame in voiced):
            raise ValueError("command recording lacks a sustained speech burst")
        frame = voiced[0]
        silence = [
            rtc.AudioFrame(
                bytes(frame.samples_per_channel * 2), frame.sample_rate, frame.num_channels, frame.samples_per_channel
            )
            for _ in range(30)
        ]
        return [*voiced, *silence]


# BurstSTT classifies amplitude and turn boundaries; this transport test needs no full sentence.
CHOIR_COMMAND_SPEECH = RecordedCommandBurst(
    filename=PLAYER_TWO_SPEECH.filename,
    utterance_id=PLAYER_TWO_SPEECH.utterance_id,
    transcript=PLAYER_TWO_SPEECH.transcript,
    sha256=PLAYER_TWO_SPEECH.sha256,
)


class BurstStream(stt.RecognizeStream):
    async def _run(self):
        voiced = quiet = 0.0
        turn = 0
        active = False
        async for frame in self._input_ch:
            if not isinstance(frame, rtc.AudioFrame):
                continue
            if max(abs(sample) for sample in frame.data) >= 500:
                quiet = 0.0
                if not active:
                    voiced += frame.duration
                if not active and voiced >= 0.25:
                    active = True
                    turn += 1
                    self._event_ch.send_nowait(stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH))
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(
                            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                            request_id=uuid.uuid4().hex,
                            alternatives=[stt.SpeechData(language=cast(Any, "en"), text=f"capstone turn {turn}")],
                        )
                    )
            elif not active:
                voiced = 0.0
            else:
                quiet += frame.duration
                if quiet >= 0.5:
                    self._event_ch.send_nowait(stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH))
                    active = False
                    voiced = quiet = 0.0


class BurstSTT(stt.STT):
    def __init__(self):
        super().__init__(capabilities=stt.STTCapabilities(streaming=True, interim_results=False))

    async def _recognize_impl(self, buffer, *, language, conn_options):
        raise AssertionError("capstone requires streaming microphone input")

    def stream(self, *, language="en", conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return BurstStream(stt=self, conn_options=conn_options)


class TurnStream(llm.LLMStream):
    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)
        self.model = model

    async def _run(self):
        model = self.model
        for item in self._chat_ctx.items:
            if isinstance(item, llm.FunctionCallOutput) and item.call_id in model.calls:
                model.receipts[item.call_id] = item
        texts = [
            item.text_content or ""
            for item in self._chat_ctx.items
            if isinstance(item, llm.ChatMessage) and item.role == "user"
        ]
        available = max(
            (int(text.split("capstone turn ")[-1].split()[0]) for text in texts if "capstone turn " in text), default=0
        )
        if len(model.calls) < min(available, len(model.commands)):
            name, arguments = model.commands[len(model.calls)]
            call_id = uuid.uuid4().hex
            model.calls[call_id] = name
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[llm.FunctionToolCall(name=name, arguments=json.dumps(arguments), call_id=call_id)],
            )
        else:
            delta = llm.ChoiceDelta(role="assistant", content="Your command reaches me.")
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid.uuid4().hex, delta=delta))


class TurnModel(ScenarioModel):
    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_kwargs):
        return TurnStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class ChoirVoiceDiagnostic:
    def __init__(self, player_id):
        self.player_id = player_id
        self.model: ScenarioModel = TurnModel(commands("silenced_cast", player_id))
        self.transcripts = []
        self.session = self.lifecycle = self.multiplayer = None
        self.before = None
        self.tts_patch = patch("base_agent._make_tts", return_value=ToneTTS())

    async def start(self, room):
        from acceptance.choir_capstone_harness import reseed_choir_content

        pool = await db.get_pool()
        await reseed_choir_content(pool)
        await seed_player_with_pools(pool, player_id=self.player_id, class_="mage", focus_current=10)
        sd = SessionData(player_id=self.player_id, location_id="accord_guild_hall")
        sd.combat_state = scene(self.player_id, "outside-observer", "silenced_cast")
        await db_mutations.save_combat_state(sd.combat_state.combat_id, sd.combat_state.to_dict())
        self.before = (sd.combat_state.to_dict(), await db_queries.get_player(self.player_id))
        self.sd = sd
        sd.room = room
        self.lifecycle = _setup_party_join(room, sd)
        sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=self.lifecycle))
        self.session = AgentSession(llm=self.model, tts=ToneTTS(), max_tool_steps=5, userdata=sd)
        self.tts_patch.start()
        with fake_job_context(room=room):
            await self.session.start(room=room, agent=CombatAgent(), room_options=gameplay_room_options(sd))

    def attach(self, manager):
        diagnostic = self

        class Receiver:
            async def receive(self):
                heard = await manager.receive()
                diagnostic.transcripts.append(heard)
                return heard

        self.multiplayer = MultiplayerInput(Receiver(), self.lifecycle, self.session, self.sd)
        self.multiplayer.start()

    async def wait_for_receipts(self, count, timeout=25):
        try:
            async with asyncio.timeout(timeout):
                while len(self.model.receipts) < count:
                    await asyncio.sleep(0.02)
        except TimeoutError as exc:
            raise AssertionError(f"missing separate authenticated turn {count} and gameplay receipt") from exc

    async def assert_refusal_unchanged(self):
        refusal = next(iter(self.model.receipts.values()))
        assert refusal.name == "declare_phase" and refusal.is_error and "silenced" in refusal.output
        assert self.sd.combat_state is not None
        saved = await db_mutations.load_combat_state(self.sd.combat_state.combat_id)
        assert saved is not None and self.before is not None
        assert saved.to_dict() == self.before[0]
        assert await db_queries.get_player(self.player_id) == self.before[1]

    def assert_complete(self):
        assert len(self.transcripts) == 2, "missing separate authenticated turn"
        assert [turn.text for turn in self.transcripts] == ["capstone turn 1", "capstone turn 2"]
        assert all(turn.participant_identity == self.player_id and turn.generation > 0 for turn in self.transcripts)
        assert all(turn.speech_events for turn in self.transcripts)
        assert len(self.model.calls) == len(self.model.receipts) == 2
        legal = list(self.model.receipts.values())[1]
        assert legal.name == "check" and not legal.is_error and legal.output.strip()

    async def aclose(self):
        try:
            if self.multiplayer is not None:
                await self.multiplayer.aclose()
        finally:
            try:
                if self.session is not None:
                    await self.session.aclose()
            finally:
                self.tts_patch.stop()
                if self.lifecycle is not None:
                    await self.lifecycle.aclose()


class OwnedStimulusStream(stt.RecognizeStream):
    def __init__(self, *, stt, conn_options):
        from acceptance.choir_acoustic_source import AcousticSource

        super().__init__(stt=stt, conn_options=conn_options)
        self.source = AcousticSource(stt.run_id)
        stt.sources.append(self.source)

    async def _run(self):
        source = self.source
        async for frame in self._input_ch:
            if not isinstance(frame, rtc.AudioFrame):
                continue
            receipt = source.observe(frame.data, frame.sample_rate)
            if receipt is None:
                continue
            self._event_ch.send_nowait(stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH))
            self._event_ch.send_nowait(
                stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    request_id=uuid.uuid4().hex,
                    alternatives=[stt.SpeechData(language=cast(Any, "en"), text=f"capstone turn {receipt['turn']}")],
                )
            )
            self._event_ch.send_nowait(stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH))


class OwnedStimulusSTT(BurstSTT):
    def __init__(self, run_id):
        super().__init__()
        self.run_id = run_id
        self.sources = []

    @property
    def source_receipts(self):
        return [receipt for source in self.sources for receipt in source.receipts]

    def stream(self, *, language="en", conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return OwnedStimulusStream(stt=self, conn_options=conn_options)
