import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from session_lifecycle.test_reconnection import ClosingSession, ManualSleep, Room

from session_data import SessionData
from session_end import run_guest_departure
from session_startup import GameplayInputOwner


def _party():
    sd = SessionData(player_id="host", location_id="hall", patron_id="host-god")
    for player_id, patron_id in (("p2", "second-god"), ("p3", "third-god")):
        member = SessionData(player_id=player_id, location_id="hall", patron_id=patron_id).party.primary
        sd.party.members.append(member)
    return sd


def test_primary_handoff_uses_longest_present_member_and_updates_facade():
    sd = _party()
    sd.handoff_primary("host")
    assert sd.party.member_ids == ["p2", "p3"]
    assert sd.party.primary.player_id == sd.primary_player_id == sd.player_id == "p2"
    assert sd.patron_id == sd.party.primary.patron_id == "second-god"


def test_guest_binding_cannot_reassign_primary_by_either_path():
    sd = _party()
    with sd._bind_authenticated_actor("p2", 1, lambda *_: None):
        with pytest.raises(AttributeError, match="write-once"):
            sd.player_id = "p2"
        with pytest.raises(RuntimeError, match="bound"):
            sd.handoff_primary("host")
    assert sd.primary_player_id == "host"
    assert sd.party.member_ids == ["host", "p2", "p3"]


@pytest.mark.asyncio
async def test_host_departure_saves_host_then_promotes_p2_and_switches_room():
    sd = _party()
    sd.room = MagicMock()
    sd.room.name = "table"
    sd.room.isconnected.return_value = True
    sd.room.local_participant.publish_data = AsyncMock()
    sd.departing_player_id = "host"
    lifecycle = MagicMock()
    sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=lifecycle))
    sd.background = MagicMock()
    sd.background.primary_changed = AsyncMock()
    room_io = MagicMock()
    session = SimpleNamespace(room_io=room_io, generate_reply=MagicMock())
    with (
        patch("session_end.generate_session_summary", new_callable=AsyncMock, return_value={"summary": "host recap"}),
        patch("session_end.room_admin.remove_player", new_callable=AsyncMock) as remove,
        patch("session_end.db_mutations.save_session_summary", new_callable=AsyncMock) as save,
    ):
        await run_guest_departure(sd, "host", session)
    remove.assert_awaited_once_with("table", "host")
    save.assert_awaited_once_with("host", sd.session_id, {"summary": "host recap", "player_id": "host"})
    room_io.set_participant.assert_called_once_with("p2")
    assert sd.primary_player_id == "p2"
    assert sd.party.member_ids == ["p2", "p3"]
    sd.background.primary_changed.assert_awaited_once()


@pytest.mark.asyncio
async def test_guest_gets_grace_and_timeout_removes_only_guest():
    from participant_lifecycle import RECONNECT_GRACE_S, _setup_reconnection

    sd = _party()
    room = Room()
    sd.room = MagicMock()
    sd.room.name = "table"
    sd.room.isconnected.return_value = True
    sd.room.local_participant.publish_data = AsyncMock()
    sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=MagicMock()))
    clock = ManualSleep()
    session = SimpleNamespace(aclose=AsyncMock(), on=MagicMock(), off=MagicMock(), generate_reply=MagicMock())
    owner = _setup_reconnection(cast(Any, room), cast(Any, session), sd, MagicMock(), sleep=clock)
    room.emit("participant_disconnected", "p2")
    await asyncio.sleep(0)
    assert len(clock.waiters) == 1
    with (
        patch("session_end.generate_session_summary", new_callable=AsyncMock, return_value={"summary": "p2 recap"}),
        patch("session_end.room_admin.remove_player", new_callable=AsyncMock),
        patch("session_end.db_mutations.save_session_summary", new_callable=AsyncMock) as save,
    ):
        await clock.advance(RECONNECT_GRACE_S)
        async with asyncio.timeout(1):
            while not save.await_count:
                await asyncio.sleep(0)
    save.assert_awaited_once_with("p2", sd.session_id, {"summary": "p2 recap", "player_id": "p2"})
    session.aclose.assert_not_awaited()
    assert sd.party.member_ids == ["host", "p3"]
    await owner.aclose()


