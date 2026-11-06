"""Unbound discovery, activation and Echo behavior through production routes."""

import json
from functools import partial
from unittest.mock import patch

import pytest
from _unbound_path_fixtures import cast, encounter, phase, push, row
from _unbound_path_fixtures import world as world
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads

from query_tools import _query_info_impl, _query_patron_impl


@pytest.mark.parametrize("bonus,state", [(0, "overreach"), (1, "flickering")])
async def test_guest_discovery_uses_persisted_resonance_and_bypasses_gods(world, bonus, state):
    w = world
    w.ctx.userdata.party.members[1].resonance.current = 1
    await w.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{resonance,current}', '2') WHERE player_id=$1", w.ids[0]
    )
    await w.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{resonance,flickering_bonus}', $2::jsonb) WHERE player_id=$1",
        w.ids[1],
        json.dumps(bonus),
    )

    def forbidden_catalog():
        raise AssertionError("Unbound read gods")

    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        with patch("query_tools._query_patron_impl", partial(_query_patron_impl, gods_loader=forbidden_catalog)):
            packet = json.loads(await _query_info_impl(w.ctx, "patron"))
    assert packet["state"] == "Unbound"
    assert packet["resonance"] == {"current": 9, "state": state}
    assert {c["id"] for c in packet["capabilities"]} == {
        "unbound_veil_clarity",
        "unbound_raw_channeling",
        "unbound_veil_mastery",
    }
    assert "activate" in str(packet["capabilities"])


async def test_guest_push_and_first_echo_are_independent_member_uses(world):
    w = world
    encounter(w)
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        assert (await push(w))["resonance_added"] == 3
        assert (await row(w))["resonance"]["current"] == 12
        w.ctx.userdata.combat_state = None
        assert (await cast(w))["hollow_echo"]["veil_mastery"] is True
    host, guest = w.ctx.userdata.party.members
    assert not host.unbound_veil_mastery_used and guest.unbound_veil_mastery_used
    assert host.resonance.current == 9 and guest.resonance.current == 12
    echoes = [p for p in published_payloads(w.ctx.userdata.room) if p["type"] == "hollow_echo_result"]
    assert [p["band"] for p in echoes] == ["nothing"]


async def test_follower_sees_state_only_and_cannot_push(world):
    w = world
    await w.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{divine_favor,patron}', '\"veythar\"') WHERE player_id=$1", w.ids[1]
    )
    await w.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{resonance,flickering_bonus}', '1') WHERE player_id=$1", w.ids[1]
    )
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        packet = json.loads(await _query_info_impl(w.ctx, "patron"))
        assert packet["resonance"] == {"state": "flickering"}
        assert "capabilities" not in packet
        encounter(w)
        with pytest.raises(ToolError, match="Unbound"):
            await push(w)
    assert not w.ctx.userdata.party.members[1].unbound_raw_channeling_used


async def test_push_requires_encounter_participation_and_ignores_ward_generation(world):
    w = world
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        with pytest.raises(ToolError, match="encounter"):
            await push(w)
        encounter(w)
        state = w.ctx.userdata.combat_state
        state.participants.pop()
        with pytest.raises(ToolError, match="participation"):
            await push(w)
        encounter(w)
        w.ctx.userdata.combat_state.veil_ward = {"source": "cleric"}
        await w.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
            w.ids[1],
            json.dumps({"race": "thessyn", "resonance": {"current": 7, "flickering_bonus": 1}}),
        )
        packet = json.loads(await _query_info_impl(w.ctx, "patron"))
        token = next(c["id"] for c in packet["capabilities"] if c["name"] == "Raw Channeling")
        assert token == "unbound_raw_channeling"
        assert await push(w, token=token) == {"resonance_added": 3, "state": "overreach"}
    assert (await row(w))["resonance"]["current"] == 10
    events = published_payloads(w.ctx.userdata.room)
    assert events[-1] == {"type": "resonance_changed", "state": "overreach", "caster_id": w.ids[1]}


