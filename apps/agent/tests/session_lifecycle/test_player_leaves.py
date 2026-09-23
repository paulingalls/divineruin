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
from session_lifecycle.test_reconnection import ManualSleep, Room

import event_types as E
from participant_lifecycle import RECONNECT_GRACE_S, PartyLifecycle, _setup_reconnection
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
    assert "rest of the party keeps playing" in result["instruction"]
    assert sd.departing_player_id == "guest"
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


def _removal_client(error: Exception) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.room.remove_participant = AsyncMock(side_effect=error)
    return client


@pytest.mark.asyncio
async def test_room_admin_treats_already_departed_participant_as_removed():
    from room_admin import remove_player

    # The self-hosted server's answer for an identity no longer in the room, probed live.
    gone = api.ServerError("not_found", "twirp error unknown: participant does not exist", status=404)
    with patch("room_admin.api.LiveKitAPI", return_value=_removal_client(gone)):
        await remove_player("test-room", "guest")


@pytest.mark.asyncio
async def test_room_admin_raises_every_other_removal_failure():
    from room_admin import remove_player

    denied = api.ServerError("permission_denied", "no room admin grant", status=403)
    with patch("room_admin.api.LiveKitAPI", return_value=_removal_client(denied)):
        with pytest.raises(api.ServerError, match="permission_denied"):
            await remove_player("test-room", "guest")


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
async def test_departed_member_fresh_connection_hydrates_again_and_old_generation_is_stale():
    sd, _ = _departure_setup()
    sd.departing_player_id = None
    assert sd.room is not None
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={"divine_favor": {"patron": "new-god"}})
    resonance = MagicMock()
    resonance.read_player_resonance = AsyncMock(return_value={"current": 2, "flickering_bonus": 0})
    concentration = MagicMock()
    concentration.read_player_concentration = AsyncMock(return_value={"spell_id": None})
    lifecycle = PartyLifecycle(sd.room, sd, queries=queries, resonance_mod=resonance, concentration_mod=concentration)
    lifecycle._on_connected(cast(rtc.RemoteParticipant, SimpleNamespace(identity="guest")))
    old_generation = await lifecycle.authorize("guest")
    assert old_generation is not None
    sd.departing_player_id = "guest"
    assert await lifecycle.authorize("guest") is None
    lifecycle.mark_departed("guest")
    sd.departing_player_id = None
    sd.party.members[:] = [sd.party.primary]
    assert not lifecycle.is_authorized("guest", old_generation)
    assert await lifecycle.authorize("guest") is None
    lifecycle._on_connected(cast(rtc.RemoteParticipant, SimpleNamespace(identity="guest")))
    new_generation = await lifecycle.authorize("guest")
    assert new_generation is not None and new_generation > old_generation
    rejoined_member = sd.party.member("guest")
    assert rejoined_member is not None and rejoined_member.patron_id == "new-god"
    assert sd.party.member_ids == ["host", "guest"]
    await lifecycle.aclose()


@pytest.mark.asyncio
async def test_host_with_guest_requests_personal_departure():
    sd = _party()
    ctx = MagicMock(userdata=sd)
    ctx.speech_handle = SpeechHandle.create()
    with sd._bind_authenticated_actor("host", 1, lambda _id, _generation: None):
        await end_session._func(ctx, "goodbye")
    assert sd.departing_player_id == "host"


@pytest.mark.asyncio
async def test_interrupted_goodbye_tells_player_to_retry_and_clears_pending_departure():
    sd = _party()
    session = SimpleNamespace(generate_reply=MagicMock())
    speech = SpeechHandle.create()
    ctx = MagicMock(userdata=sd, session=session, speech_handle=speech)
    with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
        await end_session._func(ctx, "goodbye")
    speech.interrupt(source="user_turn")
    speech._mark_done()
    await asyncio.sleep(0)
    assert sd.departing_player_id is None
    session.generate_reply.assert_called_once()
    assert "goodbye again" in session.generate_reply.call_args.kwargs["instructions"]
    assert sd.departure_task is None


