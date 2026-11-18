from unittest.mock import patch

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _d20
from acceptance.seeds import seed_player_with_pools
from sample_fixtures import published_payloads

import db_mutations
import db_mutations_travel
from query_tools import query_info
from travel_tools import travel


@pytest.mark.parametrize(
    "destination,die,arrived",
    [
        ("greyvale_south_road", 20, True),
        ("greyvale_ruins_exterior", 20, True),
        ("greyvale_ruins_exterior", 1, False),
    ],
)
async def test_unheld_travel_rolls_back_hours_and_leg(world, destination, die, arrived):
    session = world.ctx.userdata
    session.location_id = "millhaven"
    for i, pid in enumerate(world.ids):
        await seed_player_with_pools(world.pool, player_id=pid)
        await configure(world, "nythera" if i == 0 else "none", "skirmisher", index=i, location_id="millhaven")
    call = game_tools(session, travel, query_info)
    write = db_mutations.update_player_location if arrived else db_mutations_travel.update_player_travel_state
    target = "db_mutations.update_player_location" if arrived else "db_mutations_travel.update_player_travel_state"

    async def abort_leg(*args, conn, **kwargs):
        await write(*args, conn=conn, **kwargs)
        await conn.execute("SELECT 1 / 0")

    before = [await row(world, i) for i in range(2)]
    with patch("check_resolution.dice_roll", return_value=_d20(die)):
        with patch(target, abort_leg), pytest.raises(asyncpg.DivisionByZeroError):
            await call("travel", destination_id=destination, mode="scenic", hours=12, forced_march=True)
        assert [await row(world, i) for i in range(2)] == before
        assert session.location_id == "millhaven"
        assert not published_payloads(session.room)
        sense = (await call("query_info", kind="patron"))["horizon_sense"]
        assert sense["hours_traveled_since_long_rest"] == 0
        result = await call("travel", destination_id=destination, mode="scenic", hours=12, forced_march=True)
    assert result["arrived"] is arrived
    for i in range(2):
        player = await row(world, i)
        assert player["travel_hours_since_rest"] == 12
        assert player["location_id"] == (destination if arrived else "millhaven")
