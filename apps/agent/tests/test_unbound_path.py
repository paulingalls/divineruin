"""Unbound discovery, activation and Echo behavior through production routes."""

import json
from functools import partial
from typing import cast as type_cast
from unittest.mock import MagicMock, patch

import pytest
from _unbound_path_fixtures import MilestoneWalk, cast, encounter, phase, push, row
from _unbound_path_fixtures import world as world
from livekit.agents.llm import ToolError
from patron_ability_walk import AbilityWalk
from sample_fixtures import published_payloads

from query_patron import query_patron
from query_tools import _query_info_impl


@pytest.mark.parametrize("bonus,state", [(0, "overreach"), (1, "flickering")])
async def test_guest_discovery_uses_persisted_resonance_and_bypasses_gods(dev_db_pool, bonus, state):
    async with AbilityWalk(dev_db_pool) as w, AbilityWalk(dev_db_pool) as guest:
        await w.patch(divine_favor={"patron": "kaelen", "level": 40, "max": 100}, resonance={"current": 2})
        await guest.patch(
            divine_favor={"patron": "none", "level": 0, "max": 100},
            unbound_autonomy={"level": 75, "max": 100, "tier": "Sovereign"},
            resonance={"current": 9, "flickering_bonus": bonus},
        )
        guest.sd.party.primary.resonance.current = 1
        w.sd.party.members.append(guest.sd.party.primary)

        def forbidden_catalog():
            raise AssertionError("Unbound read gods")

        with patch("query_patron.query_patron", partial(query_patron, gods_loader=forbidden_catalog)):
            packet = await w.command("query_info", {"kind": "patron"}, actor=guest.player)
        assert packet["state"] == "Unbound"
        assert packet["autonomy"]["tier"] == "Sovereign"
        assert packet["resonance"] == {"current": 9, "state": state}
        assert packet["abilities"] == []
        assert {c["id"] for c in packet["capabilities"]} == {
            "unbound_veil_clarity",
            "unbound_raw_channeling",
            "unbound_veil_mastery",
        }
        assert "activate" in str(packet["capabilities"])
        follower = await w.command("query_info", {"kind": "patron"})
        assert follower["patron_id"] == "kaelen"
        assert follower["resonance"] == {"state": "stable"}


