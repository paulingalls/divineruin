from unittest.mock import AsyncMock, patch

import pytest
from session_outcome_fixture import isolated_outcome_completion as isolated_outcome_completion


@pytest.fixture(autouse=True)
def isolated_room_ownership():
    with patch("host_handoff.transfer_room", new_callable=AsyncMock):
        yield
