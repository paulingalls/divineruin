"""Live connection generations and authorization for multiplayer party members."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from participant_lifecycle import _setup_party_join
from session_data import SessionData


def _participant(identity):
    return SimpleNamespace(identity=identity)


def _recording_room(*identities):
    room = MagicMock()
    room.remote_participants = {identity: _participant(identity) for identity in identities}
    handlers: dict = {}

    def _on(event, callback=None):
        if callback is not None:
            handlers[event] = callback
            return callback

        def _register(fn):
            handlers[event] = fn
            return fn

        return _register

    room.on.side_effect = _on
    return room, handlers


def _make_mods(row):
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=row)
    res_mod = MagicMock()
    res_mod.read_player_resonance = AsyncMock(return_value={"current": 0, "flickering_bonus": 0, "state": "stable"})
    conc_mod = MagicMock()
    conc_mod.read_player_concentration = AsyncMock(return_value={"spell_id": None})
    return queries, res_mod, conc_mod


async def _drain():
    pending = asyncio.all_tasks() - {asyncio.current_task()}
    if pending:
        await asyncio.gather(*pending)


@pytest.mark.asyncio
async def test_duplicate_join_shares_lookup_and_live_generation():
    lookup_started = asyncio.Event()
    release_lookup = asyncio.Event()
    mods = _make_mods(None)

    async def delayed_lookup(pid):
        lookup_started.set()
        await release_lookup.wait()
        return {"player_id": pid}

    mods[0].get_player.side_effect = delayed_lookup
    room, handlers = _recording_room()
    sd = SessionData(player_id="player_1", location_id="loc")
    lifecycle = _setup_party_join(
        room,
        sd,
        queries=mods[0],
        resonance_mod=mods[1],
        concentration_mod=mods[2],
    )

    handlers["participant_connected"](_participant("player_2"))
    handlers["participant_connected"](_participant("player_2"))
    await lookup_started.wait()
    generation = lifecycle.current_generation("player_2")
    assert generation is not None
    assert mods[0].get_player.await_count == 1
    release_lookup.set()
    await _drain()
    handlers["participant_connected"](_participant("player_2"))
    await _drain()

    assert sd.party.member_ids == ["player_1", "player_2"]
    assert lifecycle.current_generation("player_2") == generation
    assert mods[0].get_player.await_count == 1


@pytest.mark.asyncio
async def test_disconnect_keeps_member_but_reconnect_advances_generation():
    mods = _make_mods({"player_id": "player_2"})
    room, handlers = _recording_room("player_2")
    sd = SessionData(player_id="player_1", location_id="loc")
    lifecycle = _setup_party_join(
        room,
        sd,
        queries=mods[0],
        resonance_mod=mods[1],
        concentration_mod=mods[2],
    )
    await _drain()
    first = lifecycle.current_generation("player_2")
    assert first is not None

    handlers["participant_disconnected"](_participant("player_2"))
    assert sd.party.contains("player_2")
    assert lifecycle.current_generation("player_2") is None

    handlers["participant_connected"](_participant("player_2"))
    second = lifecycle.current_generation("player_2")
    handlers["participant_connected"](_participant("player_2"))

    assert second is not None and second > first
    assert lifecycle.current_generation("player_2") == second
    assert sd.party.member_ids == ["player_1", "player_2"]


@pytest.mark.asyncio
async def test_authorization_requires_membership_live_connection_and_exact_generation():
    mods = _make_mods({"player_id": "player_2"})
    room, handlers = _recording_room("player_2")
    sd = SessionData(player_id="player_1", location_id="loc")
    lifecycle = _setup_party_join(
        room,
        sd,
        queries=mods[0],
        resonance_mod=mods[1],
        concentration_mod=mods[2],
    )
    await _drain()
    member = sd.party.member("player_2")
    generation = lifecycle.current_generation("player_2")
    assert member is not None and generation is not None
    assert lifecycle.is_authorized("player_2", generation)

    sd.party.members.remove(member)
    assert not lifecycle.is_authorized("player_2", generation)
    sd.party.members.append(member)
    handlers["participant_disconnected"](_participant("player_2"))
    assert not lifecycle.is_authorized("player_2", generation)
    handlers["participant_connected"](_participant("player_2"))
    current = lifecycle.current_generation("player_2")
    assert current is not None and current > generation
    assert not lifecycle.is_authorized("player_2", generation)
    assert lifecycle.is_authorized("player_2", current)


@pytest.mark.asyncio
async def test_authorize_refuses_an_identity_that_dropped_while_its_hydration_was_in_flight():
    release_lookup = asyncio.Event()
    lookup_started = asyncio.Event()
    mods = _make_mods(None)

    async def delayed_lookup(pid):
        lookup_started.set()
        await release_lookup.wait()
        return {"player_id": pid}

    mods[0].get_player.side_effect = delayed_lookup
    room, handlers = _recording_room("player_2")
    sd = SessionData(player_id="player_1", location_id="loc")
    lifecycle = _setup_party_join(room, sd, queries=mods[0], resonance_mod=mods[1], concentration_mod=mods[2])
    await lookup_started.wait()

    authorizing = asyncio.create_task(lifecycle.authorize("player_2"))
    await asyncio.sleep(0)
    handlers["participant_disconnected"](_participant("player_2"))
    release_lookup.set()

    assert await authorizing is None
    assert sd.party.contains("player_2")  # membership persists; only the live connection went


@pytest.mark.asyncio
async def test_authorize_raises_for_a_generation_whose_hydration_failed():
    mods = _make_mods(None)
    mods[0].get_player.side_effect = OSError("players row unreachable")
    room, handlers = _recording_room("player_2")
    sd = SessionData(player_id="player_1", location_id="loc")
    lifecycle = _setup_party_join(room, sd, queries=mods[0], resonance_mod=mods[1], concentration_mod=mods[2])
    await asyncio.gather(*(asyncio.all_tasks() - {asyncio.current_task()}), return_exceptions=True)

    assert not sd.party.contains("player_2")
    with pytest.raises(RuntimeError, match="party hydration failed"):
        await lifecycle.authorize("player_2")

    # A fresh connection clears the failed generation, so a transient DB outage is not permanent.
    mods[0].get_player.side_effect = None
    mods[0].get_player.return_value = {"player_id": "player_2"}
    handlers["participant_disconnected"](_participant("player_2"))
    handlers["participant_connected"](_participant("player_2"))

    assert await lifecycle.authorize("player_2") == lifecycle.current_generation("player_2")
    assert sd.party.member_ids == ["player_1", "player_2"]


@pytest.mark.asyncio
async def test_reconnect_during_an_in_flight_hydration_still_appends_exactly_once():
    release_lookup = asyncio.Event()
    lookups: list[str] = []
    mods = _make_mods(None)

    async def delayed_lookup(pid):
        lookups.append(pid)
        await release_lookup.wait()
        return {"player_id": pid}

    mods[0].get_player.side_effect = delayed_lookup
    room, handlers = _recording_room("player_2")
    sd = SessionData(player_id="player_1", location_id="loc")
    lifecycle = _setup_party_join(room, sd, queries=mods[0], resonance_mod=mods[1], concentration_mod=mods[2])
    await asyncio.sleep(0)

    handlers["participant_disconnected"](_participant("player_2"))
    handlers["participant_connected"](_participant("player_2"))
    release_lookup.set()
    await _drain()

    generation = lifecycle.current_generation("player_2")
    assert lookups == ["player_2", "player_2"]  # both connections really ran their own hydration
    assert sd.party.member_ids == ["player_1", "player_2"]
    assert generation is not None and lifecycle.is_authorized("player_2", generation)


async def test_close_cancels_and_joins_in_flight_hydration():
    lookup_started = asyncio.Event()
    hold_lookup = asyncio.Event()
    mods = _make_mods(None)

    async def delayed_lookup(_identity):
        lookup_started.set()
        await hold_lookup.wait()

    mods[0].get_player.side_effect = delayed_lookup
    room, _handlers = _recording_room("player_2")
    lifecycle = _setup_party_join(
        room,
        SessionData(player_id="player_1", location_id="loc"),
        queries=mods[0],
        resonance_mod=mods[1],
        concentration_mod=mods[2],
    )
    await lookup_started.wait()
    task = lifecycle._pending_joins["player_2"]

    await asyncio.wait_for(lifecycle.aclose(), 1)

    assert task.cancelled()
    assert lifecycle.current_generation("player_2") is None
    room.off.assert_any_call("participant_connected", lifecycle._on_connected)
    room.off.assert_any_call("participant_disconnected", lifecycle._on_disconnected)


async def test_cancelling_an_in_flight_join_reports_no_unhandled_error():
    """_join_finished reads task.exception(), which RAISES on a cancelled task; aclose is what
    cancels joins, so an unguarded read turns every shutdown into an unhandled-callback error."""
    hold_lookup = asyncio.Event()
    lookup_started = asyncio.Event()
    mods = _make_mods(None)

    async def delayed_lookup(_identity):
        lookup_started.set()
        await hold_lookup.wait()

    mods[0].get_player.side_effect = delayed_lookup
    room, _handlers = _recording_room("player_2")
    loop = asyncio.get_running_loop()
    reported: list[dict] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: reported.append(context))
    try:
        lifecycle = _setup_party_join(
            room,
            SessionData(player_id="player_1", location_id="loc"),
            queries=mods[0],
            resonance_mod=mods[1],
            concentration_mod=mods[2],
        )
        await lookup_started.wait()
        await lifecycle.aclose()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous)

    assert [context["message"] for context in reported] == []
