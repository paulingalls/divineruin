"""A saved rider episode resumes in a real room and settles on a WRAP defeat."""

import pytest


@pytest.fixture
def mock_combat_agent_factory():
    yield


@pytest.fixture
def stub_companion_hydrate_io():
    yield


async def test_saved_rider_reentry_and_wrap_defeat(livekit_server, reset_db_pool, tmp_path):
    from acceptance.rider_reentry_walk import reentry_and_defeat

    await reentry_and_defeat(livekit_server, tmp_path)
