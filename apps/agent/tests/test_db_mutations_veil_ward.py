"""Tests for the scope-keyed Veil Ward DB layer (db_mutations_veil_ward, story-003, M24).

Pass a mock conn directly (the functions accept conn=) and assert the SQL + params, mirroring
test_db_mutations_resonance.py. The real-PG round-trip lives in the fast lane at
tests/test_db_mutations_veil_ward_db.py; the migration key-drop proof is acceptance-lane.

Storage shape: veil_wards rows keyed by a surrogate ward_id, looked up by the NON-unique
(scope_kind, scope_id) pair. A ward is owned by its scope, never by a caster
(veil_ward_scope_model.md §1), so nothing here takes a player_id.

Only LOCATION scopes are persisted. ENCOUNTER wards ride CombatState inside
combat_instances.data — handing one to this module is a programming error, not a silent write,
so every function fails loud on an encounter scope. That guard is what keeps "one home each,
no dual state" true.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

import db_mutations_veil_ward
from veil_ward import WardScope

_LOCATION = WardScope.location("thornwatch_keep")
_ENCOUNTER = WardScope.encounter("combat_42")


@pytest.fixture(autouse=True)
def default_unwarded_scope():
    """Shadow the global read_active_ward stub — this suite tests that leaf directly."""
    yield


class TestWriteWard:
    async def test_inserts_scope_source_expiry_and_dismissible(self):
        conn = AsyncMock()
        expires = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
        await db_mutations_veil_ward.write_ward(_LOCATION, "cleric", expires, dismissible=True, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "INSERT INTO veil_wards" in sql
        # ward_id is never supplied — the DB default (gen_random_uuid) generates it.
        assert "ward_id" not in sql
        assert params == ["location", "thornwatch_keep", "cleric", expires, True]

    async def test_permanent_ward_writes_null_expiry(self):
        conn = AsyncMock()
        await db_mutations_veil_ward.write_ward(_LOCATION, "sacred_site", None, dismissible=False, conn=conn)
        _sql, *params = conn.execute.call_args.args
        assert params == ["location", "thornwatch_keep", "sacred_site", None, False]

    async def test_fails_loud_on_encounter_scope(self):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="CombatState"):
            await db_mutations_veil_ward.write_ward(_ENCOUNTER, "paladin", None, dismissible=True, conn=conn)
        conn.execute.assert_not_awaited()


class TestReadActiveWard:
    async def test_returns_none_when_no_live_ward(self):
        """An unwarded scope returns no ward — not a default-inactive placeholder (AC1)."""
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        assert await db_mutations_veil_ward.read_active_ward(_LOCATION, conn=conn) is None

    async def test_returns_the_covering_ward(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"source": "cleric", "expires_at": None, "dismissible": True}
        out = await db_mutations_veil_ward.read_active_ward(_LOCATION, conn=conn)
        assert out == {"source": "cleric", "expires_at": None, "dismissible": True}

    async def test_query_filters_scope_and_live_expiry(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        await db_mutations_veil_ward.read_active_ward(_LOCATION, conn=conn)
        sql, *params = conn.fetchrow.call_args.args
        assert "FROM veil_wards" in sql
        assert "scope_kind = $1" in sql and "scope_id = $2" in sql
        # Lazy expiry: NULL never expires, otherwise compare against NOW(). Nothing sweeps.
        assert "expires_at IS NULL OR expires_at > NOW()" in sql
        assert params == ["location", "thornwatch_keep"]

    async def test_breaks_ties_by_newest_ward(self):
        """The scope index is non-unique, so many wards may cover one scope. Pick deterministically."""
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        await db_mutations_veil_ward.read_active_ward(_LOCATION, conn=conn)
        sql, *_ = conn.fetchrow.call_args.args
        assert "ORDER BY created_at DESC" in sql
        # ward_id is the surrogate-PK secondary sort: same-transaction inserts share one
        # created_at, so it makes the order total rather than arbitrary.
        assert "ward_id DESC" in sql
        assert "LIMIT 1" in sql

    async def test_fails_loud_on_encounter_scope(self):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="CombatState"):
            await db_mutations_veil_ward.read_active_ward(_ENCOUNTER, conn=conn)
        conn.fetchrow.assert_not_awaited()


class TestDismissWard:
    async def test_deletes_only_dismissible_wards_in_scope(self):
        conn = AsyncMock()
        conn.fetch.return_value = [{"ward_id": "w1"}]
        await db_mutations_veil_ward.dismiss_ward(_LOCATION, conn=conn)
        sql, *params = conn.fetch.call_args.args
        assert "DELETE FROM veil_wards" in sql
        assert "scope_kind = $1" in sql and "scope_id = $2" in sql
        # A permanent Sacred site / large anchor is NOT the party's to dispel (§4, §5).
        assert "dismissible" in sql
        assert params == ["location", "thornwatch_keep"]

    async def test_returns_the_number_of_wards_dismissed(self):
        conn = AsyncMock()
        conn.fetch.return_value = [{"ward_id": "w1"}, {"ward_id": "w2"}]
        assert await db_mutations_veil_ward.dismiss_ward(_LOCATION, conn=conn) == 2

    async def test_returns_zero_when_nothing_dismissible_covers_the_scope(self):
        """A scope held only by a permanent ward. The caller must be able to refuse, not no-op."""
        conn = AsyncMock()
        conn.fetch.return_value = []
        assert await db_mutations_veil_ward.dismiss_ward(_LOCATION, conn=conn) == 0

    async def test_fails_loud_on_encounter_scope(self):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="CombatState"):
            await db_mutations_veil_ward.dismiss_ward(_ENCOUNTER, conn=conn)
        conn.fetch.assert_not_awaited()
