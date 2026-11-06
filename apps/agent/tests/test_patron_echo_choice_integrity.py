"""Real row locks and transaction rollback protect pending spoken choices."""

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context
from test_patron_resonance_effects import cast

import db_queries
import patron_echo_choice
from choice_tools import _select_impl


@pytest.fixture
async def players(dev_db_pool):
    ids = ["echo_" + uuid4().hex for _ in range(2)]
    for pid in ids:
        await dev_db_pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)",
            pid,
            json.dumps(
                {
                    "class": "mage",
                    "level": 5,
                    "focus": {"current": 50},
                    "divine_favor": {"patron": "zhael"},
                }
            ),
        )

    @asynccontextmanager
    async def transaction():
        async with dev_db_pool.acquire() as conn, conn.transaction():
            yield conn

    try:
        yield ids, dev_db_pool, MagicMock(transaction=transaction)
    finally:
        await dev_db_pool.execute("DELETE FROM players WHERE player_id = ANY($1)", ids)


async def pending_cast(ids, pool, database, *, total=9):
    ctx = make_context(player_id=ids[0], party_member_ids=ids)
    # Activate opens its own real transaction; all pending-choice SQL uses that connection.
    result = await cast("zhael", total, ctx=ctx, database=(database, pool), queries=db_queries)
    return ctx, result[0]["pending_choice"]


async def test_foreign_invalid_replay_and_concurrent_selection(players):
    ids, pool, database = players
    ctx, pending = await pending_cast(ids, pool, database)
    cid = pending["choice_id"]
    guest = make_context(player_id=ids[1], party_member_ids=ids)
    await cast("zhael", 9, ctx=guest, database=(database, pool), queries=db_queries)
    guest_before = await db_queries.get_player(ids[1], conn=pool)
    with patch("hollow_echo_events.publish_hollow_echo", new_callable=AsyncMock) as published:
        for who, choice, option in [(guest, cid, "first"), (ctx, cid, "third"), (ctx, cid + "stale", "first")]:
            with pytest.raises(ToolError):
                await _select_impl(who, choice, option, db_mod=database)
        row = await db_queries.get_player(ids[0], conn=pool)
        assert row is not None
        assert row[patron_echo_choice.KEY]["choice_id"] == cid
        published.assert_not_awaited()
        assert await db_queries.get_player(ids[1], conn=pool) == guest_before
        results = await asyncio.gather(
            *[_select_impl(ctx, cid, option, db_mod=database) for option in ("first", "second")], return_exceptions=True
        )
        assert sum(isinstance(r, str) for r in results) == 1
        assert sum(isinstance(r, ToolError) for r in results) == 1
        published.assert_awaited_once()
        selected_row = await db_queries.get_player(ids[0], conn=pool)
        assert selected_row is not None and patron_echo_choice.KEY not in selected_row
        with pytest.raises(ToolError):
            await _select_impl(ctx, cid, "first", db_mod=database)
        published.assert_awaited_once()


async def test_pending_refusal_preserves_offer_resources_and_other_member(players):
    ids, pool, database = players
    ctx, pending = await pending_cast(ids, pool, database)
    before = await db_queries.get_player(ids[0], conn=pool)
    with pytest.raises(ToolError) as refusal:
        await cast("zhael", ctx=ctx, database=(database, pool), queries=db_queries)
    assert pending["choice_id"] in str(refusal.value)
    assert all(option["name"] in str(refusal.value) for option in pending["options"])
    assert await db_queries.get_player(ids[0], conn=pool) == before
    other = make_context(player_id=ids[1], party_member_ids=ids)
    packet, *_ = await cast("zhael", 5, ctx=other, database=(database, pool), queries=db_queries)
    assert packet["state"] == "flickering"


@pytest.mark.parametrize("stage", ["cast", "select"])
async def test_transaction_failure_leaves_no_partial_choice_or_event(players, stage):
    ids, pool, database = players
    ctx = make_context(player_id=ids[0], party_member_ids=ids)
    pending = None
    if stage == "select":
        ctx, pending = await pending_cast(ids, pool, database)
    before = await db_queries.get_player(ids[0], conn=pool)
    resonance = ctx.userdata.resonance.current
    operation = "store" if stage == "cast" else "consume"
    original = getattr(patron_echo_choice.persistence, operation)

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("after choice write")

    with (
        patch.object(patron_echo_choice.persistence, operation, fail),
        patch("hollow_echo_events.publish_hollow_echo", new_callable=AsyncMock) as published,
    ):
        with pytest.raises(RuntimeError, match="after choice write"):
            if stage == "cast":
                await cast(
                    "zhael", 9, ctx=ctx, spell_id="arcane_fireball", database=(database, pool), queries=db_queries
                )
            else:
                assert pending is not None
                await _select_impl(ctx, pending["choice_id"], "second", db_mod=database)
        published.assert_not_awaited()
    assert await db_queries.get_player(ids[0], conn=pool) == before
    # The test helper sets the pre-cast standing total; the transaction cannot sync a new one.
    assert ctx.userdata.resonance.current == (9 if stage == "cast" else resonance)
    if pending:
        with patch("hollow_echo_events.publish_hollow_echo", new_callable=AsyncMock):
            await _select_impl(ctx, pending["choice_id"], "second", db_mod=database)


@pytest.mark.parametrize("bad", [None, {}, {"choice_id": "hollow_echo_bad", "player_id": "owner", "options": []}])
async def test_malformed_pending_fails_loud_at_cast_boundary(players, bad):
    ids, pool, database = players
    await pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{pending_hollow_echo_choice}', $2::jsonb) WHERE player_id=$1",
        ids[0],
        json.dumps(bad),
    )
    with pytest.raises(ToolError, match="Malformed"):
        await cast("zhael", ctx=make_context(player_id=ids[0]), database=(database, pool), queries=db_queries)


async def test_revoked_guest_cannot_create_choice_after_row_lock(players):
    ids, pool, database = players
    ctx = make_context(player_id=ids[0], party_member_ids=ids)
    ctx.userdata.member_state(ids[1]).resonance.current = 9
    before = await db_queries.get_player(ids[1], conn=pool)
    live = True
    lock = db_queries.get_players_for_update

    def validate(*_):
        if not live:
            raise RuntimeError("stale authenticated actor")

    async def revoke(*args, **kwargs):
        nonlocal live
        rows = await lock(*args, **kwargs)
        live = False
        return rows

    with (
        ctx.userdata._bind_authenticated_actor(ids[1], 4, validate),
        patch.object(db_queries, "get_players_for_update", revoke),
        patch("hollow_echo_events.publish_hollow_echo", new_callable=AsyncMock) as published,
    ):
        with pytest.raises(RuntimeError, match="stale authenticated actor"):
            await cast("zhael", 9, ctx=ctx, database=(database, pool), queries=db_queries)
        published.assert_not_awaited()
    assert await db_queries.get_player(ids[1], conn=pool) == before
