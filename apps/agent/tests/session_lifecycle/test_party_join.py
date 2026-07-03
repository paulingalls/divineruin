"""Live participant-join trigger: a SECOND player connecting to the LiveKit room becomes a
PartyMember (M18 story-001). This is the trigger that makes a >1-member party reachable in
prod — every session is solo (1 member) until a real 2nd participant joins.

_setup_party_join registers its own participant_connected handler, distinct from
_setup_reconnection (whose handler only handles the PRIMARY reconnecting). The sync handler
early-returns for the primary identity and for an already-present member (idempotent), else
spawns an async _join_member task that: fetches the joiner's players row (log+skip if absent —
a stray participant must not fail-loud the room), appends a PartyMember IN PLACE (never
reassigns session.party), and hydrates all FIVE per-member sub-states onto it.

Mirrors test_reconnection.py's MagicMock-room shape, but uses a recording-room stub so the
registered handler can be invoked directly (a MagicMock decorator return would swallow it).
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from caster_state import ConcentrationState, ResonanceTrack, VeilWardState
from participant_lifecycle import _setup_party_join
from party_state import PartyMember
from session_data import SessionData


def _recording_room():
    """A MagicMock room (pyright accepts it for the rtc.Room param, as test_reconnection does)
    whose .on(event) records the decorated handler into ``handlers`` by event name — so a test can
    invoke the registered participant_connected callback directly. A bare MagicMock's decorator
    return would replace the handler with another mock, hiding the real function."""
    room = MagicMock()
    handlers: dict = {}

    def _on(event):
        def _register(fn):
            handlers[event] = fn
            return fn

        return _register

    room.on.side_effect = _on
    return room, handlers


def _participant(identity):
    return SimpleNamespace(identity=identity)


def _make_mods(
    row,
    *,
    resonance=None,
    veil_ward=None,
    concentration=None,
):
    """Build the injectable DI (queries + the three read-helper modules) as AsyncMocks."""
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=row)
    res_mod = MagicMock()
    res_mod.read_player_resonance = AsyncMock(
        return_value=resonance or {"current": 0, "flickering_bonus": 0, "state": "stable"}
    )
    ward_mod = MagicMock()
    ward_mod.read_player_veil_ward = AsyncMock(return_value=veil_ward or {"active": False, "source": None})
    conc_mod = MagicMock()
    conc_mod.read_player_concentration = AsyncMock(return_value=concentration or {"spell_id": None})
    return queries, res_mod, ward_mod, conc_mod


def _wire(room, handlers, sd, mods):
    queries, res_mod, ward_mod, conc_mod = mods
    _setup_party_join(
        room,
        sd,
        queries=queries,
        resonance_mod=res_mod,
        veil_ward_mod=ward_mod,
        concentration_mod=conc_mod,
    )
    return handlers["participant_connected"]


async def _drain():
    """Run the async _join_member task(s) the sync handler spawned via asyncio.create_task."""
    pending = asyncio.all_tasks() - {asyncio.current_task()}
    if pending:
        await asyncio.gather(*pending)


def test_registers_participant_connected_handler():
    room, handlers = _recording_room()
    sd = SessionData(player_id="player_1", location_id="loc")

    _setup_party_join(room, sd)

    assert "participant_connected" in handlers


@pytest.mark.asyncio
async def test_second_player_join_appends_and_hydrates_all_five_substates():
    row2 = {"player_id": "player_2", "divine_favor": {"patron": "syrath"}}
    mods = _make_mods(
        row2,
        resonance={"current": 6, "flickering_bonus": 1, "state": "flickering"},
        veil_ward={"active": True, "source": "arch_x"},
        concentration={"spell_id": "spell_y"},
    )
    room, handlers = _recording_room()
    sd = SessionData(player_id="player_1", location_id="loc")
    sd.corruption_level = 4  # the party sits in a corrupted room; the joiner is co-located
    handler = _wire(room, handlers, sd, mods)

    handler(_participant("player_2"))
    await _drain()

    assert sd.party.member_ids == ["player_1", "player_2"]
    m = sd.party.member("player_2")
    assert m is not None
    assert m.resonance.current == 6
    assert m.resonance.flickering_bonus == 1
    assert m.veil_ward.active is True
    assert m.veil_ward.source == "arch_x"
    assert m.concentration.spell_id == "spell_y"
    assert m.patron_id == "syrath"  # per-member: from the joiner's OWN row, not the primary
    assert m.corruption_level == 4  # co-located: mirrors the party's current location corruption
    mods[0].get_player.assert_awaited_once_with("player_2")


@pytest.mark.asyncio
async def test_primary_identity_is_ignored():
    mods = _make_mods({"player_id": "player_1"})
    room, handlers = _recording_room()
    sd = SessionData(player_id="player_1", location_id="loc")
    handler = _wire(room, handlers, sd, mods)

    handler(_participant("player_1"))  # the primary (re)connecting is _setup_reconnection's job
    await _drain()

    assert sd.party.member_ids == ["player_1"]
    mods[0].get_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_idempotent_when_member_already_present():
    mods = _make_mods({"player_id": "player_2"})
    room, handlers = _recording_room()
    sd = SessionData(player_id="player_1", location_id="loc")
    sd.party.members.append(
        PartyMember(
            player_id="player_2",
            resonance=ResonanceTrack(),
            veil_ward=VeilWardState(),
            concentration=ConcentrationState(),
        )
    )
    handler = _wire(room, handlers, sd, mods)

    handler(_participant("player_2"))
    await _drain()

    assert sd.party.member_ids == ["player_1", "player_2"]  # no double-add
    mods[0].get_player.assert_not_awaited()  # sync early-return, no DB round-trip


@pytest.mark.asyncio
async def test_missing_player_row_logs_and_skips(caplog):
    mods = _make_mods(None)  # get_player -> None (no such players row)
    room, handlers = _recording_room()
    sd = SessionData(player_id="player_1", location_id="loc")
    handler = _wire(room, handlers, sd, mods)

    with caplog.at_level(logging.WARNING, logger="divineruin.dm"):
        handler(_participant("stray_ghost"))
        await _drain()

    assert sd.party.member_ids == ["player_1"]  # not appended
    assert any("stray_ghost" in r.message for r in caplog.records)  # logged the skip


@pytest.mark.asyncio
async def test_join_mutates_party_in_place():
    mods = _make_mods({"player_id": "player_2"})
    room, handlers = _recording_room()
    sd = SessionData(player_id="player_1", location_id="loc")
    handler = _wire(room, handlers, sd, mods)
    party_id, members_id = id(sd.party), id(sd.party.members)

    handler(_participant("player_2"))
    await _drain()

    assert id(sd.party) == party_id
    assert id(sd.party.members) == members_id
    assert sd.party.member_ids == ["player_1", "player_2"]


@pytest.mark.asyncio
async def test_concurrent_joins_for_same_id_append_once():
    """Two participant_connected events for the SAME new id both pass the sync contains() check
    before either task appends; the after-await race guard in _join_member keeps it to one add."""
    mods = _make_mods({"player_id": "player_2"})
    room, handlers = _recording_room()
    sd = SessionData(player_id="player_1", location_id="loc")
    handler = _wire(room, handlers, sd, mods)

    handler(_participant("player_2"))
    handler(_participant("player_2"))
    await _drain()

    assert sd.party.member_ids == ["player_1", "player_2"]  # appended exactly once
