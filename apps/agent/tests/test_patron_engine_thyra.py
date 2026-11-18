import json
from unittest.mock import patch

from _patron_engine_fixtures import configure
from acceptance._capstone_helpers import _d20
from sample_fixtures import published_payloads


async def wild_kinship_adds_city_bonus(world, archetype, skill):
    from check_tools import _check_impl

    await configure(world, "thyra", archetype)
    with patch("check_resolution.dice_roll", return_value=_d20(11)) as dice:
        packet = json.loads(await _check_impl(world.ctx, "skill", skill=skill, difficulty="moderate"))
    assert dice.call_count == 1
    assert packet["roll"] == 11
    assert packet["modifier"] == 2
    assert packet["total"] == 13
    assert packet["gift_name"] == "Nature's Pulse"
    event = [p for p in published_payloads(world.ctx.userdata.room) if p["type"] == "dice_roll"][-1]
    assert event["total"] == 13


SCENARIOS = {
    "thyra_wild_kinship": (
        "patron_gifts:skill_gift",
        wild_kinship_adds_city_bonus,
        [(a, s) for a in ("druid", "beastcaller", "warden") for s in ("perception", "survival")],
    ),
}
