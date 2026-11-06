"""Grievance and disposition writes share the authenticated actor's transaction."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _unbound_path_fixtures import world as world

import db_mutations
import db_queries
import session_tools


async def test_revocation_during_disposition_rolls_back_both_writes(world):
    w = world
    pid = w.ids[1]
    before = await db_queries.get_player(pid, conn=w.pool)
    disposition = await db_queries.get_npc_disposition("guildmaster_torin", pid, conn=w.pool)
    live = True

    def validate(*_):
        if not live:
            raise RuntimeError("stale authenticated actor")

    async def revoke(*args, **kwargs):
        nonlocal live
        await db_mutations.set_npc_disposition(*args, **kwargs)
        live = False

    with (
        w.ctx.userdata._bind_authenticated_actor(pid, 4, validate),
        patch.object(session_tools, "require_npc_present", AsyncMock()),
        patch.object(session_tools, "publish_game_event", AsyncMock()) as published,
    ):
        with pytest.raises(RuntimeError, match="stale authenticated actor"):
            await session_tools._update_npc_disposition_impl(
                w.ctx,
                "guildmaster_torin",
                1,
                "broken promise",
                "broken_promise",
                db_mod=w.db,
                queries=db_queries,
                mutations=MagicMock(set_npc_disposition=revoke, set_player_flag=db_mutations.set_player_flag),
            )
        published.assert_not_awaited()
    assert await db_queries.get_player(pid, conn=w.pool) == before
    assert await db_queries.get_npc_disposition("guildmaster_torin", pid, conn=w.pool) == disposition
