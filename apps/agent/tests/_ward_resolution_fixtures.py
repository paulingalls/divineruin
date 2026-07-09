"""Shared pytest fixture: a safe unwarded default for the cast path's ward read (M24 story-004).

spell_casting now resolves the Veil Ward from the DATABASE on every cast
(ward_resolution.resolve_scope_ward), because the in-memory mirror cannot see a ward whose
expires_at lapsed mid-session, nor one the party walked away from. That read hits
db_mutations_veil_ward.read_active_ward — which a MagicMock conn cannot satisfy.

Every mock-conn cast test that does not care about the ward needs a safe default, and "no ward"
is exactly the state they were all implicitly in before this story: they read
``caster.veil_ward.active``, which defaulted False. So the default preserves their intent rather
than changing it.

Directly mirrors _combat_end_fixtures.default_condition_persistence, which solved the same problem
when combat_end grew an unconditional condition read. Import it into the conftest of each suite
that drives a cast with a mock conn, so the default is defined once, not copied.

Tests that DO care about the ward override it with their own monkeypatch (which runs after and
wins), or inject ``ward_resolution_mod``. Real-PG tests are skipped so they exercise the actual
scope read unchanged — both the fast-lane ``dev_db_pool`` and the acceptance-lane ``reset_db_pool``,
since the m32 capstone proves real halving against a real veil_wards row.
"""

from unittest.mock import AsyncMock

import pytest

import ward_resolution

# A real pool means the test can serve the real query; do not stub it out from under them.
_REAL_DB_FIXTURES = ("dev_db_pool", "reset_db_pool")


@pytest.fixture(autouse=True)
def default_unwarded_scope(request, monkeypatch):
    if any(name in request.fixturenames for name in _REAL_DB_FIXTURES):
        return
    monkeypatch.setattr(ward_resolution, "resolve_scope_ward", AsyncMock(return_value=None))
