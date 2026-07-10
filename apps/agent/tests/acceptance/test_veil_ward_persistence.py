"""Capstone: M24 scope-owned Veil Ward persistence against a real Postgres testcontainer.

story-003 moved the ward off the per-player row onto the scope. This proves the property
that move exists to deliver, and that the mocked unit tests structurally cannot: two players
in one scope are backed by ONE ward row, and neither player row carries ward state (AC4).

story-005 adds the activation end: driving the real tool against a real pool, an encounter ward
lands on CombatState (never in veil_wards) and only the raiser pays for it.

Distinct from tests/test_db_mutations_veil_ward_db.py, which is the fast-lane single-table
round-trip of the accessors themselves. This file is the multi-player, post-migration proof:
it seeds real players through the same seed path production uses, and asserts the absence of
the legacy players.data.veil_ward key that migration 057 removed.

Auto-marked `acceptance` by tests/acceptance/conftest.py. Each test uses a distinct scope id
since the testcontainer DB is shared across the session.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from acceptance.seeds import seed_player, seed_player_with_pools

import db
import db_mutations
import db_mutations_veil_ward
from session_data import CombatState, ConcentrationState, PartyMember, ResonanceTrack, SessionData
from veil_ward import WardScope
from veil_ward_tools import _activate_veil_ward_impl


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


async def test_paladin_raise_in_combat_charges_only_the_raiser(reset_db_pool: str) -> None:
    """AC9, story-005: the whole activation path against a real pool, no module injection.

    A Paladin's ROUNDS ward is combat-only, so this raise targets the ENCOUNTER scope: the ward
    round-trips through combat_instances.data carrying its 3-round clock, no veil_wards row is
    written, and the Focus/Stamina come from the raiser alone even though the ward it buys covers
    the whole party.
    """
    pool = await db.get_pool()
    location_id = "cap_ward_combat_hall"  # scope ids unique to this test — the container DB is shared
    combat_id = "cap_ward_combat_1"

    await seed_player_with_pools(pool, player_id="cap_ward_pal", class_="paladin")
    await seed_player_with_pools(pool, player_id="cap_ward_ally", class_="cleric")
    # Paladin's source requires level 10; the seed default is 2.
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{level}', '10'::jsonb) WHERE player_id = $1", "cap_ward_pal"
    )

    session = SessionData(player_id="cap_ward_pal", location_id=location_id)
    session.party.members.append(
        PartyMember(player_id="cap_ward_ally", resonance=ResonanceTrack(), concentration=ConcentrationState())
    )
    combat = CombatState(combat_id=combat_id, participants=[], initiative_order=[], location_id=location_id)
    session.combat_state = combat
    await db_mutations.save_combat_state(combat_id, combat.to_dict(), conn=pool)

    ctx = MagicMock()
    ctx.userdata = session
    await _activate_veil_ward_impl(ctx, True)  # real db/queries/mutations/resolution modules

    # The encounter ward survives a full round trip through combat_instances.data...
    reloaded = await db_mutations.load_combat_state(combat_id, conn=pool)
    assert reloaded is not None
    assert reloaded.veil_ward == {"source": "paladin", "rounds_remaining": 3}

    # ...and it is NOT in veil_wards: the encounter scope has exactly one home.
    assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", combat_id) == 0
    assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", location_id) == 0

    # The raiser paid 3 Focus + 3 Stamina; the ally it also wards paid nothing.
    async def pools(player_id: str) -> tuple[int, int]:
        row = await pool.fetchrow(
            "SELECT (data->'focus'->>'current')::int AS f, (data->'stamina'->>'current')::int AS s "
            "FROM players WHERE player_id = $1",
            player_id,
        )
        return row["f"], row["s"]

    assert await pools("cap_ward_pal") == (7, 7)
    assert await pools("cap_ward_ally") == (10, 10)