async def test_raw_channeling_preserves_action_and_reaction(dev_db_pool):
    import db_mutations
    import reaction_spend

    async with MilestoneWalk(dev_db_pool) as w:
        await w.patch(
            **{
                "class": "skirmisher",
                "stamina": {"current": 100, "max": 100},
                "divine_favor": {"patron": "none", "level": 0, "max": 100},
                "resonance": {"current": 3},
            }
        )
        state = await w.encounter()
        state.current_turn_index = state.initiative_order.index(w.player)
        actor = state.get_participant(w.player)
        assert actor is not None
        actor.has_reaction_ability = True
        actor.reaction_ids = ["skirmisher_sidestep"]
        enemy = state.get_participant("enemy")
        assert enemy is not None
        enemy.action_pool = [
            {"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "attack_bonus": 4, "range": "melee"}
        ]
        state.reactions_available[w.player] = reaction_spend.unspent()
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        before = state.to_dict()
        query = await w.command("query_info", {"kind": "patron"})
        token = next(c["id"] for c in query["capabilities"] if c["name"] == "Raw Channeling")
        result = await w.use(token)
        assert result["resonance_added"] == 3
        assert (await w.row())["resonance"]["current"] == 6
        assert w.sd.party.primary.unbound_raw_channeling_used
        assert w.sd.combat_state is not None
        assert w.sd.combat_state.to_dict() == before
        assert not reaction_spend.is_spent(w.sd.combat_state.reactions_available[w.player])
        assert "spent this encounter" in await w.use(token, error=True)
        assert (await w.row())["resonance"]["current"] == 6
        assert w.sd.combat_state.to_dict() == before
        result = await w.command(
            "declare_phase",
            {
                "declarations": [
                    {"reshape": [], "kind": "defend", "actor_id": w.player},
                    {
                        "reshape": [],
                        "quick_fingers_mode": "",
                        "quick_fingers_item": "",
                        "kind": "attack",
                        "actor_id": "enemy",
                        "action": "Scimitar",
                        "target_id": w.player,
                        "held_item_id": "",
                        "rider": "",
                    },
                ]
            },
        )
        assert w.player in result["accepted_actors"]
        assert w.sd.combat_state is not None
        assert w.sd.combat_state.pending_declarations[w.player] == {"type": "defend"}
        assert w.sd.combat_state.round_number == state.round_number
        for _ in range(8):
            result = await w.command("resolve_phase", {})
            waiting = result["next"]["waiting_on"]
            if waiting and any(r["id"] == "skirmisher_sidestep" for r in waiting["reactions"]):
                break
        else:
            pytest.fail(f"No Sidestep offered: {result}")
        assert waiting["target_id"] == w.player
        await w.use(next(r["id"] for r in waiting["reactions"] if r["id"] == "skirmisher_sidestep"))
        assert w.sd.combat_state is not None
        spend = w.sd.combat_state.reactions_available[w.player]
        assert reaction_spend.is_spent(spend)
        assert spend["ability_id"] == "skirmisher_sidestep"
        assert spend["window_id"] == waiting["window_id"]
        saved = await db_mutations.load_combat_state(state.combat_id)
        assert saved is not None
        assert saved.reactions_available[w.player] == spend


async def test_unbound_refuses_all_patron_abilities(dev_db_pool):
    from _gods_content import load_gods

    catalog = load_gods()
    assert len(catalog) == 10
    tiers, gifts = set(), set()
    for god in catalog:
        assert set(god["layer_3_tier_abilities"]) == {"acknowledged", "devoted", "exalted"}
        tiers.update(a["id"] for a in god["layer_3_tier_abilities"].values())
        gifts.add(god["layer_1_gift"]["id"])
    assert len(tiers) == 30 and len(gifts) == 10 and len(tiers | gifts) == 40
    assert all(tiers | gifts)
    async with MilestoneWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": "none", "level": 0, "max": 100})
        await w.encounter()
        assert await w.abilities() == []
        before = await w.row()
        for token in sorted(tiers | gifts):
            try:
                refusal = await w.use(token, error=True)
            except AssertionError as error:
                raise AssertionError(f"{token}: {error}") from error
            expected = (
                "offer_id"
                if token in ("zhael_fates_thread", "zhael_lucky")
                else "Unbound"
                if token in tiers or token == "valdris_weight_of_truth"
                else "requires an active Veythar gift"
                if token == "veythar_lorekeepers_insight"
                else "requires an active Syrath gift"
                if token == "syrath_shadow_veil"
                else "not an activatable capability"
            )
            assert expected in refusal, (token, refusal)
        assert await w.row() == before
        assert await w.abilities() == []


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


async def test_follower_cannot_push(world):
    w = world
    await w.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{divine_favor,patron}', '\"veythar\"') WHERE player_id=$1", w.ids[1]
    )
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
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


async def test_patron_query_reports_actor_alone_bonus_without_abilities(world):
    from test_aelora_gift import _live_party

    from session_data import CompanionState

    w = world

    async def query(applies):
        packet = json.loads(await _query_info_impl(w.ctx, "patron"))
        assert packet["alone_bonus"] == {
            "amount": 1,
            "description": "+1 to all skill checks when no ally is present.",
            "applies_now": applies,
        }
        assert packet["abilities"] == [] and packet["synergy"] is None
        assert {c["id"] for c in packet["capabilities"]} == {
            "unbound_veil_clarity",
            "unbound_raw_channeling",
            "unbound_veil_mastery",
        }

    await query(True)
    w.ctx.userdata.companion = CompanionState(id="ally", name="Ally", is_present=True)
    await query(False)
    w.ctx.userdata.companion.is_present = False
    await query(True)
    lifecycle = _live_party(w.ctx.userdata, *w.ids)
    handlers = dict(call.args for call in type_cast(MagicMock, lifecycle.room).on.call_args_list)
    try:
        await query(False)
        handlers["participant_disconnected"](lifecycle.room.remote_participants[w.ids[1]])
        await query(True)
        handlers["participant_connected"](lifecycle.room.remote_participants[w.ids[1]])
        handlers["participant_disconnected"](lifecycle.room.remote_participants[w.ids[0]])
        with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
            await query(True)
    finally:
        await lifecycle.aclose()
