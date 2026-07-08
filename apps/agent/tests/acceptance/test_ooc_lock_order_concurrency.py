"""Capstone: OOC condition lock-order deadlock-freedom on a real 2-transaction Postgres.

``condition_produce.lock_ooc_caster_and_targets`` pre-locks ``{caster} UNION {party targets}`` in ONE
``get_players_for_update`` statement (``... WHERE player_id = ANY($1) ORDER BY player_id FOR
UPDATE``). ``ORDER BY player_id`` is the deadlock-freedom SSOT: every caller takes row locks in the
same global ascending order, so two overlapping casts can never build a circular wait.

``tests/test_ability_lock_order.py`` proves the ORDERING IDENTITY by construction (role-swapped
casts compute the same sorted id list, no DB). This file proves the PG SEMANTICS that identity
relies on, empirically, on a real testcontainer Postgres (risk 5da95d657255):

  * an ordered batch ``FOR UPDATE`` SERIALIZES two concurrent overlapping casts — the loser blocks
    on the winner's row locks until it commits, rather than deadlocking; and
  * re-locking a row already locked by the SAME transaction is a NO-OP.

RATIONALE, not an executed case: the retired caster-first ordering (debt 361417d1bea5) locked the
caster row, then the target row. Alice-on-Bob would hold alice and wait for bob while Bob-on-Alice
held bob and waited for alice — a circular wait Postgres resolves by aborting one txn with
``DeadlockDetectedError``. The ascending union order below makes that shape unrepresentable. We do
NOT execute the reversed order here: the tests drive the REAL helper (which always sorts ascending
and has no mid-statement seam to barrier), and an enabled test that deadlocks on purpose is a test
that hangs CI. A production reorder therefore goes red in ``test_ability_lock_order.py``, not here.

Auto-marked ``acceptance`` by tests/acceptance/conftest.py. Distinct player_ids, since the
testcontainer DB is shared across the session.
"""

from __future__ import annotations

import asyncio
import json

import asyncpg
import pytest
from acceptance.seeds import seed_player

import condition_produce
import db

# Ascending by id: ALICE < BOB. The swapped-role casts below must converge on [ALICE, BOB].
ALICE = "ooc_lock_alice"
BOB = "ooc_lock_bob"
PARTY = [ALICE, BOB]

# A regression (circular wait) must fail FAST rather than hang the acceptance lane.
GATHER_TIMEOUT_S = 10.0

# asyncpg types a `pool.acquire()`d proxy distinctly from Connection. `_QueryConn` covers anything
# that can run a query (Pool included, for a plain fetchval); `_TxnConn` excludes Pool because only
# a single connection can open a `.transaction()`.
_QueryConn = asyncpg.Connection | asyncpg.Pool | asyncpg.pool.PoolConnectionProxy
_TxnConn = asyncpg.Connection | asyncpg.pool.PoolConnectionProxy


async def _read_casts_landed(conn: _QueryConn, player_id: str) -> int:
    """The ``casts_landed`` counter on a player's JSONB row (absent on a freshly seeded row)."""
    raw = await conn.fetchval("SELECT data->>'casts_landed' FROM players WHERE player_id = $1", player_id)
    return int(raw) if raw is not None else 0


