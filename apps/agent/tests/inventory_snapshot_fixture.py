"""Owned query mock for the versioned inventory wire contract."""

from inspect import isawaitable
from unittest.mock import AsyncMock


def snapshot_query(items, revision="1"):
    async def read(player_id, **kwargs):
        inventory = items(player_id, **kwargs) if callable(items) else items
        if isawaitable(inventory):
            inventory = await inventory
        return {"player_id": player_id, "inventory_revision": revision, "inventory": inventory}

    return AsyncMock(side_effect=read)
