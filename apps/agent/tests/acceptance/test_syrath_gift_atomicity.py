"""Shadow Veil transaction integrity through registered commands."""

import asyncio
import copy
import json
from unittest.mock import patch

import pytest
from acceptance.test_syrath_gift import GIFT, reconnect, row, use
from acceptance.test_syrath_gift import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_syrath_gift import veil as veil
from livekit.agents.llm import ToolError

import concealment


async def test_failure_after_both_writes_rolls_back(veil):
    h = veil
    before = await row(h)
    original = concealment.transition
    reached = []

    async def fail(*args, **kwargs):
        result = await original(*args, **kwargs)
        import db_queries

        player = await db_queries.get_player(h.players[0], conn=kwargs["conn"])
        assert player is not None
        assert player["flags"]["concealed"] and player["patron_gifts"][GIFT]["spent"]
        reached.append(result)
        raise ToolError("injected activation rollback")

    with patch.object(concealment, "transition", fail):
        assert "injected activation rollback" in await h.command("activate", {"id": GIFT}, error=True)
    assert len(reached) == 1
    assert await row(h) == before
    await use(h)


async def test_two_sessions_wait_then_spend_once(veil):
    h = veil
    other = copy.copy(h)
    await reconnect(other, close=False)
    tasks = []
    try:
        async with h.pool.acquire() as writer:
            async with writer.transaction():
                await writer.fetchrow("SELECT * FROM players WHERE player_id=$1 FOR UPDATE", h.players[0])
                pid = await writer.fetchval("SELECT pg_backend_pid()")

                async def activate(w):
                    w.model.commands.append(("activate", {"id": GIFT}))
                    with w.sd._bind_authenticated_actor(w.players[0], 1, lambda *_: None):
                        await w.session.run(user_input="Activate now.")
                    return list(w.model.receipts.values())[-1]

                tasks = [asyncio.create_task(activate(w)) for w in (h, other)]
                async with asyncio.timeout(5):
                    while (
                        await h.pool.fetchval(
                            """WITH RECURSIVE blocked(pid) AS (
                        SELECT pid FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid))
                        UNION SELECT a.pid FROM pg_stat_activity a JOIN blocked b
                        ON b.pid=ANY(pg_blocking_pids(a.pid))) SELECT count(*) FROM blocked""",
                            pid,
                        )
                        < 2
                    ):
                        assert not any(t.done() for t in tasks)
                        await asyncio.sleep(0.01)
        receipts = await asyncio.wait_for(asyncio.gather(*tasks), 10)
        assert sum(r.is_error for r in receipts) == 1
        assert "spent" in next(r.output for r in receipts if r.is_error)
        player = await row(h)
        assert player["patron_gifts"] == {"other": {"x": 1}, GIFT: {"spent": True}}
        assert player["flags"]["shadow_veil"] is True
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await other.session.aclose()


@pytest.mark.parametrize(
    "data",
    [
        {"patron_gifts": []},
        {"patron_gifts": {GIFT: {"spent": "false"}}},
        {"patron_gifts": {GIFT: {}}},
        {"flags": {"concealed": False, "shadow_veil": True}},
        {"flags": {"concealed": True, "shadow_veil": 1}},
    ],
)
async def test_malformed_activation_is_loud_and_preserves_row(veil, data):
    h = veil
    await h.pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", h.players[0], json.dumps(data))
    before = await row(h)
    await h.command("activate", {"id": GIFT}, error=True)
    assert await row(h) == before


async def test_malformed_expiry_leaves_combat_retryable(veil):
    h = veil
    await use(h)
    await h.pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{flags,shadow_veil}','1') WHERE player_id=$1",
        h.players[0],
    )
    before = await row(h)
    await h.command("end_combat", {"outcome": "fled"}, error=True)
    assert await row(h) == before
    await h.reload()


async def test_player_outside_the_fight_is_refused_without_writes(veil):
    # Expiry visits only this combat's player participants, so a lifetime written for anyone
    # else would never end: they would stay hidden, with the hidden-casting discount, silently.
    h = veil
    state = h.sd.combat_state
    state.participants = [p for p in state.participants if p.id != h.players[0]]
    if state.spatial is not None:
        state.spatial["positions"].pop(h.players[0])
        state.spatial["speeds"].pop(h.players[0])
    await h.persist()
    before = await row(h)
    assert "current player combat participant" in await h.command("activate", {"id": GIFT}, error=True)
    assert await row(h) == before
