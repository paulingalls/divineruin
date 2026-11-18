"""Numeric patron clauses at the check, activation and combat boundaries."""

import json
from typing import cast as type_cast
from unittest.mock import MagicMock, patch

import pytest
from _unbound_path_fixtures import cast, encounter, phase, row
from _unbound_path_fixtures import world as world
from acceptance._capstone_helpers import (
    _build_state,
    _d20,
    _damage_die,
    _declare_attacks,
    _enemy,
    _resolve_round,
    _start_combat,
)
from acceptance.test_kaelen_iron_resolve_capstone import required_player, ui_player
from sample_fixtures import make_context, make_mock_room, published_payloads
from test_aelora_gift import _live_party
from test_unbound_alone_bonus import check

import db_mutations
from activate_tools import _activate_impl
from query_tools import _query_info_impl
from session_data import CompanionState


async def configure(w, patron, archetype, *, index=0, **fields):
    await w.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        w.ids[index],
        json.dumps(
            {
                "player_id": w.ids[index],
                "class": archetype,
                "divine_favor": {"patron": patron, "level": 40, "max": 100},
                **fields,
            }
        ),
    )
    w.ctx.userdata.party.members[index].patron_id = patron


@pytest.mark.parametrize("archetype", ["artificer", "bard", "diplomat", "warrior"])
async def test_bond_counts_live_allies(world, archetype):
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


@pytest.mark.parametrize(
    "archetype,skill,bonus",
    [(a, s, 3) for a in ("seeker", "spy") for s in ("investigation", "perception")]
    + [("bard", "investigation", 0), ("seeker", "athletics", 0)],
)
async def test_uncharted_senses_uses_map_history(world, archetype, skill, bonus):
    w = world
    await configure(w, "nythera", archetype)
    await w.pool.execute(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,$3::jsonb)",
        w.ids[0],
        w.ctx.userdata.location_id,
        json.dumps({"revisited": False}),
    )
    assert (await check(w, skill))["total"] == 11 + bonus
    await w.pool.execute(
        "UPDATE player_map_progress SET data='{" + '"revisited":true' + "}' WHERE player_id=$1",
        w.ids[0],
    )
    assert (await check(w, skill))["total"] == 11


@pytest.mark.parametrize("archetype,expected,calls", [("druid", 17, 2), ("beastcaller", 17, 2), ("bard", 4, 1)])
async def test_uncharted_handling_rolls_advantage(world, archetype, expected, calls):
    from check_tools import _check_impl

    w = world
    await configure(w, "nythera", archetype)
    await w.pool.execute(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,'{}')",
        w.ids[0],
        w.ctx.userdata.location_id,
    )
    with patch("check_resolution.dice_roll", side_effect=[_d20(4), _d20(17)]) as dice:
        packet = json.loads(await _check_impl(w.ctx, "skill", skill="animal_handling", difficulty="moderate"))
    assert packet["roll"] == expected and dice.call_count == calls


@pytest.mark.parametrize(
    "archetype,hidden,expected", [("mage", True, 0), ("seeker", True, 0), ("bard", True, 1), ("mage", False, 3)]
)
async def test_hidden_casting_composes_and_persists(world, archetype, hidden, expected):
    w = world
    await configure(w, "syrath", archetype, flags={"concealed": hidden})
    packet = await cast(w, sid="arcane_fireball")
    assert packet["resonance_generated"] == expected
    assert (await row(w, 0))["resonance"]["current"] == (9 if expected == 0 else 7 + expected)
    assert w.ctx.userdata.party.primary.resonance.current == (9 if expected == 0 else 7 + expected)


async def test_hidden_guest_declared_cast(world):
    w = world
    await configure(w, "syrath", "seeker", index=1, flags={"concealed": True})
    encounter(w)
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        packet = await phase(w)
    assert packet["packets"]
    assert (await row(w))["resonance"]["current"] == 9
    assert (await row(w, 0))["resonance"]["current"] == 9


