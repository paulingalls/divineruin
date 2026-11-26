from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _d20
from acceptance.seeds import seed_player_with_pools

from _gods_content import load_gods
from activate_tools import activate
from check_tools import check
from query_tools import query_info
from rest_tools import rest
from zhael_fate import FATE

CLAUSE = "zhael_twice_woven"
SAVE = {"kind": "save", "save_type": "wisdom", "dc": 10, "effect_on_fail": "frightened"}


def assert_uses(packet, remaining):
    assert packet["remaining_uses"] == remaining
    assert packet["use_limit"] == 2
    assert packet["clause_id"] == CLAUSE


async def twice_woven(world):
    patron = next(god for god in load_gods() if god["god_id"] == "zhael")
    assert patron["layer_4_synergy_matrix"]["oracle"]["clauses"] == [
        {
            "effect": "Prophecy Fragment becomes 2-sentence vision with more detail.",
            "status": "active",
            "resolution": "narrated",
        },
        {
            "effect": "Fate's Thread usable twice per long rest",
            "status": "active",
            "resolution": "engine",
            "implementation_id": CLAUSE,
        },
    ]
    await seed_player_with_pools(world.pool, player_id=world.ids[0], class_="oracle")
    await configure(world, "zhael", "oracle", location_id="millhaven_inn")
    session = world.ctx.userdata
    session.location_id = "millhaven_inn"
    call = game_tools(session, check, activate, query_info, rest)

    async def query(remaining):
        gift = (await call("query_info", kind="patron"))["layer_1_gift"]
        assert_uses(gift, remaining)
        assert gift["spent"] is (remaining == 0)
        assert gift["available"] is (remaining > 0)

    async def offer():
        result = (await call("check", roll=SAVE))["fate_offer"]
        assert result["abilities"] == [{"id": FATE, "eligible_followers": world.ids[:1]}]
        return {"id": FATE, "offer_id": result["offer_id"]}

    async def spend(remaining):
        choice = await offer()
        receipt = await call("activate", **choice)
        assert_uses(receipt, remaining)
        assert receipt["original"]["die"] == 12 and receipt["reroll"]["die"] == 18
        result = await call("activate", **choice, keep="reroll")
        assert result["roll"] == 18 and result["outcome"] == "success", result
        assert (await row(world, 0))["patron_gifts"][FATE] == {"uses_spent": 2 - remaining}
        await query(remaining)

    await query(2)
    with patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in (12, 18, 12, 12, 18, 12, 12)]):
        await spend(1)
        await call("activate", **await offer(), keep="original")
        await call("rest", rest_type="short", use_song_of_rest=False)
        await query(1)
        assert (await row(world, 0))["patron_gifts"][FATE] == {"uses_spent": 1}
        await spend(0)
        assert "fate_offer" not in await call("check", roll=SAVE)
        await call("rest", rest_type="long", use_song_of_rest=False)
        assert (await row(world, 0))["patron_gifts"][FATE] == {"uses_spent": 0}
        await query(2)
        await call("activate", **await offer(), keep="original")


SCENARIOS = {CLAUSE: ("zhael_fate:availability", twice_woven, [()])}


@pytest.mark.parametrize("spent,remaining", [(True, 1), (False, 2)])
async def test_patron_query_reads_legacy_fate_state(world, spent, remaining):
    stored = {FATE: {"spent": spent}}
    await configure(world, "zhael", "oracle", patron_gifts=stored)
    call = game_tools(world.ctx.userdata, query_info)
    gift = (await call("query_info", kind="patron"))["layer_1_gift"]
    assert_uses(gift, remaining)
    assert gift["available"] and not gift["spent"]
    assert (await row(world, 0))["patron_gifts"] == stored
