from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from acceptance._live_voice import has_live_voice_key
from acceptance._livekit_client import (
    aclose_audio,
    aclose_room,
    connect_room,
    create_microphone_track,
    mint_access_token,
    wait_for_peer,
)
from livekit import rtc
from livekit.agents import Agent, AgentSession, utils
from livekit.agents.testing import fake_job_context
from livekit.plugins import deepgram

from multiplayer_transcription import MultiParticipantTranscriber
from participant_lifecycle import RECONNECT_GRACE_S, _setup_party_join, _setup_reconnection
from session_data import SessionData
from session_startup import gameplay_room_options

# The skipif is the not-opted-in path (CI without the secret, a worktree carrying
# .env.example's placeholder); REQUIRE_REAL_LLM=1 suppresses it so the conftest fixture
# fails this lane LOUD rather than letting it absent itself from the boundary.
pytestmark = [
    pytest.mark.live_voice,
    pytest.mark.skipif(
        not has_live_voice_key(os.environ) and not os.environ.get("REQUIRE_REAL_LLM"),
        reason="live-voice acceptance drives the real Deepgram STT API and needs DEEPGRAM_API_KEY",
    ),
]


class Queries:
    async def get_player(self, player_id: str) -> dict[str, str]:
        return {"player_id": player_id}


class Resonance:
    async def read_player_resonance(self, _player_id: str) -> dict[str, int]:
        return {"current": 0, "flickering_bonus": 0}


class Concentration:
    async def read_player_concentration(self, _player_id: str) -> dict[str, None]:
        return {"spell_id": None}


class ManualSleep:
    def __init__(self) -> None:
        self.now = 0
        self.waiters: list[tuple[int, asyncio.Future[None]]] = []

    async def __call__(self, delay: float) -> None:
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((self.now + int(delay), future))
        await future

    async def advance(self, seconds: int) -> None:
        self.now += seconds
        for deadline, future in tuple(self.waiters):
            if deadline <= self.now and not future.done():
                future.set_result(None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)


async def wait_for(predicate, description: str) -> None:
    try:
        async with asyncio.timeout(10):
            while not predicate():
                await asyncio.sleep(0.02)
    except TimeoutError as exc:
        raise TimeoutError(f"timed out waiting for {description}") from exc


