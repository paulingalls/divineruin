"""Capstone: M24 scope-owned Veil Ward persistence against a real Postgres testcontainer.

story-003 moved the ward off the per-player row onto the scope. This proves the property
that move exists to deliver, and that the mocked unit tests structurally cannot: two players
in one scope are backed by ONE ward row, and neither player row carries ward state (AC4).

Distinct from tests/test_db_mutations_veil_ward_db.py, which is the fast-lane single-table
round-trip of the accessors themselves. This file is the multi-player, post-migration proof:
it seeds real players through the same seed path production uses, and asserts the absence of
the legacy players.data.veil_ward key that migration 057 removed.

Auto-marked `acceptance` by tests/acceptance/conftest.py. Each test uses a distinct scope id
since the testcontainer DB is shared across the session.
"""

from __future__ import annotations

from acceptance.seeds import seed_player

import db
import db_mutations_veil_ward
from veil_ward import WardScope


async def test_one_row_backs_every_player_in_the_scope(reset_db_pool: str) -> None:
    """AC4: a ward written once for a scope covers both players, and no player row holds ward state."""
    pool = await db.get_pool()
    scope = WardScope.location("cap_ward_shared_hall")
    await seed_player(pool, player_id="cap_ward_p1")
    await seed_player(pool, player_id="cap_ward_p2")

    # The scope starts unwarded: no ward at all, not a default-inactive placeholder.
    assert await db_mutations_veil_ward.read_active_ward(scope, conn=pool) is None

    await db_mutations_veil_ward.write_ward(scope, "cleric", None, dismissible=True, conn=pool)

    # ONE row backs the scope...
    assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", scope.id) == 1
    # ...and every caster in it resolves the same ward, keyed by nothing player-specific.
    ward = await db_mutations_veil_ward.read_active_ward(scope, conn=pool)
    assert ward is not None and ward["source"] == "cleric"

    # Neither player row carries ward state — migration 057 removed the key and nothing rewrites it.
    for player_id in ("cap_ward_p1", "cap_ward_p2"):
        assert await pool.fetchval("SELECT data ? 'veil_ward' FROM players WHERE player_id = $1", player_id) is False, (
            f"{player_id} still carries the legacy players.data.veil_ward key"
        )


async def test_scope_ward_round_trips_and_dismisses_for_the_whole_scope(reset_db_pool: str) -> None:
    """Raise then dismiss: the ward clears for every caster at once, because it was never theirs."""
    pool = await db.get_pool()
    scope = WardScope.location("cap_ward_dismiss_hall")
    await seed_player(pool, player_id="cap_ward_p3")

    await db_mutations_veil_ward.write_ward(scope, "druid", None, dismissible=True, conn=pool)
    raised = await db_mutations_veil_ward.read_active_ward(scope, conn=pool)
    assert raised is not None and raised["source"] == "druid"

    deleted = await db_mutations_veil_ward.dismiss_ward(scope, conn=pool)
    assert deleted == 1
    assert await db_mutations_veil_ward.read_active_ward(scope, conn=pool) is None


async def test_each_ward_source_round_trips_unchanged(reset_db_pool: str) -> None:
    """Each ward source id survives the round trip; scopes are independent of one another."""
    pool = await db.get_pool()
    for source in ("cleric", "druid", "paladin"):
        scope = WardScope.location(f"cap_ward_src_{source}")
        await db_mutations_veil_ward.write_ward(scope, source, None, dismissible=True, conn=pool)
        ward = await db_mutations_veil_ward.read_active_ward(scope, conn=pool)
        assert ward is not None and ward["source"] == source
