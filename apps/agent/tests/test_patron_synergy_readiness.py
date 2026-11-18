"""A registered but pending clause cannot alter a live check."""

from copy import deepcopy

from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from test_aelora_gift import _live_party
from test_unbound_alone_bonus import check

import patron_synergy
from session_data import CompanionState


async def test_pending_registered_clause_retains_base(world, monkeypatch):
    w = world
    await configure(w, "aelora", "bard")
    w.ctx.userdata.companion = CompanionState(id="ally", name="Ally", is_present=True)
    lifecycle = _live_party(w.ctx.userdata, *w.ids)
    try:
        assert (await check(w))["total"] == 13
        pending = deepcopy(patron_synergy.get_archetype_synergy("bard", "aelora"))
        assert pending is not None
        pending["clauses"][0]["status"] = "pending"
        monkeypatch.setattr(patron_synergy, "get_archetype_synergy", lambda *_: pending)
        assert (await check(w))["total"] == 12
    finally:
        await lifecycle.aclose()
