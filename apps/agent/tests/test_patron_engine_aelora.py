from typing import cast as type_cast
from unittest.mock import MagicMock

from _patron_engine_fixtures import configure
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from test_unbound_alone_bonus import check

from session_data import CompanionState


async def bond_counts_live_allies(world, archetype):
    w = world
    await configure(w, "aelora", archetype)
    assert (await check(w))["total"] == 11
    w.ctx.userdata.companion = CompanionState(id="ally", name="Ally", is_present=True)
    assert (await check(w))["total"] == 12
    lifecycle = _live_party(w.ctx.userdata, *w.ids)
    try:
        assert (await check(w))["total"] == (12 if archetype == "warrior" else 13)
        event = [p for p in published_payloads(w.ctx.userdata.room) if p["type"] == "dice_roll"][-1]
        assert event["total"] == (12 if archetype == "warrior" else 13)
        await configure(w, "aelora", archetype, index=1)
        with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
            assert (await check(w))["total"] == (12 if archetype == "warrior" else 13)
        handlers = dict(call.args for call in type_cast(MagicMock, lifecycle.room).on.call_args_list)
        handlers["participant_disconnected"](lifecycle.room.remote_participants[w.ids[1]])
        assert (await check(w))["total"] == 12
    finally:
        await lifecycle.aclose()


SCENARIOS = {
    "aelora_common_bond": (
        "patron_gifts:skill_gift",
        bond_counts_live_allies,
        [(a,) for a in ("artificer", "bard", "diplomat", "warrior")],
    ),
}
