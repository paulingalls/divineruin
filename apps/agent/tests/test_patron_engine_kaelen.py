import json
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import encounter, row
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
from sample_fixtures import make_context, make_mock_room

import db_mutations
from activate_tools import _activate_impl
from query_tools import _query_info_impl


async def iron_resolve_through_enemy_attack(world, archetype, before, damage, fires):
    dev_db_pool = world.pool
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


SCENARIOS = {
    "kaelen_iron_resolve": (
        "kaelen_gift:trigger_iron_resolve",
        iron_resolve_through_enemy_attack,
        [("bard", 30, 10, True), ("bard", 30, 5, False)],
    ),
    "kaelen_tempered_resolve": (
        "kaelen_gift:trigger_iron_resolve",
        iron_resolve_through_enemy_attack,
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
    ),
}
