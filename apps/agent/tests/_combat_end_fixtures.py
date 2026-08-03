"""Shared pytest fixtures: the DB reads combat_end performs on EVERY teardown.

Both fixtures exist for the same reason: combat_end grew an unconditional read that a MagicMock
conn can't satisfy, so any unit test that drives end_combat with a mock conn — and does not care
about that read — needs a safe default rather than its own boilerplate.

  - ``default_condition_persistence``: combat_end reconciles the player's persistent +
    beneficial-buff conditions back to players.data on every combat end (concern ab37d4fc61c6).
  - ``default_player_row``: the combat-end XP Resolve (M28 story-001) reads every player
    participant's row FOR UPDATE on a victory, where previously nothing did unless the enemies
    happened to drop coin.

Import them into the conftest (or test module) of each such suite so the defaults are defined once,
not copied. Tests that DO care override with their own monkeypatch or DI (both run after / win).
Real-PG tests (those requesting dev_db_pool) are skipped so they exercise the real round-trip.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import GUILD_PLAYER

import db_mutations_conditions
import db_queries


def combat_end_mutations() -> MagicMock:
    """A db_mutations stand-in covering the writes combat_end makes on a plain victory teardown.

    A bare MagicMock() is not enough — every one of these is awaited, and an un-stubbed attribute
    returns a non-awaitable MagicMock. Kept in one place so the next write combat_end grows is a
    single edit rather than a sweep across the combat / handoff suites."""
    return MagicMock(
        delete_combat_state=AsyncMock(),
        update_player_xp=AsyncMock(),
        set_player_flag=AsyncMock(),
    )


def combat_end_queries(**overrides) -> MagicMock:
    """A db_queries stand-in covering the reads combat_end performs on a victory teardown: every
    player participant's row (the XP Resolve locks it FOR UPDATE) and their inventory (weapon
    durability). ``overrides`` shadow either — e.g. an equipped-weapon inventory."""
    queries = MagicMock(
        get_player=AsyncMock(side_effect=lambda pid, conn=None, for_update=False: {**GUILD_PLAYER, "player_id": pid}),
        get_player_inventory=AsyncMock(return_value=[]),
    )
    for name, value in overrides.items():
        setattr(queries, name, value)
    return queries


@pytest.fixture(autouse=True)
def default_condition_persistence(request, monkeypatch):
    if "dev_db_pool" in request.fixturenames:
        return
    monkeypatch.setattr(db_mutations_conditions, "read_player_conditions", AsyncMock(return_value=[]))
    monkeypatch.setattr(db_mutations_conditions, "save_player_conditions", AsyncMock())


@pytest.fixture(autouse=True)
def default_player_row(request, monkeypatch):
    """A plausible level-1 row for any player_id, so the combat-end XP grant has something to read."""
    if "dev_db_pool" in request.fixturenames:
        return
    monkeypatch.setattr(
        db_queries,
        "get_player",
        AsyncMock(side_effect=lambda pid, conn=None, for_update=False: {**GUILD_PLAYER, "player_id": pid}),
    )
