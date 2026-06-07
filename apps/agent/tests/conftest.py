"""Shared test fixtures — auto-mock agent factories, seed training config."""

from unittest.mock import MagicMock, patch

import pytest
from _db_lifecycle import ensure_db_up, stop_if_started
from archetype_abilities_config_fixture import setup_archetype_abilities_config_fixture
from archetype_milestones_config_fixture import setup_archetype_milestones_config_fixture
from archetypes_config_fixture import setup_archetypes_config_fixture
from mentor_variants_config_fixture import setup_mentor_variants_config_fixture
from spells_config_fixture import setup_spells_config_fixture
from training_config_fixture import setup_training_config_fixture

# Tracks whether THIS process started docker compose, so sessionfinish only
# stops what sessionstart started.
_started_db = False


def _is_xdist_worker(config: pytest.Config) -> bool:
    """True on an xdist worker subprocess; False on the controller / serial run."""
    return hasattr(config, "workerinput")


def pytest_sessionstart(session: pytest.Session) -> None:
    """Start the docker-compose dev DB for the run if it isn't already up.

    Many non-acceptance tests connect to the dev Postgres at :55432, so a bare
    `pytest` would fail when docker isn't running. ensure_db_up() is a fast
    no-op when the DB is already reachable (the common dev case) and only starts
    docker compose when it's down. See _db_lifecycle.py.

    Under pytest-xdist (-n N) every worker runs its own session; gating on the
    controller (no `workerinput`) ensures docker is started/stopped exactly once
    so a worker that finishes early can't stop the DB while others still query.
    """
    global _started_db
    if _is_xdist_worker(session.config):
        return
    _started_db = ensure_db_up()


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Stop docker compose iff this run started it (never `down -v`).

    Runs only on the controller / serial run, mirroring pytest_sessionstart, so
    the dev DB is preserved and workers never tear it down mid-run.
    """
    if _is_xdist_worker(session.config):
        return
    stop_if_started(_started_db)


@pytest.fixture(autouse=True)
def mock_combat_agent_factory():
    """Prevent real CombatAgent construction via start_combat in tests.

    CombatAgent inherits LiveKit Agent lifecycle methods that create
    unawaited coroutines during GC in test contexts. Mocking the factory
    avoids this while still testing the tool logic.
    """
    with patch("combat_agent.create_combat_agent", return_value=MagicMock()) as mock:
        yield mock


@pytest.fixture(autouse=True)
def seed_training_config():
    """Populate training_rules._activity_types from content JSON before every test.

    Mirrors what load_training_activity_types() does at worker startup in
    production, but sync and file-based. Runs before each test so tests can
    freely call set_training_activity_types() to override without polluting
    other tests.
    """
    setup_training_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_archetypes():
    """Populate archetypes._archetypes from content/archetypes.json before every test.

    Mirrors load_archetypes() at worker startup, but sync and file-based, so
    chassis-fed math (calculate_max_hp, calculate_max_pools) resolves without a DB.
    """
    setup_archetypes_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_abilities():
    """Populate abilities._abilities from content/archetype_abilities.json before every test.

    Mirrors load_abilities() at worker/agent startup, but sync and file-based.
    Required so agent.py dm_session's guarded load_abilities() sees the map already
    populated (is_loaded() True) and skips the DB fetch in tests that exercise startup.
    """
    setup_archetype_abilities_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_spells():
    """Populate spells._spells from content/spells.json before every test.

    Mirrors load_spells() at worker/agent startup, but sync and file-based.
    Required so agent.py dm_session's guarded load_spells() sees the map already
    populated (is_loaded() True) and skips the DB fetch in tests that exercise startup.
    """
    setup_spells_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_mentor_variants():
    """Populate mentor_variants._mentor_variants from content before every test.

    Mirrors load_mentor_variants() at worker/agent startup, but sync and
    file-based. Required so agent.py dm_session's guarded load_mentor_variants()
    sees the map already populated (is_loaded() True) and skips the DB fetch in
    tests that exercise startup.
    """
    setup_mentor_variants_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_milestones():
    """Populate milestones._milestones from content/archetype_milestones.json before every test.

    Mirrors load_milestones() at worker/agent startup, but sync and file-based.
    Required so agent.py dm_session's guarded load_milestones() sees the map already
    populated (is_loaded() True) and skips the DB fetch in tests that exercise startup.
    """
    setup_archetype_milestones_config_fixture()
    yield
