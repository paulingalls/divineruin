"""A database failure rolls back binding, disposition and conditions together."""

from unittest.mock import patch

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_skills_fixtures import FATE, INSPIRED
from _zhael_fate_skills_fixtures import party as party
from acceptance._capstone_helpers import _d20
from sample_fixtures import published_payloads
from test_zhael_foretold_words import ATTEMPT, CLAUSE, FORETELL, NPC, follower, ledger

import db_queries
import zhael_foretold_words


@pytest.mark.parametrize("held", [False, True])
async def test_settlement_rolls_back_every_write_and_retries(world, party, held) -> None:
    call, _ = party
    session = world.ctx.userdata
    await follower(world, fate=held)
    await configure(world, "zhael", "bard", conditions=INSPIRED)
    await call(0, "check", roll=FORETELL)
    pending = await ledger(world)
    clear = zhael_foretold_words.clear

    async def abort_after_clear(conn, *args) -> None:
        await clear(conn, *args)
        await conn.execute("SELECT 1 / 0")

    with patch("check_resolution.dice_roll", side_effect=[_d20(16), _d20(16)]):
        tool, arguments = "check", {"roll": ATTEMPT}
        if held:
            offer = (await call(0, tool, **arguments))["fate_offer"]
            choice = {"id": FATE, "offer_id": offer["offer_id"]}
            await call(0, "activate", **choice)
            tool, arguments = "activate", {**choice, "keep": "reroll"}
        with (
            patch.object(zhael_foretold_words, "clear", abort_after_clear),
            pytest.raises(asyncpg.DivisionByZeroError),
        ):
            await call(0, tool, **arguments)
        assert await ledger(world) == pending
        assert await db_queries.get_npc_disposition(NPC, world.ids[0]) == "neutral"
        assert (await row(world, 0))["conditions"] == INSPIRED
        assert not published_payloads(session.room)

        result = await call(0, tool, **arguments)

    assert (result["clause_id"], result["outcome"], result["new_disposition"]) == (CLAUSE, "success", "friendly")
    assert (await ledger(world))[0]["binding"] == "null"
    assert (await row(world, 0))["conditions"] == []
    assert [event["type"] for event in published_payloads(session.room)] == ["dice_roll", "disposition_changed"]
