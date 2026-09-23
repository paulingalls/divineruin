"""Guest departure remains scoped to the authenticated member and spoken turn."""

import asyncio
import json
import time
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit import api, rtc
from livekit.agents.voice.speech_handle import SpeechHandle

import event_types as E
from participant_lifecycle import PartyLifecycle
from session_data import SessionData
from session_end import run_guest_departure
from session_startup import GameplayInputOwner
from session_summary import generate_session_summary
from session_tools import end_session


def _party():
    sd = SessionData(player_id="host", location_id="hall")
    guest = SessionData(player_id="guest", location_id="hall").party.primary
    sd.party.members.append(guest)
    return sd


@pytest.mark.asyncio
async def test_guest_intent_does_not_end_party_inside_tool():
    sd = _party()
    ctx = MagicMock(userdata=sd)
    ctx.speech_handle = SpeechHandle.create()
    with sd._bind_authenticated_actor("guest", 1, lambda _id, _generation: None):
        result = json.loads(await end_session._func(ctx, "goodbye"))
    assert result["status"] == "ending"
    assert sd.departing_player_id == "guest"
    assert not sd.ending_requested
    assert sd.party.member_ids == ["host", "guest"]
    assert sd.departure_task is None


def _departure_setup():
    sd = _party()
    room = MagicMock(name="room")
    room.name = "test-room"
    room.isconnected.return_value = True
    room.local_participant.publish_data = AsyncMock()
    room.remote_participants = {}
    sd.room = room
    lifecycle = MagicMock()
    sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=lifecycle))
    sd.departing_player_id = "guest"
    return sd, lifecycle


@pytest.mark.asyncio
async def test_departure_waits_for_speech_and_keeps_host_playing():
    sd, lifecycle = _departure_setup()
    session = SimpleNamespace(generate_reply=MagicMock())
    ctx = MagicMock(userdata=sd, session=session)
    speech = SpeechHandle.create()
    ctx.speech_handle = speech
    sd.departing_player_id = None
    with (
        patch(
            "session_end.generate_session_summary", new_callable=AsyncMock, return_value={"summary": "Guest's journey"}
        ),
        patch("session_end.room_admin.remove_player", new_callable=AsyncMock) as remove,
        patch("session_end.db_mutations.save_session_summary", new_callable=AsyncMock) as save,
    ):
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            await end_session._func(ctx, "goodbye")
        assert not remove.await_count
        assert not save.await_count
        speech._mark_done()
        await asyncio.sleep(0)
        assert sd.departure_task is not None
        await sd.departure_task
    remove.assert_awaited_once_with("test-room", "guest")
    save.assert_awaited_once()
    assert save.await_args is not None
    assert save.await_args.args[0] == "guest"
    assert sd.party.member_ids == ["host"]
    lifecycle.mark_departed.assert_called_once_with("guest")
    assert not sd.ending_requested
    event = [e for e in sd.event_bus.drain() if e.event_type == E.SESSION_END]
    assert len(event) == 1 and event[0].payload["player_id"] == "guest"


@pytest.mark.asyncio
async def test_failed_removal_keeps_membership_and_does_not_save(caplog):
    sd, lifecycle = _departure_setup()
    session = SimpleNamespace(generate_reply=MagicMock())
    with (
        patch(
            "session_end.generate_session_summary", new_callable=AsyncMock, return_value={"summary": "Guest's journey"}
        ),
        patch("session_end.room_admin.remove_player", new_callable=AsyncMock, side_effect=RuntimeError("room down")),
        patch("session_end.db_mutations.save_session_summary", new_callable=AsyncMock) as save,
    ):
        with pytest.raises(RuntimeError, match="room down"):
            await run_guest_departure(sd, "guest", session)
    assert sd.party.member_ids == ["host", "guest"]
    assert not save.await_count
    lifecycle.mark_departed.assert_not_called()
    session.generate_reply.assert_called_once()
    assert session.generate_reply.call_args is not None
    assert "departure failed" in session.generate_reply.call_args.kwargs["instructions"]
    assert "Guest departure failed" in caplog.text
    events = [e.payload for e in sd.event_bus.drain() if e.event_type == E.SESSION_END]
    assert events == [{"summary": "Guest's journey", "player_id": "guest"}, {"player_id": "guest", "cancelled": True}]


