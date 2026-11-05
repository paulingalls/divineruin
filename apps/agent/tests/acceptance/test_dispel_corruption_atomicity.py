"""Fault injection after executed item and resource writes, before commit."""

from acceptance.test_dispel_corruption import dispel as dispel
from sample_fixtures import published_payloads

import db_queries
import spell_casting


async def test_cast_failure_rolls_back_inventory_focus_and_events(dispel, monkeypatch):
    h = dispel
    owner = h.players[0]
    await h.add(owner)
    before = await h.snapshot(owner)
    memory = (h.sd.resonance.current, h.sd.concentration.spell_id)
    selector = await h.selector(owner)
    resolve = spell_casting._resolve_cast
    staged = False

    async def fail_before_commit(*args, **kwargs):
        nonlocal staged
        result = await resolve(*args, **kwargs)
        conn = kwargs["conn"]
        player = await db_queries.get_player(owner, conn=conn)
        rows = await db_queries.get_player_inventory(owner, conn=conn)
        assert player is not None and player["focus"]["current"] == 7
        assert [(r["tainted"], r["slot_info"]["quantity"]) for r in rows] == [(False, 5)]
        assert result.packet["purified"]["quantity"] == 3
        assert not published_payloads(h.sd.room)
        staged = True
        raise RuntimeError("dispel injected failure before commit")

    monkeypatch.setattr(spell_casting, "_resolve_cast", fail_before_commit)
    await h.cast(selector, error=True)
    assert staged
    assert await h.focus(owner) == 10 and await h.snapshot(owner) == before
    assert (h.sd.resonance.current, h.sd.concentration.spell_id) == memory
    assert not published_payloads(h.sd.room)
