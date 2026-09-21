import asyncio
import logging
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import Agent, room_io
from livekit.agents.voice import SpeechHandle
from livekit.agents.voice.speech_handle import InputDetails

from session_data import SessionData
from session_startup import GameplayInputOwner, gameplay_room_options, solo_room_options, start_gameplay_session
from speech_delivery import deliver_player_turn


def test_gameplay_room_options_pin_primary_and_disable_vendor_close() -> None:
    sd = SessionData(player_id="player-one", location_id="loc")

    options = gameplay_room_options(sd)

    assert isinstance(options, room_io.RoomOptions)
    assert options.participant_identity == "player-one"
    assert options.close_on_disconnect is False
    assert options.audio_input is False
    assert options.text_input is False
    assert options.get_audio_input_options() is None
    assert options.get_text_input_options() is None


def test_solo_room_options_keep_the_microphone_the_pre_gameplay_agents_are_the_only_ear_for() -> None:
    """Creation and onboarding have no MultiParticipantTranscriber; room audio is their only input."""
    sd = SessionData(player_id="player-one", location_id="loc")

    options = solo_room_options(sd)

    assert isinstance(options, room_io.RoomOptions)
    assert options.participant_identity == "player-one"
    assert options.close_on_disconnect is False
    assert options.get_audio_input_options() is not None


async def test_prologue_start_installs_primary_room_options() -> None:
    from agent import dm_session

    ctx = MagicMock()
    ctx.job = None
    ctx.room = MagicMock()
    session = MagicMock()
    session.start = AsyncMock()
    with (
        patch("agent._make_agent_session", return_value=session),
        patch("agent._setup_reconnection"),
        patch("agent.db_queries.get_player", new_callable=AsyncMock, return_value=None),
        patch("agent.db_queries.get_last_session_summary", new_callable=AsyncMock, return_value=None),
    ):
        await dm_session(ctx)

    options = session.start.call_args.kwargs["room_options"]
    assert isinstance(options, room_io.RoomOptions)
    assert options.participant_identity == "player_1"
    assert options.close_on_disconnect is False
    assert options.get_audio_input_options() is not None


async def test_revocation_force_interrupts_a_real_uninterruptible_speech_handle() -> None:
    handle = SpeechHandle(
        speech_id="revoked-player-turn",
        allow_interruptions=False,
        input_details=InputDetails(modality="text"),
    )
    revoked = asyncio.Event()
    session = MagicMock()
    # The real Agent, because deliver_player_turn runs its per-turn hook before replying.
    session.current_agent = Agent(instructions="revocation double")
    session.generate_reply.return_value = handle

    async def finish_interrupted_handle() -> None:
        await handle._interrupt_fut
        handle._mark_done()

    async def wait_until_revoked() -> None:
        await revoked.wait()

    finishing = asyncio.create_task(finish_interrupted_handle())
    delivery = asyncio.create_task(
        deliver_player_turn(
            session,
            "stale turn",
            logging.getLogger("test"),
            "revoked turn",
            revoked=wait_until_revoked,
        )
    )
    await asyncio.sleep(0)
    revoked.set()

    assert await asyncio.wait_for(delivery, 1) is True
    assert handle.interrupted is True
    await finishing


async def test_gameplay_start_owns_inputs_and_closes_them_with_session(monkeypatch) -> None:
    events = []

    class Room:
        remote_participants = {}

        def __init__(self):
            self.listeners = {}

        def on(self, event, callback):
            events.append(f"room:{event}")
            self.listeners.setdefault(event, []).append(callback)

        def off(self, event, callback):
            self.listeners[event].remove(callback)

    class Session:
        def __init__(self):
            self.listeners = {}
            self.start_kwargs = None
            self.current_agent = None

        async def start(self, **kwargs):
            events.append("session:start")
            self.start_kwargs = kwargs
            self.current_agent = kwargs["agent"]

        def on(self, event, callback):
            self.listeners[event] = callback

    monkeypatch.setattr("session_startup.deepgram.STT", lambda **_kwargs: object())
    room = Room()
    session = Session()
    sd = SessionData(player_id="player-one", location_id="loc")
    agent = MagicMock()

    owner = await start_gameplay_session(room, cast(Any, session), agent, sd)

    assert sd.multiplayer_owner is owner
    observe_player_speech = owner.input.observe_player_speech
    assert observe_player_speech is not None
    observe_player_speech((), "player-one", "I inspect the door")
    agent.observe_player_speech.assert_called_once_with((), "player-one", "I inspect the door")

    # enter_combat hands the floor to a new agent and closes the outgoing agent's transcript
    # logger and affect analyzer, so the fork has to follow the handoff, not the startup agent.
    combat_agent = MagicMock()
    session.current_agent = combat_agent
    observe_player_speech((), "player-one", "I swing")

    combat_agent.observe_player_speech.assert_called_once_with((), "player-one", "I swing")
    agent.observe_player_speech.assert_called_once()
    assert events.index("room:participant_connected") < events.index("session:start")
    assert session.start_kwargs is not None
    options = session.start_kwargs["room_options"]
    assert isinstance(options, room_io.RoomOptions)
    assert options.participant_identity == "player-one"
    assert options.close_on_disconnect is False
    assert options.get_audio_input_options() is None
    assert options.get_text_input_options() is None
    session.listeners["close"](object())
    close_task = sd.multiplayer_close_task
    session.listeners["close"](object())
    # LiveKit can emit "close" more than once; a second cleanup would aclose an already
    # closed transcriber and re-raise its drained failures at the job's session-end join.
    assert sd.multiplayer_close_task is close_task
    assert close_task is not None
    await close_task
    assert owner.input._task is None


async def test_cleanup_failures_from_every_owned_resource_are_raised_together() -> None:
    class Failing:
        def __init__(self, error) -> None:
            self.error = error

        async def aclose(self) -> None:
            raise self.error

    input_error = OSError("input cleanup failed")
    transcriber_error = OSError("transcriber cleanup failed")
    lifecycle_error = OSError("lifecycle cleanup failed")
    owner = GameplayInputOwner(
        cast(Any, Failing(lifecycle_error)),
        cast(Any, Failing(transcriber_error)),
        cast(Any, Failing(input_error)),
    )

    with pytest.raises(BaseExceptionGroup) as caught:
        await owner.aclose()

    assert set(caught.value.exceptions) == {input_error, transcriber_error, lifecycle_error}


async def test_cleanup_starts_all_owned_resources_before_waiting() -> None:
    started = {name: asyncio.Event() for name in ("input", "transcriber", "lifecycle")}
    release = asyncio.Event()

    class Gated:
        def __init__(self, name) -> None:
            self.name = name

        async def aclose(self) -> None:
            started[self.name].set()
            await release.wait()

    owner = GameplayInputOwner(
        cast(Any, Gated("lifecycle")),
        cast(Any, Gated("transcriber")),
        cast(Any, Gated("input")),
    )
    close_task = asyncio.create_task(owner.aclose())

    await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 1)
    assert not close_task.done()
    release.set()
    await close_task
