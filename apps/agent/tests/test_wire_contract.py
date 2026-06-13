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

import db_queries
import event_types
import hollow_echo_events
import resonance_events
import veil_ward_tools
from hollow_echo import HollowEchoResult
from spells import Spell

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


@pytest.mark.asyncio
async def test_resonance_changed_serializes_to_fixture() -> None:
    expected = FIXTURE["events"]["resonance_changed"]
    session = MagicMock()
    session.resonance.state = expected["state"]
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
    expected = FIXTURE["events"]["veil_ward_changed"]
    session = MagicMock()
    with patch("veil_ward_tools.publish_game_event", new_callable=AsyncMock) as pub:
        await veil_ward_tools._publish_veil_ward_changed(session, expected["active"])
    assert _captured_wire(pub) == expected


def test_spell_row_builder_matches_fixture() -> None:
    # The session-init spell row (db_queries._enrich_spell_row) is the drift point for the
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
    with patch("db_queries.spells.get_spell", return_value=spell):
        row = db_queries._enrich_spell_row(expected["spell_id"], is_prepared=expected["is_prepared"])
    assert row == expected