@pytest.mark.parametrize("patron,first_roll", [(None, 1), ("none", 20)])
async def test_mastery_lifetime_natural_nothing_and_zero_generation(world, patron, first_roll):
    from sample_fixtures import make_context

    w = world
    await w.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{divine_favor,patron}', $2::jsonb) WHERE player_id=$1",
        w.ids[1],
        json.dumps(patron),
    )
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        member = w.ctx.userdata.party.members[1]
        member.resonance.current = 8
        await w.pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{resonance,current}', '8') WHERE player_id=$1", w.ids[1]
        )
        assert "hollow_echo" not in await cast(w)
        assert not member.unbound_veil_mastery_used
        member.resonance.current = 9
        await w.pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{resonance,current}', '9') WHERE player_id=$1", w.ids[1]
        )
        first = await cast(w, roll=first_roll)
        assert first["resonance_generated"] == 0
        assert first["hollow_echo"]["veil_mastery"]
        assert member.unbound_veil_mastery_used
        assert (await cast(w))["hollow_echo"]["band"] == "breach"
        assert w.ctx.userdata.party.members[1] is member
    assert (await cast(w))["hollow_echo"]["band"] == "nothing"
    w.ctx = make_context(player_id=w.ids[0], party_member_ids=[w.ids[1]])
    w.ctx.userdata.party.members[1].resonance.current = 9
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 5, lambda *_: None):
        assert (await cast(w))["hollow_echo"]["veil_mastery"]


async def test_unaffordable_cast_preserves_mastery(world):
    w = world
    await w.pool.execute("UPDATE players SET data=jsonb_set(data, '{focus,current}', '0') WHERE player_id=$1", w.ids[1])
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        with pytest.raises(ToolError):
            await cast(w, sid="arcane_fireball")
    assert not w.ctx.userdata.party.members[1].unbound_veil_mastery_used
    assert (await row(w))["resonance"]["current"] == 9
    assert not published_payloads(w.ctx.userdata.room)


async def test_combat_cast_commits_mastery_for_declaring_member(world):
    w = world
    encounter(w)
    result = await phase(w)
    packets = [p["cast"] for p in result["packets"] if p["actor_id"] == w.ids[1]]
    assert packets[0]["hollow_echo"]["veil_mastery"]
    echoes = [p for p in published_payloads(w.ctx.userdata.room) if p["type"] == "hollow_echo_result"]
    assert echoes == [{"type": "hollow_echo_result", "band": "nothing"}]
    host, guest = w.ctx.userdata.party.members
    assert guest.unbound_veil_mastery_used and not host.unbound_veil_mastery_used
    assert guest.resonance.current == (await row(w))["resonance"]["current"]
    assert (await row(w))["focus"]["current"] < 100
    w.ctx.userdata.combat_state = None
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        assert (await cast(w))["hollow_echo"]["band"] == "breach"


async def test_concurrent_exploration_casts_cannot_both_claim_mastery(world):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    w = world
    second_rolled = asyncio.Event()
    committed = asyncio.Event()
    count = 0

    @asynccontextmanager
    async def transaction():
        nonlocal count
        count += 1
        first = count == 1
        async with w.db.transaction() as conn:
            yield conn
        if first:
            committed.set()
            try:
                await asyncio.wait_for(second_rolled.wait(), 0.2)
            except TimeoutError:
                pass

    def roll(_):
        if committed.is_set():
            second_rolled.set()
        return SimpleNamespace(total=1)

    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        results = await asyncio.gather(
            *[cast(w, database=SimpleNamespace(transaction=transaction), die=MagicMock(roll=roll)) for _ in range(2)]
        )
    assert [p["hollow_echo"]["band"] for p in results] == ["nothing", "breach"]


async def test_encounter_end_and_start_refill_only_raw_channeling(world):
    from unittest.mock import AsyncMock

    from _combat_end_fixtures import combat_end_mutations
    from combat.test_start_combat import SAMPLE_PLAYER, _make_start_combat_mocks

    from combat_end import _end_combat_impl
    from combat_init import _start_combat_impl

    w = world
    encounter(w)
    members = w.ctx.userdata.party.members
    for member in members:
        with w.ctx.userdata._bind_authenticated_actor(member.player_id, 4, lambda *_: None):
            await push(w)
        member.unbound_veil_mastery_used = True
    await _end_combat_impl(w.ctx, "fled", mutations=combat_end_mutations(), db_mod=w.db)
    assert all(not m.unbound_raw_channeling_used and m.unbound_veil_mastery_used for m in members)
    # Start must reset independently of end, including encounters entered with retained flags.
    for member in members:
        member.unbound_raw_channeling_used = True
    mutations, queries, content = _make_start_combat_mocks()
    queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "player_id": w.ids[0]})
    queries.get_players_for_update = AsyncMock(return_value={w.ids[1]: {**SAMPLE_PLAYER, "player_id": w.ids[1]}})
    await _start_combat_impl(
        w.ctx, "goblin_patrol", "A patrol.", mutations=mutations, queries=queries, content=content, db_mod=w.db
    )
    assert all(not m.unbound_raw_channeling_used and m.unbound_veil_mastery_used for m in members)
    for member in members:
        with w.ctx.userdata._bind_authenticated_actor(member.player_id, 4, lambda *_: None):
            await push(w)
    assert all(m.unbound_raw_channeling_used for m in members)