@pytest.mark.parametrize(
    "archetype,before,damage,fires",
    [
        ("warrior", 50, 15, True),
        ("guardian", 50, 15, True),
        ("skirmisher", 50, 15, True),
        ("bard", 50, 15, False),
        ("warrior", 40, 5, True),
        ("warrior", 50, 10, False),
        ("warrior", 35, 5, False),
        ("warrior", 50, 50, False),
    ],
)
async def test_iron_resolve_through_enemy_attack(dev_db_pool, archetype, before, damage, fires):
    pid = f"synergy_iron_{archetype}_{before}_{damage}"
    state = _build_state(f"combat_{pid}", pid, [_enemy("goblin_a", hp=100)])
    pc = required_player(state, pid)
    pc.hp_current, pc.hp_max = before, 100
    ctx = make_context(pid, room=make_mock_room())
    ctx.userdata.party.primary.patron_id = "kaelen"
    try:
        await _start_combat(dev_db_pool, pid, state, ctx)
        await dev_db_pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
            pid,
            json.dumps(
                {"class": archetype, "hp": {"current": before, "max": 100}, "divine_favor": {"patron": "kaelen"}}
            ),
        )
        await _declare_attacks(ctx, pid, "goblin_a", ["goblin_a"])
        with (
            patch("check_resolution.dice_roll", return_value=_d20(15)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(damage)),
        ):
            result = await _resolve_round(ctx)
        packet = next(p for p in result["packets"] if p.get("attacker") == "Goblin A")
        live = required_player(ctx.userdata.combat_state, pid)
        assert live.hp_current == before - damage
        assert (packet.get("gift_triggered") == "Iron Resolve") is fires
        assert live.iron_resolve_spent is fires
        saved = await db_mutations.load_combat_state(state.combat_id, conn=dev_db_pool)
        assert required_player(saved, pid).iron_resolve_spent is fires
        assert [c["type"] for c in ui_player(ctx, pid)["conditions"]] == [c["type"] for c in live.conditions]
        if fires:
            assert live.conditions[0]["type"] == "iron_resolve"
            assert live.conditions[0]["duration"] == 1
        if (archetype, before, damage) == ("warrior", 50, 15):
            ctx.userdata.combat_state = saved
            required_player(saved, pid).hp_current = 50
            await db_mutations.update_player_hp(pid, 50, conn=dev_db_pool)
            await _declare_attacks(ctx, pid, "goblin_a", ["goblin_a"])
            with (
                patch("check_resolution.dice_roll", return_value=_d20(15)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(damage)),
            ):
                again = await _resolve_round(ctx)
            enemy = next(p for p in again["packets"] if p.get("attacker") == "Goblin A")
            assert "gift_triggered" not in enemy
            assert required_player(ctx.userdata.combat_state, pid).conditions == []
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=dev_db_pool)
        await dev_db_pool.execute("DELETE FROM players WHERE player_id=$1", pid)


@pytest.mark.parametrize("archetype,fires", [("warrior", True), ("bard", False)])
async def test_inner_fire_uses_locked_archetype(world, archetype, fires):
    w = world
    await configure(w, "kaelen", archetype, race="draethar", hp={"current": 10, "max": 20})
    encounter(w)
    w.ctx.userdata.combat_state.participants[0].hp_current = 10
    import draethar_inner_fire

    with (
        patch.object(draethar_inner_fire.db, "transaction", w.db.transaction),
        patch("draethar_inner_fire.dice.roll", return_value=_damage_die(3)),
    ):
        packet = json.loads(await _activate_impl(w.ctx, "draethar_inner_fire"))
    assert (packet.get("gift_triggered") == "Iron Resolve") is fires
    assert (await row(w, 0))["hp"]["current"] == 7


async def test_guardian_reports_active_and_pending_siblings(world):
    await configure(world, "kaelen", "guardian")
    packet = json.loads(await _query_info_impl(world.ctx, "patron"))
    clauses = packet["synergy"]["clauses"]
    assert clauses[0]["status"] == "active"
    assert clauses[0]["implementation_id"] == "kaelen_tempered_resolve"
    assert clauses[1]["status"] == "pending"


@pytest.mark.parametrize("ward,corruption,expected", [(False, 0, 1), (True, 1, 0)])
async def test_hidden_casting_positive_generation(world, ward, corruption, expected):
    w = world
    await configure(w, "syrath", "mage", level=20, flags={"concealed": True})
    w.ctx.userdata.party.primary.corruption_level = corruption
    packet = await cast(w, sid="arcane_wall_of_force", ward=ward)
    assert packet["resonance_generated"] == expected
    assert (await row(w, 0))["resonance"]["current"] == (8 if expected else 9)


