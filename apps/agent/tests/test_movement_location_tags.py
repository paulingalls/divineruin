"""Arrival puts the destination's tags on LOCATION_CHANGED so the client Stage can derive music (M27).

The mobile music engine (inferExplorationState) already derives the exploration/tension/hollow/silence
track from the pushed location context on every move — but only if it receives the location's tags.
The live LOCATION_CHANGED handler had hardcoded an empty tag list, so the tag branch was dead. This
test pins the Python half: apply_arrival must serialize the destination's `tags` onto the payload
(alongside the existing ambient_sounds/region/time_of_day fields). No LLM audio tool involved.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import event_types as E
import movement_tools
from session_data import SessionData


def _db_mod():
    mod = MagicMock()
    conn = AsyncMock()
    mod.transaction.return_value.__aenter__ = AsyncMock(return_value=conn)
    mod.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    mod.extract_exit_connections = MagicMock(return_value={})
    return mod


async def _arrive(session, destination_location):
    """Drive apply_arrival with the ward resolver stubbed to unwarded; return the publish mock."""
    resolver = AsyncMock(return_value=(None, None))
    with (
        patch.object(movement_tools, "publish_game_event", AsyncMock()) as pub,
        patch.object(movement_tools.ward_resolution, "resolve_scope_ward_with_scope", resolver),
    ):
        await movement_tools.apply_arrival(
            session, "greyvale_ruins", destination_location, db_mod=_db_mod(), mutations=AsyncMock()
        )
    return pub


def _location_changed_payload(pub):
    return next(c.args[2] for c in pub.call_args_list if c.args[1] == E.LOCATION_CHANGED)


def _session() -> SessionData:
    return SessionData(player_id="p1", location_id="accord_market_square")


async def test_arrival_puts_destination_tags_on_location_changed():
    session = _session()
    pub = await _arrive(session, {"name": "Greyvale Ruins", "tags": ["dungeon", "ancient", "mystery"]})

    payload = _location_changed_payload(pub)
    assert payload["tags"] == ["dungeon", "ancient", "mystery"]


async def test_arrival_defaults_tags_to_empty_when_location_has_none():
    session = _session()
    pub = await _arrive(session, {"name": "Nowhere"})

    payload = _location_changed_payload(pub)
    assert payload["tags"] == []


async def test_arrival_defaults_tags_to_empty_when_destination_location_missing():
    session = _session()
    pub = await _arrive(session, None)

    payload = _location_changed_payload(pub)
    assert payload["tags"] == []
