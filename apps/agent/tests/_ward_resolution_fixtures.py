"""Shared pytest fixture: stub the un-mockable DB read behind ward resolution (M24 story-006).

The cast path, movement arrival, and the activation tool all ask "is this party warded?"
through ``ward_resolution.resolve_scope_ward``. That resolver is INTERNAL LOGIC — the
covering-scope OR (encounter ward first, else the location row) this milestone exists to
centralize. The only thing a MagicMock conn cannot serve is the leaf DB read underneath it,
``db_mutations_veil_ward.read_active_ward``.

So we stub exactly that boundary and nothing above it. The real resolver still runs: it reads
``combat_state.veil_ward`` from memory, and for a location scope calls this stub. A mock-conn
test that wants "no ward" gets one (the leaf answers "no row"); a test that wants a ward sets
``combat_state.veil_ward`` or overrides the leaf, and the gate fires for real. This stubs at the
system edge and trusts the internal logic, per CLAUDE.md.

The predecessor stubbed ``resolve_scope_ward`` itself, which answered every ward gate "unwarded"
forever — a consumer whose gate IS that call could never be tested honestly (concern
ec9d730b899d, debt bc5730af663c). story-005 had to inject the real resolver to work around it.
TestCastSpellWardThroughRealResolver in test_spell_casting.py is the non-vacuity proof: it fails
against the old fixture and passes against this one.

Suites that exercise ``read_active_ward`` itself shadow this fixture with a no-op, the way
test_ward_resolution.py already shadows it to test the resolver.

Mirrors _combat_end_fixtures.default_condition_persistence, which solved the same problem when
combat_end grew an unconditional condition read. Real-PG tests are exempt so they exercise the
actual read unchanged — both the fast-lane ``dev_db_pool`` and the acceptance-lane
``reset_db_pool``, since the m32 capstone proves real halving against a real veil_wards row.
"""

from unittest.mock import AsyncMock

import pytest

import db_mutations_veil_ward

# A real pool means the test can serve the real query; do not stub it out from under them.
_REAL_DB_FIXTURES = ("dev_db_pool", "reset_db_pool")


@pytest.fixture(autouse=True)
def default_unwarded_scope(request, monkeypatch):
    if any(name in request.fixturenames for name in _REAL_DB_FIXTURES):
        return
    monkeypatch.setattr(db_mutations_veil_ward, "read_active_ward", AsyncMock(return_value=None))