@pytest.mark.asyncio
async def test_disconnected_host_interrupted_during_farewell_still_departs():
    sd = _party()
    sd.party.members.append(SessionData(player_id="p3", location_id="hall").party.primary)
    room = Room()
    sd.room = MagicMock()
    sd.room.name = "test-room"
    sd.room.isconnected.return_value = True
    sd.room.local_participant.publish_data = AsyncMock()
    sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=MagicMock()))
    sd.background = MagicMock()
    sd.background.primary_changed = AsyncMock()
    session = MagicMock()
    session.aclose = AsyncMock()
    session.room_io = MagicMock()
    clock = ManualSleep()
    owner = _setup_reconnection(cast(rtc.Room, room), session, sd, MagicMock(), sleep=clock)
    speech = SpeechHandle.create()
    ctx = MagicMock(userdata=sd, session=session, speech_handle=speech)
    with (
        patch("session_end.generate_session_summary", new_callable=AsyncMock, return_value={"summary": "host recap"}),
        patch("session_end.room_admin.remove_player", new_callable=AsyncMock) as remove,
        patch("session_end.db_mutations.save_session_summary", new_callable=AsyncMock) as save,
    ):
        with sd._bind_authenticated_actor("host", 1, lambda *_: None):
            await end_session._func(ctx, "goodbye")
        room.emit("participant_disconnected", "host")
        speech.interrupt(source="user_turn")
        speech._mark_done()
        await asyncio.sleep(0)
        assert sd.departure_task is not None
        await sd.departure_task
        save.assert_awaited_once()
        assert save.await_args is not None
        assert save.await_args.args[0] == "host"
        remove.assert_awaited_once_with("test-room", "host")
        assert sd.party.member_ids == ["guest", "p3"]
        assert sd.primary_player_id == "guest"
        session.room_io.set_participant.assert_called_once_with("guest")
        session.generate_reply.assert_not_called()
        assert not sd.player_disconnected
        assert not owner.is_disconnected("host")
        room.emit("participant_disconnected", "guest")
        assert not sd.background.pause.called
        room.emit("participant_connected", "guest")
        await asyncio.sleep(0)
        sd.departing_player_id = "p3"
        await run_guest_departure(sd, "p3", session)
        room.emit("participant_disconnected", "guest")
        await asyncio.sleep(0)
        await clock.advance(RECONNECT_GRACE_S)
        session.aclose.assert_awaited_once()
    await owner.aclose()


@pytest.mark.asyncio
async def test_failed_departure_of_disconnected_member_retries_after_grace():
    sd, _ = _departure_setup()
    sd.departing_player_id = None
    room = Room()
    clock = ManualSleep()
    session = MagicMock()
    session.aclose = AsyncMock()
    owner = _setup_reconnection(cast(rtc.Room, room), session, sd, MagicMock(), sleep=clock)
    speech = SpeechHandle.create()
    ctx = MagicMock(userdata=sd, session=session, speech_handle=speech)
    remove = AsyncMock(side_effect=[RuntimeError("room down"), None])
    with (
        patch("session_end.generate_session_summary", new_callable=AsyncMock, return_value={"summary": "guest recap"}),
        patch("session_end.room_admin.remove_player", remove),
        patch("session_end.db_mutations.save_session_summary", new_callable=AsyncMock) as save,
    ):
        with sd._bind_authenticated_actor("guest", 1, lambda *_: None):
            await end_session._func(ctx, "goodbye")
        room.emit("participant_disconnected", "guest")
        speech._mark_done()
        await asyncio.sleep(0)
        assert sd.departure_task is not None
        with pytest.raises(RuntimeError, match="room down"):
            await sd.departure_task
        assert sd.party.member_ids == ["host", "guest"]
        await clock.advance(RECONNECT_GRACE_S)
        async with asyncio.timeout(1):
            while sd.party.contains("guest"):
                await asyncio.sleep(0)
    assert remove.await_count == 2
    save.assert_awaited_once()
    assert sd.party.member_ids == ["host"]
    room.emit("participant_disconnected", "host")
    await asyncio.sleep(0)
    await clock.advance(RECONNECT_GRACE_S)
    session.aclose.assert_awaited_once()
    await owner.aclose()


@pytest.mark.asyncio
async def test_unbound_multiplayer_actor_cannot_end_host_session():
    sd = _party()
    ctx = MagicMock(userdata=sd)
    ctx.speech_handle = SpeechHandle.create()
    with pytest.raises(RuntimeError, match="No actor"):
        await end_session._func(ctx, "goodbye")
    assert sd.departing_player_id is None