async def _cast(conn: _TxnConn, barrier: asyncio.Barrier, *, caster: str, target: str) -> list[str]:
    """One OOC cast in its own transaction: BEGIN, rendezvous, take the real batch lock, write.

    The barrier gates BEFORE the helper call — never mid-statement, which the single-statement
    batch lock makes impossible anyway — so both transactions have BEGUN and are contending for the
    same two rows at the moment either fires its ``FOR UPDATE``.

    The read-modify-write on ``casts_landed`` after the lock is the MUTUAL-EXCLUSION probe: it is a
    classic lost update unless the batch lock actually serializes the two transactions. Without it
    the test would still pass green if ``get_players_for_update`` silently dropped its ``FOR UPDATE``
    clause — deadlock-freedom is trivially true when nothing locks.
    """
    async with conn.transaction():
        await barrier.wait()
        locked_rows, caster_row = await condition_produce.lock_ooc_caster_and_targets(
            produces_ooc=True,
            player_id=caster,
            target_id=target,
            target_ids=None,
            party_member_ids=PARTY,
            conn=conn,
        )
        assert caster_row["player_id"] == caster

        # Read under the lock we just took, then write back +1. The loser's FOR UPDATE blocks until
        # the winner commits, so it re-reads the winner's value (READ COMMITTED) and lands 2, not 1.
        landed = await _read_casts_landed(conn, ALICE)
        await conn.execute(
            "UPDATE players SET data = jsonb_set(data, '{casts_landed}', $2::jsonb) WHERE player_id = $1",
            ALICE,
            json.dumps(landed + 1),
        )
        return sorted(locked_rows)


async def test_swapped_role_concurrent_ooc_casts_serialize_without_deadlock(
    reset_db_pool: str,
) -> None:
    """Alice-on-Bob and Bob-on-Alice, concurrently, in two real transactions: both commit.

    Each txn needs its OWN connection — one pooled connection cannot drive two concurrent txns.
    Neither may raise ``DeadlockDetectedError``; the loser simply blocks until the winner commits.
    """
    pool = await db.get_pool()
    await seed_player(pool, player_id=ALICE)
    await seed_player(pool, player_id=BOB)

    barrier = asyncio.Barrier(2)
    async with pool.acquire() as conn_a, pool.acquire() as conn_b:
        try:
            locked = await asyncio.wait_for(
                asyncio.gather(
                    _cast(conn_a, barrier, caster=ALICE, target=BOB),
                    _cast(conn_b, barrier, caster=BOB, target=ALICE),
                ),
                timeout=GATHER_TIMEOUT_S,
            )
        except asyncpg.exceptions.DeadlockDetectedError as exc:  # pragma: no cover - regression
            pytest.fail(f"ascending union lock order deadlocked: {exc}")
        except TimeoutError as exc:  # pragma: no cover - regression
            pytest.fail(f"concurrent OOC casts did not both commit within {GATHER_TIMEOUT_S}s: {exc}")

    # Both transactions committed, and each locked the SAME ascending union despite swapped roles.
    assert locked == [[ALICE, BOB], [ALICE, BOB]]

    # No lost update: the batch FOR UPDATE genuinely serialized the two overlapping casts.
    assert await _read_casts_landed(pool, ALICE) == 2


async def test_self_targeted_cast_relocks_caster_row_as_a_no_op(reset_db_pool: str) -> None:
    """caster in targets: the union dedups, and re-``FOR UPDATE``-ing an already-held row is a no-op.

    This is the specific PG semantic risk 5da95d657255 named. The second helper call in the SAME
    transaction re-locks the caster row it already holds; Postgres neither blocks nor errors, and
    the txn commits.
    """
    pool = await db.get_pool()
    await seed_player(pool, player_id=ALICE)

    async with pool.acquire() as conn:
        async with conn.transaction():
            locked_rows, _ = await condition_produce.lock_ooc_caster_and_targets(
                produces_ooc=True,
                player_id=ALICE,
                target_id=ALICE,  # self-target: {ALICE} | {ALICE} dedups to one row
                target_ids=None,
                party_member_ids=PARTY,
                conn=conn,
            )
            assert sorted(locked_rows) == [ALICE]

            # Re-lock the row this transaction already holds: a no-op, not a self-block.
            relocked, _ = await asyncio.wait_for(
                condition_produce.lock_ooc_caster_and_targets(
                    produces_ooc=True,
                    player_id=ALICE,
                    target_id=ALICE,
                    target_ids=None,
                    party_member_ids=PARTY,
                    conn=conn,
                ),
                timeout=GATHER_TIMEOUT_S,
            )
            assert sorted(relocked) == [ALICE]
