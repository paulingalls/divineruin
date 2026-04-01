"""Shared test fixtures — auto-mock agent factories to avoid LiveKit lifecycle warnings."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_combat_agent_factory():
    """Prevent real CombatAgent construction via start_combat in tests.

    CombatAgent inherits LiveKit Agent lifecycle methods that create
    unawaited coroutines during GC in test contexts. Mocking the factory
    avoids this while still testing the tool logic.
    """
    with patch("combat_agent.create_combat_agent", return_value=MagicMock()) as mock:
        yield mock