@pytest.mark.asyncio
async def test_guest_reconnect_cancels_only_their_grace():
    from participant_lifecycle import RECONNECT_GRACE_S, _setup_reconnection

    sd = _party()
    room = Room()
    clock = ManualSleep()
    session = SimpleNamespace(aclose=AsyncMock(), on=MagicMock(), off=MagicMock(), generate_reply=MagicMock())
    owner = _setup_reconnection(cast(Any, room), cast(Any, session), sd, MagicMock(), sleep=clock)
    room.emit("participant_disconnected", "p2")
    await asyncio.sleep(0)
    room.emit("participant_connected", "p2")
    await asyncio.sleep(0)
    await clock.advance(RECONNECT_GRACE_S)
    assert sd.party.member_ids == ["host", "p2", "p3"]
    session.aclose.assert_not_awaited()
    session.generate_reply.assert_called_once()
    await owner.aclose()


@pytest.mark.asyncio
async def test_host_grace_promotes_oldest_survivor():
    from participant_lifecycle import RECONNECT_GRACE_S, _setup_reconnection

    sd = _party()
    room = Room()
    sd.room = MagicMock()
    sd.room.name = "table"
    sd.room.isconnected.return_value = True
    sd.room.local_participant.publish_data = AsyncMock()
    sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=MagicMock()))
    clock = ManualSleep()
    session = SimpleNamespace(
        aclose=AsyncMock(),
        on=MagicMock(),
        off=MagicMock(),
        generate_reply=MagicMock(),
        room_io=MagicMock(),
    )
    owner = _setup_reconnection(cast(Any, room), cast(Any, session), sd, MagicMock(), sleep=clock)
    room.emit("participant_disconnected", "host")
    await asyncio.sleep(0)
    with (
        patch("session_end.generate_session_summary", new_callable=AsyncMock, return_value={"summary": "host recap"}),
        patch("session_end.room_admin.remove_player", new_callable=AsyncMock),
        patch("session_end.db_mutations.save_session_summary", new_callable=AsyncMock) as save,
    ):
        await clock.advance(RECONNECT_GRACE_S)
        async with asyncio.timeout(1):
            while not save.await_count:
                await asyncio.sleep(0)
    assert sd.primary_player_id == "p2"
    assert sd.party.member_ids == ["p2", "p3"]
    session.room_io.set_participant.assert_called_once_with("p2")
    session.aclose.assert_not_awaited()
    await owner.aclose()


@pytest.mark.asyncio
async def test_promoted_last_member_grace_close_is_not_cancelled_by_its_own_cleanup():
    from participant_lifecycle import RECONNECT_GRACE_S, _setup_reconnection

    sd = SessionData(player_id="host", location_id="hall")
    sd.party.members.append(SessionData(player_id="p2", location_id="hall").party.primary)
    room = Room()
    session = ClosingSession()
    clock = ManualSleep()
    owner = _setup_reconnection(cast(Any, room), cast(Any, session), sd, MagicMock(), sleep=clock)
    room.emit("participant_disconnected", "p2")
    await asyncio.sleep(0)
    deadline = owner._deadlines["p2"]
    sd.handoff_primary("host")
    await clock.advance(RECONNECT_GRACE_S)
    async with asyncio.timeout(1):
        while owner.close_task is None:
            await asyncio.sleep(0)
    await asyncio.wait_for(owner.close_task, 1)
    await asyncio.gather(deadline, return_exceptions=True)
    assert session.close_count == 1
    assert not deadline.cancelled()


@pytest.mark.asyncio
async def test_grace_expiry_waits_for_a_pending_goodbye():
    from participant_lifecycle import RECONNECT_GRACE_S, _setup_reconnection

    sd = _party()
    sd.departing_player_id = "p2"
    room = Room()
    clock = ManualSleep()
    session = SimpleNamespace(aclose=AsyncMock(), on=MagicMock(), off=MagicMock(), generate_reply=MagicMock())
    owner = _setup_reconnection(cast(Any, room), cast(Any, session), sd, MagicMock(), sleep=clock)
    room.emit("participant_disconnected", "p3")
    await asyncio.sleep(0)
    with patch("participant_lifecycle.run_guest_departure", new_callable=AsyncMock) as depart:
        await clock.advance(RECONNECT_GRACE_S)
        await asyncio.sleep(0)
        depart.assert_not_awaited()
        assert sd.departing_player_id == "p2"
        sd.departing_player_id = None
        await clock.advance(RECONNECT_GRACE_S)
        async with asyncio.timeout(1):
            while not depart.await_count:
                await asyncio.sleep(0)
    depart.assert_awaited_once_with(sd, "p3", session)
    await owner.aclose()
