"""Shared test fixtures — auto-mock agent factories, seed training config."""

from unittest.mock import MagicMock, patch

import pytest
from archetype_abilities_config_fixture import setup_archetype_abilities_config_fixture
from archetype_milestones_config_fixture import setup_archetype_milestones_config_fixture
from archetypes_config_fixture import setup_archetypes_config_fixture
from spells_config_fixture import setup_spells_config_fixture
from training_config_fixture import setup_training_config_fixture


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
def seed_milestones():
    """Populate milestones._milestones from content/archetype_milestones.json before every test.

    Mirrors load_milestones() at worker/agent startup, but sync and file-based.
    Required so agent.py dm_session's guarded load_milestones() sees the map already
    populated (is_loaded() True) and skips the DB fetch in tests that exercise startup.
    """
    setup_archetype_milestones_config_fixture()
    yield
