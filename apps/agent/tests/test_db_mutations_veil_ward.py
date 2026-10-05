"""Location wards live in veil_wards; encounter wards live in CombatState. Reject dual state.
Multiple wards may cover the same scope."""

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
        assert "expires_at IS NULL OR expires_at > NOW()" in sql
        assert params == ["location", "thornwatch_keep"]

    async def test_breaks_ties_by_newest_ward(self):
        """Use a stable tie-breaker because this index is non-unique."""
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
        conn = AsyncMock()
        conn.fetch.return_value = []
        assert await db_mutations_veil_ward.dismiss_ward(_LOCATION, conn=conn) == 0

    async def test_fails_loud_on_encounter_scope(self):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="CombatState"):
            await db_mutations_veil_ward.dismiss_ward(_ENCOUNTER, conn=conn)
        conn.fetch.assert_not_awaited()
