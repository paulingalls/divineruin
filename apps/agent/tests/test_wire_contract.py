"""Cross-language wire-contract test (story-007, closes 82fc).

``packages/shared/fixtures/event_wire.json`` is the single source of truth for the
wire shape both lanes assert against. Here is the Python half: each M3.2 event
publisher, driven from the fixture's own values, must serialize exactly the fixture's
``{type, ...payload}`` shape, and the session-init spell-row builder must emit exactly
the fixture ``spell_row`` keys. A renamed payload key on the Python side fails this
test; the TS half (``apps/mobile/src/__tests__/wire-contract.test.ts``) asserts the
mirror, so drift on either side goes red instead of silently rendering a blank value.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import _WARRIOR_MILESTONES, GUILD_PLAYER, _milestones_mod_for

import db_session_queries
import event_types
import hollow_echo
import hollow_echo_events
import resonance_events
import veil_ward_events
from hollow_echo import HollowEchoResult
from progression_tools import _award_divine_favor_core, _award_xp_core
from spells import Spell
from veil_ward import WardScope

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "packages" / "shared" / "fixtures" / "event_wire.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())


def _captured_wire(pub: AsyncMock) -> dict:
    """Reconstruct the top-level wire object from a captured publish_game_event call.

    publish_game_event(room, event_type, payload, event_bus) flat-merges
    {"type": event_type, **payload} onto the data channel (game_events.py).
    """
    assert pub.await_args is not None, "publish_game_event was never awaited"
    _room, event_type, payload, *_ = pub.await_args.args
    return {"type": event_type, **payload}


def test_fixture_event_types_match_python_constants() -> None:
    # Pin the fixture's type strings to event_types.py (the <-> event-types.ts parity anchor).
    assert FIXTURE["events"]["resonance_changed"]["type"] == event_types.RESONANCE_CHANGED
    assert FIXTURE["events"]["hollow_echo_result"]["type"] == event_types.HOLLOW_ECHO_RESULT
    assert FIXTURE["events"]["veil_ward_changed"]["type"] == event_types.VEIL_WARD_CHANGED
    assert FIXTURE["events"]["xp_awarded"]["type"] == event_types.XP_AWARDED
    assert FIXTURE["events"]["specialization_choice"]["type"] == event_types.SPECIALIZATION_CHOICE
    assert FIXTURE["events"]["divine_favor_changed"]["type"] == event_types.DIVINE_FAVOR_CHANGED


def test_fixture_hollow_echo_bands_match_agent_resolver() -> None:
    # The full 7-band vocabulary is the SSOT both lanes assert against: an agent band the
    # mobile union lacks would be silently dropped by the fail-safe. Pin the fixture list to
    # the agent's resolver bands (hollow_echo._BANDS + _BREACH); the TS lane pins it to the
    # mobile HollowEchoBand vocabulary, so a band added on one side without the other goes red.
    agent_bands = {band for _floor, band, _name, _effect in hollow_echo._BANDS}
    agent_bands.add(hollow_echo._BREACH[0])
    assert set(FIXTURE["hollow_echo_bands"]) == agent_bands


@pytest.mark.asyncio
async def test_resonance_changed_serializes_to_fixture() -> None:
    expected = FIXTURE["events"]["resonance_changed"]
    session = MagicMock()
    session.resonance.state = expected["state"]
    session.player_id = expected["caster_id"]  # caster_id defaults to the session primary
    with patch("resonance_events.publish_game_event", new_callable=AsyncMock) as pub:
        await resonance_events.publish_resonance_changed(session)
    assert _captured_wire(pub) == expected


@pytest.mark.asyncio
async def test_hollow_echo_result_serializes_to_fixture() -> None:
    expected = FIXTURE["events"]["hollow_echo_result"]
    result = HollowEchoResult(band=expected["band"], name="Whisper", effect="x", effective_roll=15)
    session = MagicMock()
    with patch("hollow_echo_events.publish_game_event", new_callable=AsyncMock) as pub:
        await hollow_echo_events.publish_hollow_echo(session, result)
    assert _captured_wire(pub) == expected


@pytest.mark.asyncio
async def test_veil_ward_changed_serializes_to_fixture() -> None:
    # story-008: {active, scope_kind, scope_id, source} — no caster_id. The ward is scope-owned, so
    # every in-scope client lights up and there is nothing to filter on (scope_model.md §6).
    expected = FIXTURE["events"]["veil_ward_changed"]
    ward = {"source": expected["source"], "expires_at": None, "dismissible": True}
    scope = WardScope.location(expected["scope_id"])
    session = MagicMock()
    with patch("veil_ward_events.publish_game_event", new_callable=AsyncMock) as pub:
        await veil_ward_events.publish_veil_ward_changed(session, ward, scope)
    assert _captured_wire(pub) == expected


def test_veil_ward_fixture_carries_no_caster_id() -> None:
    """The asymmetry, pinned in the fixture itself: RESONANCE_CHANGED filters per-caster; the ward
    does not. A reader who 'restores consistency' by adding caster_id back fails here."""
    assert "caster_id" not in FIXTURE["events"]["veil_ward_changed"]
    assert "caster_id" in FIXTURE["events"]["resonance_changed"]


async def _core_pending_events() -> dict[str, dict]:
    """Drive _award_xp_core over the fixture's own award (L3 @600xp + 450 -> L5) and return
    the buffered {type: payload} it appended. The core buffers rather than publishes (it runs
    in the caller's transaction), so the wire object is {type, **payload} the same way
    publish_game_event flat-merges it post-commit."""
    expected = FIXTURE["events"]["xp_awarded"]
    player = {**GUILD_PLAYER, "class": "warrior", "level": 3, "xp": expected["new_xp"] - expected["amount"]}
    mutations = MagicMock()
    mutations.update_player_xp = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    pending: list[tuple[str, dict]] = []
    await _award_xp_core(
        player_id=expected["player_id"],
        player=player,
        amount=expected["amount"],
        reason=expected["reason"],
        conn=MagicMock(),
        pending_events=pending,
        mutations=mutations,
        milestones_mod=_milestones_mod_for(_WARRIOR_MILESTONES, "warrior"),
    )
    return {event_type: {"type": event_type, **payload} for event_type, payload in pending}


@pytest.mark.asyncio
async def test_xp_awarded_serializes_to_fixture() -> None:
    # story-001: the mobile handler read xp_gained/level_up while every Python emitter published
    # amount/leveled_up, so a real award toasted "+0 XP". Both lanes assert this fixture now.
    # player_id is the RECIPIENT — combat-end grants party-wide, so each client filters on it.
    wire = await _core_pending_events()
    assert wire[event_types.XP_AWARDED] == FIXTURE["events"]["xp_awarded"]


@pytest.mark.asyncio
async def test_specialization_choice_serializes_to_fixture() -> None:
    # The same L5 crossing surfaces the fork cue, stamped with the same recipient so a
    # non-primary's fork does not pop the choice UI on every client.
    wire = await _core_pending_events()
    assert wire[event_types.SPECIALIZATION_CHOICE] == FIXTURE["events"]["specialization_choice"]


@pytest.mark.asyncio
async def test_level_up_carries_the_recipient() -> None:
    # LEVEL_UP rides the same award; without the stamp a teammate's level-up would be
    # indistinguishable from the local player's.
    wire = await _core_pending_events()
    assert wire[event_types.LEVEL_UP]["player_id"] == FIXTURE["events"]["xp_awarded"]["player_id"]


def test_spell_row_builder_matches_fixture() -> None:
    # The session-init spell row (db_session_queries._enrich_spell_row) is the drift point for the
    # blank-tier bug (82fc): the TS parser coerces a missing spell_tier to "". Pin its keys.
    expected = FIXTURE["spell_row"]
    spell = Spell(
        id=expected["spell_id"],
        name=expected["name"],
        source="arcane",
        spell_tier=expected["spell_tier"],
        focus_cost=expected["focus_cost"],
        mechanics="",
        narration_cue="",
    )
    with patch("db_session_queries.spells.get_spell", return_value=spell):
        row = db_session_queries._enrich_spell_row(expected["spell_id"], is_prepared=expected["is_prepared"])
    assert row == expected


async def _favor_core_pending_events() -> dict[str, dict]:
    """Drive _award_divine_favor_core over the fixture's own grant and return the buffered
    {type: payload}. Like the XP core it buffers rather than publishes, so the wire object is
    {type, **payload} exactly as publish_game_event flat-merges it post-commit."""
    expected = FIXTURE["events"]["divine_favor_changed"]
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(
        return_value={
            "patron": expected["patron_id"],
            "level": expected["previous_level"],
            "max": expected["max"],
            "last_whisper_level": expected["last_whisper_level"],
        }
    )
    mutations = MagicMock()
    mutations.update_divine_favor = AsyncMock()
    pending: list[tuple[str, dict]] = []
    await _award_divine_favor_core(
        player_id=expected["player_id"],
        amount=expected["amount"],
        reason=expected["reason"],
        conn=MagicMock(),
        pending_events=pending,
        mutations=mutations,
        activities=activities,
    )
    return {event_type: {"type": event_type, **payload} for event_type, payload in pending}


@pytest.mark.asyncio
async def test_divine_favor_changed_serializes_to_fixture() -> None:
    # story-002: the mobile handler reads `max` for the favor bar's denominator (falling back to
    # 100) but no Python publisher ever sent it, so the denominator was fabricated on every real
    # event — the same both-sides-mocked shape as story-001's xp_awarded. player_id is the
    # RECIPIENT: quest favor is party-wide, so each client filters on it.
    wire = await _favor_core_pending_events()
    assert wire[event_types.DIVINE_FAVOR_CHANGED] == FIXTURE["events"]["divine_favor_changed"]
