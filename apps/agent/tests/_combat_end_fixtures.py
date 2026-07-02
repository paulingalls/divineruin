"""Shared pytest fixture: default player-condition persistence for combat-end unit tests.

combat_end reconciles the player's persistent + beneficial-buff conditions back to players.data on
every combat end (concern ab37d4fc61c6), so it always calls db_mutations_conditions.read_player_conditions
— which a MagicMock conn can't satisfy. Any unit test that drives end_combat with a mock conn but does
not care about condition persistence needs a safe empty-store default. This fixture provides it; import
it into the conftest (or test module) of each such suite so the default is defined once, not copied.

Tests that DO care override it with their own monkeypatch (which runs after and wins). Real-PG tests
(those requesting dev_db_pool) are skipped so they exercise the actual read/save round-trip unchanged.
"""

from unittest.mock import AsyncMock

import pytest

import db_mutations_conditions


@pytest.fixture(autouse=True)
def default_condition_persistence(request, monkeypatch):
    if "dev_db_pool" in request.fixturenames:
        return
    monkeypatch.setattr(db_mutations_conditions, "read_player_conditions", AsyncMock(return_value=[]))
    monkeypatch.setattr(db_mutations_conditions, "save_player_conditions", AsyncMock())
