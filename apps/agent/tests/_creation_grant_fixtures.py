"""Autouse stub for finalize_character's creation-time companion grant (story-003).

finalize_character now writes a companion_relationships row. Unlike create_player — which
every finalize test already mocks — that write is wrapped in a broad `except Exception`, so
an unmocked unit test does not fail, it just quietly performs real I/O. With DATABASE_URL
set (the dev shell, and the `uv run pytest tests/<path>` inner loop apps/agent/CLAUDE.md
endorses) that inserted uncleaned `test_player` / `player_1` rows into the shared dev DB,
against that doc's unique-keys-plus-cleanup rule for real-PG writes.

Import into any module that drives finalize_character without asserting on the grant. The
modules that DO assert on it patch the same attribute and win.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def stub_creation_companion_grant():
    with patch("db_mutations_companion.insert_companion_relationship_if_absent", new_callable=AsyncMock):
        yield
