"""Shared test fixtures — auto-mock agent factories, seed training config."""

from unittest.mock import MagicMock, patch

import pytest
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
