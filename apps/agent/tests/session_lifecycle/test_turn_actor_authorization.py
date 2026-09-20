"""Authenticated multiplayer turns cannot fall back to the primary player's resources."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import make_context, make_db_mod

from ability_tools import _request_ability_activation_impl
from inventory_tools import _transact_impl


def _player(player_id: str) -> dict:
    return {
        "player_id": player_id,
        "name": player_id,
        "class": "warrior",
        "level": 5,
        "stamina": {"current": 10, "max": 10},
        "focus": {"current": 10, "max": 10},
    }


async def test_bound_guest_nonreaction_spends_the_guests_resources() -> None:
    ctx = make_context(party_member_ids=["player_2"])
    db_mod, conn = make_db_mod()
    rows = {player_id: _player(player_id) for player_id in ("player_1", "player_2")}
    queries = MagicMock()

    async def lock(ids, *, conn):
        return {player_id: rows[player_id] for player_id in ids}

    queries.get_players_for_update = AsyncMock(side_effect=lock)
    persistence = MagicMock(
        owns_elective=AsyncMock(return_value=False),
        get_active_variant=AsyncMock(return_value=None),
        update_player_resources=AsyncMock(),
    )

    with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_args: None):
        await _request_ability_activation_impl(
            ctx,
            "warrior_devastating_strike",
            db_mod=db_mod,
            queries_mod=queries,
            persistence_mod=persistence,
        )

    queries.get_players_for_update.assert_awaited_once_with(["player_2"], conn=conn)
    persistence.update_player_resources.assert_awaited_once_with("player_2", stamina=7, focus=None, conn=conn)


async def test_revoked_guest_nonreaction_cannot_reach_the_resource_write() -> None:
    ctx = make_context(party_member_ids=["player_2"])
    db_mod, _conn = make_db_mod()
    lock_started = asyncio.Event()
    release_lock = asyncio.Event()
    authorized = True
    queries = MagicMock()

    async def lock(ids, *, conn):
        lock_started.set()
        await release_lock.wait()
        return {"player_2": _player("player_2")}

    queries.get_players_for_update = AsyncMock(side_effect=lock)
    persistence = MagicMock(
        owns_elective=AsyncMock(return_value=False),
        get_active_variant=AsyncMock(return_value=None),
        update_player_resources=AsyncMock(),
    )

    def validate(_player_id, _generation):
        if not authorized:
            raise RuntimeError("stale authenticated actor")

    async def invoke():
        with ctx.userdata._bind_authenticated_actor("player_2", 4, validate):
            return await _request_ability_activation_impl(
                ctx,
                "warrior_devastating_strike",
                db_mod=db_mod,
                queries_mod=queries,
                persistence_mod=persistence,
            )

    task = asyncio.create_task(invoke())
    await lock_started.wait()
    authorized = False
    release_lock.set()
    with pytest.raises(RuntimeError, match="stale"):
        await task
    persistence.update_player_resources.assert_not_awaited()


async def test_bound_guest_consumes_the_guests_inventory() -> None:
    ctx = make_context(party_member_ids=["player_2"])
    db_mod, conn = make_db_mod()
    queries = MagicMock(
        get_inventory_item=AsyncMock(return_value={"quantity": 1, "equipped": False}),
        get_player_inventory=AsyncMock(return_value=[]),
    )
    inventory_mutations = MagicMock(transact_inventory=AsyncMock(return_value=0))
    content = MagicMock(get_item=AsyncMock(return_value={"name": "Potion"}))

    with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_args: None):
        await _transact_impl(
            ctx,
            "healing_potion",
            -1,
            db_mod=db_mod,
            queries=queries,
            inventory_mutations=inventory_mutations,
            content=content,
        )

    queries.get_inventory_item.assert_awaited_once_with("player_2", "healing_potion", conn=conn, for_update=True)
    inventory_mutations.transact_inventory.assert_awaited_once_with("player_2", "healing_potion", -1, conn=conn)


def test_primary_player_fallback_fails_loud_during_a_guest_turn() -> None:
    ctx = make_context(party_member_ids=["player_2"])

    with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_args: None):
        with pytest.raises(RuntimeError, match="primary player"):
            _ = ctx.userdata.player_id
