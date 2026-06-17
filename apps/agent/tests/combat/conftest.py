"""Shared fixtures for the combat test suite."""

import os

import pytest
from _db_lifecycle import _DEFAULT_DATABASE_URL

import db


@pytest.fixture
async def dev_db_pool():
    """Point db.get_pool() at the docker-compose dev DB (started by tests/conftest.py), then
    restore. Mirrors acceptance's reset_db_pool but for the :55432 dev DB the non-acceptance
    lane already relies on; resolves the DSN the same way _db_lifecycle does. Shared across the
    combat real-PG tests (persistence + tx-integrity)."""
    prior = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = prior or _DEFAULT_DATABASE_URL
    await db.close_all()
    try:
        yield await db.get_pool()
    finally:
        await db.close_all()
        if prior is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prior
