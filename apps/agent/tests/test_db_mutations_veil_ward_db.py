"""Real-PG round-trip for the M24 veil_wards scope table (story-003, migration 057).

Single-table round-trip against the shared dev DB at :55432 (fast lane; conftest auto-starts
docker). Proves the scope-keyed accessors against real SQL: an unwarded scope reads back as no
ward at all, a written ward reads back with its source, lazy expiry hides an elapsed ward
without any sweeper, and many wards may cover one scope without clobbering each other.

Isolates via a unique scope_id + cleanup (the _db_lifecycle / dev_db_pool pattern) — the rows
are scope-keyed, so a uuid scope_id can never collide with another test's.

Requires migration 057 on the dev DB: run `bun run migrate` first (CI does this before the lane).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

import db
import db_mutations_veil_ward
from veil_ward import WardScope

pytestmark = pytest.mark.usefixtures("dev_db_pool")


async def _delete_scope(scope: WardScope) -> None:
    pool = await db.get_pool()
    await pool.execute("DELETE FROM veil_wards WHERE scope_kind = $1 AND scope_id = $2", scope.kind.value, scope.id)


def _unique_location() -> WardScope:
    return WardScope.location(f"test_loc_{uuid.uuid4().hex}")


async def test_unwarded_scope_returns_no_ward():
    """AC1: an unwarded scope returns no ward, not a default-inactive placeholder."""
    pool = await db.get_pool()
    scope = _unique_location()
    assert await db_mutations_veil_ward.read_active_ward(scope, conn=pool) is None


async def test_write_then_read_round_trips_the_ward():
    """AC1: a scope with an active ward reads back with its source."""
    pool = await db.get_pool()
    scope = _unique_location()
    try:
        await db_mutations_veil_ward.write_ward(scope, "cleric", None, dismissible=True, conn=pool)
        ward = await db_mutations_veil_ward.read_active_ward(scope, conn=pool)
        assert ward is not None
        assert ward["source"] == "cleric"
        assert ward["expires_at"] is None  # no absolute expiry: until dismissed
        assert ward["dismissible"] is True
    finally:
        await _delete_scope(scope)


async def test_expired_ward_is_not_returned_without_any_sweeper():
    """Lazy expiry: nothing sweeps veil_wards; the read simply compares expires_at to NOW()."""
    pool = await db.get_pool()
    scope = _unique_location()
    past = datetime.now(UTC) - timedelta(hours=1)
    future = datetime.now(UTC) + timedelta(hours=1)
    try:
        await db_mutations_veil_ward.write_ward(scope, "artificer", past, dismissible=False, conn=pool)
        assert await db_mutations_veil_ward.read_active_ward(scope, conn=pool) is None
        # The row is still there — it was hidden by the read, not deleted by a tick loop.
        assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", scope.id) == 1

        await db_mutations_veil_ward.write_ward(scope, "cleric", future, dismissible=True, conn=pool)
        ward = await db_mutations_veil_ward.read_active_ward(scope, conn=pool)
        assert ward is not None and ward["source"] == "cleric"
    finally:
        await _delete_scope(scope)


async def test_a_short_ward_never_clobbers_a_permanent_one():
    """The (scope_kind, scope_id) index is non-unique on purpose.

    A 1-hour Artificer anchor deployed at a Sacred site must coexist with the permanent ward.
    Were the scope unique, the anchor would overwrite it and the site would silently fall an
    hour later (decision 4e126734aebe).
    """
    pool = await db.get_pool()
    scope = _unique_location()
    soon = datetime.now(UTC) + timedelta(hours=1)
    try:
        await db_mutations_veil_ward.write_ward(scope, "sacred_site", None, dismissible=False, conn=pool)
        await db_mutations_veil_ward.write_ward(scope, "artificer", soon, dismissible=False, conn=pool)

        assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", scope.id) == 2
        # Both cover the scope; the newest wins the deterministic tie-break.
        ward = await db_mutations_veil_ward.read_active_ward(scope, conn=pool)
        assert ward is not None and ward["source"] == "artificer"

        # Expire the anchor by hand; the permanent ward still covers the scope.
        await pool.execute(
            "UPDATE veil_wards SET expires_at = NOW() - INTERVAL '1 minute' WHERE scope_id = $1 AND source = $2",
            scope.id,
            "artificer",
        )
        ward = await db_mutations_veil_ward.read_active_ward(scope, conn=pool)
        assert ward is not None and ward["source"] == "sacred_site"
    finally:
        await _delete_scope(scope)


async def test_dismiss_removes_dismissible_wards_and_spares_permanent_ones():
    """§5: any in-scope member may dismiss a dismissible ward; a Sacred site is not theirs to dispel."""
    pool = await db.get_pool()
    scope = _unique_location()
    try:
        await db_mutations_veil_ward.write_ward(scope, "sacred_site", None, dismissible=False, conn=pool)
        await db_mutations_veil_ward.write_ward(scope, "cleric", None, dismissible=True, conn=pool)

        await db_mutations_veil_ward.dismiss_ward(scope, conn=pool)

        rows = await pool.fetch("SELECT source FROM veil_wards WHERE scope_id = $1", scope.id)
        assert [r["source"] for r in rows] == ["sacred_site"]
        # The scope is still warded — the resolved state, not the dismissed scope's own toggle (§3).
        ward = await db_mutations_veil_ward.read_active_ward(scope, conn=pool)
        assert ward is not None and ward["source"] == "sacred_site"
    finally:
        await _delete_scope(scope)


async def test_two_players_in_one_scope_are_backed_by_a_single_row():
    """AC4: the ward is scope-owned. One row backs every caster in the scope."""
    pool = await db.get_pool()
    scope = _unique_location()
    try:
        await db_mutations_veil_ward.write_ward(scope, "cleric", None, dismissible=True, conn=pool)
        assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", scope.id) == 1

        # Every caster in the scope resolves the same ward; nothing is keyed by player_id.
        for _ in ("player_1", "player_2"):
            ward = await db_mutations_veil_ward.read_active_ward(scope, conn=pool)
            assert ward is not None and ward["source"] == "cleric"

        assert "player_id" not in await pool.fetchval(
            "SELECT string_agg(column_name, ',') FROM information_schema.columns WHERE table_name = 'veil_wards'"
        )
    finally:
        await _delete_scope(scope)