async def test_guest_damage_reads_latest_target_class(world):
    import combat_turn

    w = world
    for host_class, guest_class, fires in [("bard", "warrior", True), ("warrior", "bard", False)]:
        await configure(w, "kaelen", host_class)
        await configure(w, "kaelen", guest_class, index=1)
        encounter(w)
        state = w.ctx.userdata.combat_state
        state.combat_id = "synergy_guest_" + guest_class
        guest = state.get_participant(w.ids[1])
        guest.hp_current, guest.hp_max = 50, 100
        state.participants.append(_enemy("goblin_a", hp=100))
        state.initiative_order = [*w.ids, "goblin_a"]
        from voice_condition_fixtures import place_actors

        place_actors(state)
        try:
            await combat_turn._declare_phase_impl(
                w.ctx,
                {
                    w.ids[0]: {"type": "defend"},
                    w.ids[1]: {"type": "defend"},
                    "goblin_a": {"type": "attack", "action": "Scimitar", "target_id": w.ids[1]},
                },
            )
            with (
                patch("check_resolution.dice_roll", return_value=_d20(15)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(15)),
            ):
                await _resolve_round(w.ctx)
            live = required_player(w.ctx.userdata.combat_state, w.ids[1])
            assert live.hp_current == 35 and live.iron_resolve_spent is fires
            assert not required_player(w.ctx.userdata.combat_state, w.ids[0]).iron_resolve_spent
        finally:
            await db_mutations.delete_combat_state(state.combat_id, conn=w.pool)


async def test_guest_discovery_and_reroll_use_first_stay(world):
    from unittest.mock import AsyncMock

    import db_mutations_conditions
    import db_mutations_skill_advancement
    import db_queries
    from check_skill import _check_skill_run
    from check_tools import _check_impl
    from skill_check_effects import SkillCheckEffects

    w = world
    await configure(w, "nythera", "spy", index=1)
    await w.pool.execute(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,'{}')",
        w.ids[1],
        w.ctx.userdata.location_id,
    )
    with (
        w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None),
        patch("check_resolution.dice_roll", return_value=_d20(11)),
    ):
        packet = json.loads(
            await _check_impl(
                w.ctx,
                "discover",
                skill="perception",
                content=MagicMock(
                    get_item=AsyncMock(return_value=None),
                    get_location=AsyncMock(return_value={"hidden_elements": []}),
                ),
            )
        )
        assert packet["total"] == 14
        async with w.db.transaction() as conn:
            player = await db_queries.get_player(w.ids[1], conn=conn, for_update=True)
            effects = SkillCheckEffects()
            packet = json.loads(
                await _check_skill_run(
                    w.ctx,
                    "investigation",
                    "moderate",
                    "reroll",
                    hearing_only=False,
                    queries=db_queries,
                    mutations=db_mutations_skill_advancement,
                    db_mod=w.db,
                    conditions_mutations=db_mutations_conditions,
                    effects=effects,
                    conn=conn,
                    locked_player=player,
                    reroll_dc=12,
                )
            )
        assert packet["total"] == 14 and effects.events[0][1]["total"] == 14


@pytest.mark.parametrize("first_stay,bonus", [(True, 3), (False, 0)])
async def test_choir_search_carries_uncharted_senses(first_stay, bonus, mock_combat_agent_factory):
    import combat_packet
    from combat_phase import ResolutionPacket
    from declarations import resolve_declaration
    from tests.combat.test_choir_encounter import start_choir

    ctx, _, mutations, queries = await start_choir()
    state = ctx.userdata.combat_state
    actor = state.get_participant("player_1")
    queries.get_player.return_value = {
        **queries.get_player.return_value,
        "class": "seeker",
        "divine_favor": {"patron": "nythera", "level": 40, "max": 100},
    }
    decl = resolve_declaration({"type": "interact", "action": "choir_search_perception", "target_id": "choir_sound"})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(10)),
        patch("choir_encounter.check_first_stay", return_value=first_stay),
    ):
        packet = await combat_packet._resolve_one_packet(
            ctx.userdata,
            state,
            ResolutionPacket(actor_id=actor.id, declaration=decl, initiative=actor.initiative),
            mutations=mutations,
            queries=queries,
            resolver=None,
            concentration_break_mod=None,
        )
    assert packet["total"] == 13 + bonus
    assert (packet.get("gift_name") == "Uncharted Senses") is first_stay
