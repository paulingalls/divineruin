"""Outcome seams for isolated startup and summary-consumer tests."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

import db_queries
from session_outcome import Predecessor


@pytest.fixture(autouse=True)
def isolated_outcome_startup():
    @asynccontextmanager
    async def startup(_player_id):
        summary = await db_queries.get_last_session_summary(_player_id)
        yield "isolated-session", Predecessor(None, summary, summary)

    with patch("session_outcome.startup", startup):
        yield


@pytest.fixture(autouse=True)
def isolated_outcome_completion():
    with patch("session_outcome.complete", new_callable=AsyncMock):
        yield
