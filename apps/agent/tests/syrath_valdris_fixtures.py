"""Real persistence and owned dice seams for patron producer integration tests."""

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from livekit.agents.llm.utils import prepare_function_arguments
from livekit.agents.voice import RunContext
from sample_fixtures import SAMPLE_PLAYER

import check_tools
import db_mutations_skill_advancement
import db_queries
import spell_casting
import spells
from activate_tools import _activate_impl


@pytest.fixture
async def world(dev_db_pool):
    ids = [f"producer_{uuid4().hex}" for _ in range(3)]
    async with dev_db_pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            for pid in ids:
                row = {
                    **deepcopy(SAMPLE_PLAYER),
                    "player_id": pid,
                    "class": "mage",
                    "level": 20,
                    "focus": {"current": 50},
                    "divine_favor": {"patron": "syrath"},
                }
                await conn.execute("INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)", pid, json.dumps(row))

            @asynccontextmanager
            async def scope():
                async with conn.transaction():
                    yield conn

            queries = MagicMock(wraps=db_queries)

            async def player(pid, **kwargs):
                kwargs["conn"] = conn
                return await db_queries.get_player(pid, **kwargs)

            async def advancement(*args, **kwargs):
                kwargs["conn"] = conn
                return await db_queries.get_single_skill_advancement(*args, **kwargs)

            queries.get_player = player
            queries.get_single_skill_advancement = advancement
            database = MagicMock(transaction=scope)
            yield ids, conn, database, queries
        finally:
            await tx.rollback()


async def hide(world, ctx, roll=20, skill="stealth", difficulty="easy"):
    _, conn, database, queries = world
    ctx.mock_add_spec(RunContext)
    args, kwargs = prepare_function_arguments(
        fnc=check_tools.check,
        json_arguments=json.dumps(
            {
                "roll": {
                    "kind": "skill",
                    "skill": skill,
                    "difficulty": difficulty,
                    "context_description": "A watcher might notice",
                    "hearing_only": False,
                }
            }
        ),
        call_ctx=ctx,
    )
    original = check_tools._check_skill_impl

    async def invoke(*args, **kwargs):
        mutations = MagicMock(wraps=db_mutations_skill_advancement)

        async def update(*args, **kwargs):
            kwargs["conn"] = conn
            return await db_mutations_skill_advancement.update_skill_advancement(*args, **kwargs)

        mutations.update_skill_advancement = update
        kwargs.update(db_mod=database, queries=queries, mutations=mutations)
        return await original(*args, **kwargs)

    with (
        patch.object(check_tools, "_check_skill_impl", invoke),
        patch("check_resolution.dice_roll", return_value=MagicMock(total=roll)),
    ):
        return json.loads(await check_tools.check(*args, **kwargs))


async def cast(world, ctx, spell_id="arcane_fireball", target=None, *, spell=None, target_ids=None):
    _, _, database, queries = world
    catalog = MagicMock(wraps=spells, get_spell=MagicMock(return_value=spell)) if spell else spells
    library = MagicMock(get_known=AsyncMock(return_value=[{"spell_id": spell_id}]))
    entry = partial(
        spell_casting._cast_spell_impl,
        db_mod=database,
        queries_mod=queries,
        character_spells_mod=library,
        spells_mod=catalog,
        ward_resolution_mod=MagicMock(resolve_scope_ward=AsyncMock(return_value=None)),
    )
    return json.loads(
        await _activate_impl(
            ctx,
            spell_id,
            target_id=target,
            target_ids=target_ids,
            spells_mod=catalog,
            cast_spell_mod=MagicMock(_cast_spell_impl=entry),
        )
    )


async def player_row(conn, player_id):
    row = await db_queries.get_player(player_id, conn=conn)
    assert row is not None
    return row
