from unittest.mock import AsyncMock, patch

import pytest
from session_outcome_fixture import isolated_outcome_completion as isolated_outcome_completion


@pytest.fixture(autouse=True)
def isolated_room_ownership():
    with patch("host_handoff.transfer_room", new_callable=AsyncMock):
        yield


@pytest.fixture(autouse=True)
def isolated_patron_ability_entry():
    with patch("session_hydration.hydrate_patron_ability_session", new_callable=AsyncMock):
        yield


@pytest.fixture(autouse=True)
def isolated_join_snapshot():
    with (
        patch("db_session_queries.get_session_init_payload", new_callable=AsyncMock) as build,
        patch("game_events.publish_game_event", new_callable=AsyncMock) as publish,
    ):
        build.return_value = {"character": {"player_id": "player_2"}, "world_state": {}}
        yield build, publish
