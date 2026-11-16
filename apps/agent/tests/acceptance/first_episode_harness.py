"""First-episode sessions through the product entrypoint and real room transport."""

import asyncio
import json
import uuid
import wave
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from acceptance._livekit_client import (
    aclose_audio,
    aclose_room,
    connect_room,
    create_microphone_track,
    mint_access_token,
    play_audio_frames,
    register_data_packet_collector,
)
from acceptance.multiplayer_voice._harness import PLAYER_TWO_SPEECH
from acceptance.multiplayer_voice.test_guest_leaves import ToneTTS
from acceptance.voice_condition_harness import CommandSTT, ScenarioModel
from livekit import rtc
from livekit.agents import AgentSession, llm
from livekit.agents.testing import fake_job_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

import agent
import db
import db_queries
from session_data import SessionData


class EpisodeStream(llm.LLMStream):
    def __init__(self, model, *, no_tools, **kwargs):
        super().__init__(model, **kwargs)
        self.model, self.no_tools = model, no_tools

    async def _run(self):
        model = self.model
        for item in self._chat_ctx.items:
            if isinstance(item, llm.FunctionCallOutput) and item.call_id in model.calls:
                model.receipts[item.call_id] = item
        if not self.no_tools and len(model.calls) < len(model.commands):
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
            model.narrated = True
            delta = llm.ChoiceDelta(role="assistant", content="The mist stirs around you.")
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid.uuid4().hex, delta=delta))


class EpisodeModel(ScenarioModel):
    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, tool_choice=None, **kwargs):
        return EpisodeStream(
            self, no_tools=tool_choice == "none", chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options
        )


async def until(predicate):
    async with asyncio.timeout(25):
        while not predicate():
            await asyncio.sleep(0.02)


class Episode:
    session: AgentSession[SessionData]
    source: rtc.AudioSource
    reconnect: Callable[[], Awaitable[None]]

    def __init__(self):
        self.player_id = f"episode-{uuid.uuid4().hex}"
        self.model = EpisodeModel([])
        self.requests = []
        self.events = []
        self.stt = CommandSTT()
        self.speeches = []

    def make_session(self, _model, userdata: SessionData):
        self.session = AgentSession(
            userdata=userdata,
            stt=self.stt,
            llm=self.model,
            tts=ToneTTS(),
            turn_detection="stt",
            min_endpointing_delay=0.01,
        )
        return self.session

    async def turn(self, name, **arguments):
        await until(lambda: self.session.current_speech is None)
        self.model.narrated = False
        self.model.commands.append((name, arguments))
        self.stt.epoch += 1
        await play_audio_frames(self.source, PLAYER_TWO_SPEECH.frames()[:150])
        await until(lambda: len(self.model.receipts) == len(self.model.commands))
        if self.model.failure:
            raise self.model.failure
        await asyncio.sleep(0.1)
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name and receipt.output.strip()
        return receipt

    def packets(self, event_type):
        return [event for event, sender in self.events if event["type"] == event_type and sender == "episode-agent"]


@asynccontextmanager
async def episode(
    server,
    tmp_path,
    *,
    prepare=None,
    initial_agent="CreationAgent",
    reload_companions=False,
    player_id=None,
    preserve=False,
):
    run = Episode()
    if player_id is not None:
        run.player_id = player_id
    # The acceptance fixture opens a new event loop per case; initialize before
    # dm_session starts concurrent readers of the process-scoped pool.
    await db.get_pool()
    if player_id is None:
        assert await db_queries.get_player(run.player_id) is None
    if prepare is not None:
        await prepare(run.player_id)
    if reload_companions:
        from companion_profiles import set_companion_profiles

        set_companion_profiles({})
    room_name = run.player_id

    async def connect(identity):
        token = mint_access_token(
            api_key=server["api_key"], api_secret=server["api_secret"], room_name=room_name, identity=identity
        )
        return await connect_room(server["ws_url"], token)

    player = await connect(run.player_id)
    room = await connect("episode-agent")
    queue = asyncio.Queue()
    unregister = register_data_packet_collector(player, topic="game_events", queue=queue)
    run.source, _track, _publication = await create_microphone_track(
        player,
        sample_rate=16000,
        channels=1,
        name="episode-voice",
    )
    clip = tmp_path / "prologue.wav"
    with wave.open(str(clip), "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 2400)
    from background_process import BackgroundProcess

    queue_speech = BackgroundProcess._queue_speech

    def capture_speech(background, priority, instructions):
        run.speeches.append((priority, instructions))
        queue_speech(background, priority, instructions)

    chat = run.model.chat

    def capture(**kwargs):
        run.requests.append(kwargs)
        return chat(**kwargs)

    async def receive():
        while True:
            payload, sender = await queue.get()
            run.events.append((json.loads(payload), sender))

    async def reconnect():
        nonlocal player, unregister
        owner = run.session.userdata.reconnection_owner
        assert owner is not None
        unregister()
        await aclose_audio(run.source)
        await aclose_room(player)
        await until(lambda: owner.is_disconnected(run.player_id))
        player = await connect(run.player_id)
        unregister = register_data_packet_collector(player, topic="game_events", queue=queue)
        run.source, _, _ = await create_microphone_track(player, sample_rate=16000, channels=1, name="episode-voice")
        await until(lambda: not owner.is_disconnected(run.player_id))

    run.reconnect = reconnect
    receiver = asyncio.create_task(receive())
    with (
        patch("agent._make_agent_session", side_effect=run.make_session),
        patch.object(BackgroundProcess, "_queue_speech", capture_speech),
        patch("base_agent._make_tts", return_value=ToneTTS()),
        patch("session_startup.deepgram.STT", return_value=run.stt),
        patch("prologue.PROLOGUE_PATH", str(clip)),
        patch.object(run.model, "chat", side_effect=capture),
        patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=None),
    ):
        try:
            with fake_job_context(room=room, job_metadata=json.dumps({"player_id": run.player_id})) as ctx:
                await agent.dm_session(ctx)
                if prepare is None and player_id is None:
                    await until(
                        lambda: run.session.current_agent.__class__.__name__ == "CreationAgent" and run.requests
                    )
                else:
                    await until(lambda: run.session.current_agent is not None and run.packets("session_init"))
                    assert run.session.current_agent.__class__.__name__ == initial_agent
                yield run
        finally:
            if hasattr(run, "session"):
                await run.session.aclose()
                if run.session.userdata.multiplayer_close_task:
                    await run.session.userdata.multiplayer_close_task
            if hasattr(run, "session") and run.session.userdata.reconnection_owner:
                await run.session.userdata.reconnection_owner.aclose()
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            unregister()
            await aclose_audio(run.source)
            await aclose_room(player)
            await aclose_room(room)
            if not preserve:
                pool = await db.get_pool()
                await pool.execute("DELETE FROM companion_relationships WHERE player_id = $1", run.player_id)
                await pool.execute("DELETE FROM players WHERE player_id = $1", run.player_id)
