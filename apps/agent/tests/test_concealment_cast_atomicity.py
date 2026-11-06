"""The cast's new concealment write belongs to the existing cast transaction."""

from unittest.mock import patch

import pytest
from sample_fixtures import make_context
from syrath_valdris_fixtures import cast, hide, player_row
from syrath_valdris_fixtures import world as world

import ability_persistence


async def test_later_cast_failure_rolls_back_reveal(world):
    ids, conn, _, _ = world
    ctx = make_context(player_id=ids[0])
    await hide(world, ctx)

    async def fail_later(*args, **kwargs):
        row = await player_row(conn, ids[0])
        assert row["flags"]["concealed"] is False
        raise RuntimeError("later cast write failed")

    with patch.object(ability_persistence, "update_player_resources", fail_later):
        with pytest.raises(RuntimeError, match="later cast write failed"):
            await cast(world, ctx)
    assert (await player_row(conn, ids[0]))["flags"]["concealed"] is True