async def test_real_room_reconnect_grace_preserves_remaining_players(
    livekit_server: dict[str, str],
) -> None:
    suffix = uuid.uuid4().hex[:10]
    room_name = f"multiplayer-reconnection-{suffix}"
    primary_id = f"primary-{suffix}"
    secondary_id = f"secondary-{suffix}"

    def token(identity: str) -> str:
        return mint_access_token(
            api_key=livekit_server["api_key"],
            api_secret=livekit_server["api_secret"],
            room_name=room_name,
            identity=identity,
        )

    http_context = utils.http_context.open()
    await http_context.__aenter__()
    secondary: rtc.Room | None = None
    primary: rtc.Room | None = None
    listener: rtc.Room | None = None
    audio: dict[str, tuple[Any, Any, Any]] = {}
    manager: MultiParticipantTranscriber | None = None
    dm_session: AgentSession | None = None
    reconnect_owner = None
    try:
        secondary = await connect_room(livekit_server["ws_url"], token(secondary_id))
        audio[secondary_id] = await create_microphone_track(
            secondary, sample_rate=16000, channels=1, name="secondary-microphone"
        )
        listener = await connect_room(livekit_server["ws_url"], token(f"dm-{suffix}"))
        await wait_for_peer(listener, identity=secondary_id)

        userdata = SessionData(player_id=primary_id, location_id="acceptance")
        lifecycle = _setup_party_join(
            listener,
            userdata,
            queries=Queries(),
            resonance_mod=Resonance(),
            concentration_mod=Concentration(),
        )
        dm_session = AgentSession(max_tool_steps=5, userdata=userdata)
        dm_session.output.set_audio_enabled(False)
        closed = asyncio.Event()
        dm_session.on("close", lambda _event: closed.set())
        with fake_job_context(room=listener):
            await dm_session.start(
                room=listener,
                agent=Agent(instructions="Wait for multiplayer speech."),
                room_options=gameplay_room_options(userdata),
            )

        primary = await connect_room(livekit_server["ws_url"], token(primary_id))
        audio[primary_id] = await create_microphone_track(
            primary, sample_rate=16000, channels=1, name="primary-microphone"
        )
        await wait_for_peer(listener, identity=primary_id)
        await wait_for(lambda: dm_session.room_io.linked_participant is not None, "primary RoomIO link")
        assert dm_session.room_io.linked_participant is not None
        assert dm_session.room_io.linked_participant.identity == primary_id

        manager = MultiParticipantTranscriber(
            listener,
            stt=deepgram.STT(model="nova-3", language="en-US", endpointing_ms=300),
            authorizer=lifecycle.authorize,
        )
        manager.start()
        await wait_for(
            lambda: manager.active_identities == {primary_id, secondary_id},
            "both transcription sessions",
        )
        await wait_for(lambda: userdata.party.contains(secondary_id), "secondary party hydration")

        clock = ManualSleep()
        grace_close_started = asyncio.Event()

        class SessionBridge:
            def on(self, event, callback):
                assert dm_session is not None
                dm_session.on(event, callback)

            def off(self, event, callback):
                assert dm_session is not None
                dm_session.off(event, callback)

            async def aclose(self) -> None:
                assert dm_session is not None
                grace_close_started.set()
                await dm_session.aclose()

            def generate_reply(self, **_kwargs):
                return object()

        reconnect_owner = _setup_reconnection(
            listener,
            cast(Any, SessionBridge()),
            userdata,
            cast(Any, SimpleNamespace(_fire_and_forget=lambda _handle: None)),
            sleep=clock,
        )

        await aclose_audio(audio.pop(secondary_id)[0])
        await aclose_room(secondary)
        secondary = None
        await wait_for(lambda: manager.active_identities == {primary_id}, "secondary transcription close")
        assert not closed.is_set()
        assert userdata.party.member_ids.count(secondary_id) == 1

        secondary = await connect_room(livekit_server["ws_url"], token(secondary_id))
        audio[secondary_id] = await create_microphone_track(
            secondary, sample_rate=16000, channels=1, name="secondary-reconnected-microphone"
        )
        await wait_for_peer(listener, identity=secondary_id)
        await wait_for(
            lambda: manager.active_identities == {primary_id, secondary_id},
            "secondary transcription restore",
        )
        assert manager.start_counts == {primary_id: 1, secondary_id: 2}
        assert userdata.party.member_ids.count(secondary_id) == 1

        await aclose_audio(audio.pop(primary_id)[0])
        await aclose_room(primary)
        primary = None
        await wait_for(lambda: userdata.player_disconnected, "primary disconnect handler")
        await wait_for(
            lambda: sum(not future.done() for _, future in clock.waiters) == 1,
            "first reconnect deadline armed",
        )
        await clock.advance(RECONNECT_GRACE_S - 1)
        assert not closed.is_set()

        primary = await connect_room(livekit_server["ws_url"], token(primary_id))
        audio[primary_id] = await create_microphone_track(
            primary, sample_rate=16000, channels=1, name="primary-reconnected-microphone"
        )
        await wait_for_peer(listener, identity=primary_id)
        await wait_for(
            lambda: manager.active_identities == {primary_id, secondary_id},
            "primary transcription restore",
        )
        await wait_for(lambda: not userdata.player_disconnected, "primary reconnect cancellation")
        await clock.advance(1)
        await wait_for(
            lambda: grace_close_started.is_set() or all(task.done() for task in reconnect_owner._tasks),
            "reconnect cancellation to settle",
        )
        assert not grace_close_started.is_set()
        assert not closed.is_set()
        assert manager.start_counts == {primary_id: 2, secondary_id: 2}

        await aclose_audio(audio.pop(primary_id)[0])
        await aclose_room(primary)
        primary = None
        await wait_for(lambda: userdata.player_disconnected, "second primary disconnect handler")
        await wait_for(
            lambda: sum(not future.done() for _, future in clock.waiters) == 1,
            "second reconnect deadline armed",
        )
        await clock.advance(RECONNECT_GRACE_S)
        await wait_for(grace_close_started.is_set, "session close after reconnect grace")
        await wait_for(lambda: reconnect_owner.close_task is not None, "reconnect cleanup on DM close")
        assert reconnect_owner.close_task is not None
        await asyncio.wait_for(reconnect_owner.close_task, 10)
        assert reconnect_owner._closed
    finally:
        if reconnect_owner is not None:
            await reconnect_owner.aclose()
        if manager is not None:
            await manager.aclose()
        if dm_session is not None:
            await dm_session.aclose()
        for source, _track, _publication in tuple(audio.values()):
            await aclose_audio(source)
        for room in (secondary, primary, listener):
            if room is not None:
                await aclose_room(room)
        await http_context.__aexit__(None, None, None)