@pytest.mark.asyncio
async def test_failed_summary_write_does_not_undo_successful_room_removal():
    sd, lifecycle = _departure_setup()
    session = SimpleNamespace(generate_reply=MagicMock())
    with (
        patch(
            "session_end.generate_session_summary", new_callable=AsyncMock, return_value={"summary": "Guest's journey"}
        ),
        patch("session_end.room_admin.remove_player", new_callable=AsyncMock),
        patch(
            "session_end.db_mutations.save_session_summary", new_callable=AsyncMock, side_effect=RuntimeError("db down")
        ),
    ):
        with pytest.raises(RuntimeError, match="db down"):
            await run_guest_departure(sd, "guest", session)
    assert sd.party.member_ids == ["host"]
    lifecycle.mark_departed.assert_called_once_with("guest")
    events = [e.payload for e in sd.event_bus.drain() if e.event_type == E.SESSION_END]
    assert events == [{"summary": "Guest's journey", "player_id": "guest"}]


@pytest.mark.asyncio
async def test_room_admin_builds_real_revoking_request():
    from room_admin import remove_player

    captured = []
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.room.remove_participant = AsyncMock(side_effect=lambda request: captured.append(request))
    with patch("room_admin.api.LiveKitAPI", return_value=client):
        await remove_player("test-room", "guest")
    assert len(captured) == 1
    request = captured[0]
    assert isinstance(request, api.RoomParticipantIdentity)
    assert request.room == "test-room" and request.identity == "guest"
    assert request.revoke_token_ts >= int(time.time())


@pytest.mark.asyncio
async def test_departure_summary_names_the_guest_as_focus():
    sd = _party()
    with patch(
        "session_summary._call_llm_summary", new_callable=AsyncMock, return_value={"summary": "Guest's journey"}
    ) as llm:
        await generate_session_summary(sd, None, player_id="guest")
    assert llm.await_args is not None
    assert llm.await_args.kwargs["focus_player_id"] == "guest"


@pytest.mark.asyncio
async def test_departed_member_reconnect_is_removed_again_without_party_authority():
    sd, _ = _departure_setup()
    assert sd.room is not None
    lifecycle = PartyLifecycle(
        sd.room, sd, queries=MagicMock(), resonance_mod=MagicMock(), concentration_mod=MagicMock()
    )
    lifecycle.mark_departed("guest")
    with patch("participant_lifecycle.room_admin.remove_player", new_callable=AsyncMock) as remove:
        lifecycle._on_connected(cast(rtc.RemoteParticipant, SimpleNamespace(identity="guest")))
        await asyncio.sleep(0)
        await asyncio.gather(*lifecycle._spawned_joins)
    remove.assert_awaited_once_with("test-room", "guest")
    assert await lifecycle.authorize("guest") is None
    assert sd.party.member_ids == ["host", "guest"]
    await lifecycle.aclose()


@pytest.mark.asyncio
async def test_host_with_guest_still_requests_whole_session_close():
    sd = _party()
    ctx = MagicMock(userdata=sd)
    ctx.speech_handle = SpeechHandle.create()
    with sd._bind_authenticated_actor("host", 1, lambda _id, _generation: None):
        await end_session._func(ctx, "goodbye")
    assert sd.ending_requested
    assert sd.departing_player_id is None


@pytest.mark.asyncio
async def test_unbound_multiplayer_actor_cannot_end_host_session():
    sd = _party()
    ctx = MagicMock(userdata=sd)
    ctx.speech_handle = SpeechHandle.create()
    with pytest.raises(RuntimeError, match="No actor"):
        await end_session._func(ctx, "goodbye")
    assert not sd.ending_requested
