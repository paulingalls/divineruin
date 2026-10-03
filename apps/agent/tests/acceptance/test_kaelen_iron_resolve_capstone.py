import json
from unittest.mock import patch

from acceptance._capstone_helpers import (
    _build_state,
    _d20,
    _damage_die,
    _declare_attacks,
    _enemy,
    _resolve_round,
    _start_combat,
)
from sample_fixtures import make_context, make_mock_room, published_payloads

import combat_turn
import conditions
import db
import db_mutations
import db_mutations_conditions
import event_types as E
from kaelen_gift import trigger_iron_resolve
from session_data import CombatParticipant, CombatState


def required_player(state: CombatState | None, pid: str) -> CombatParticipant:
    assert state is not None
    participant = state.get_participant(pid)
    assert participant is not None
    return participant


def ui_player(ctx, pid):
    updates = [p for p in published_payloads(ctx.userdata.room) if p["type"] == E.COMBAT_UI_UPDATE]
    assert updates
    assert updates[-1]["combatants"]
    return next(c for c in updates[-1]["combatants"] if c["id"] == pid)


async def test_phase_trigger_bonus_and_expiry(reset_db_pool):
    pool = await db.get_pool()
    totals = {}
    for patron in ["kaelen", "none"]:
        pid = f"cap_232_phase_{patron}"
        state = _build_state(f"combat_{pid}", pid, [_enemy("goblin_a", hp=100)])
        pc = required_player(state, pid)
        pc.hp_current, pc.hp_max = 10, 20
        ctx = make_context(pid, room=make_mock_room())
        ctx.userdata.party.primary.patron_id = patron
        try:
            await _start_combat(pool, pid, state, ctx)
            await pool.execute(
                "UPDATE players SET data = data || $2::jsonb WHERE player_id = $1",
                pid,
                json.dumps({"hp": {"current": 10, "max": 20}, "divine_favor": {"patron": patron}}),
            )
            await _declare_attacks(ctx, pid, "goblin_a", ["goblin_a"])
            with (
                patch("check_resolution.dice_roll", return_value=_d20(15)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(6)),
            ):
                result = await _resolve_round(ctx)
            assert result["packets"]
            enemy_packet = next(p for p in result["packets"] if p.get("attacker") == "Goblin A")
            live = required_player(ctx.userdata.combat_state, pid)
            assert live.hp_current == 4
            saved = await db_mutations.load_combat_state(state.combat_id, conn=pool)
            saved_pc = required_player(saved, pid)
            assert saved_pc.conditions == live.conditions
            assert saved_pc.iron_resolve_spent == (patron == "kaelen")
            if patron == "kaelen":
                assert enemy_packet["gift_triggered"] == "Iron Resolve"
                assert live.conditions[0]["duration"] == 1
                assert ui_player(ctx, pid)["conditions"][0]["type"] == "iron_resolve"
            else:
                assert "gift_triggered" not in enemy_packet
                assert live.conditions == []
            await combat_turn._declare_phase_impl(
                ctx,
                {
                    pid: {"type": "attack", "action": "Longsword", "target_id": "goblin_a"},
                    "goblin_a": {"type": "defend"},
                },
            )
            with (
                patch("check_resolution.dice_roll", return_value=_d20(15)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(6)),
            ):
                result = await _resolve_round(ctx)
            totals[patron] = next(p for p in result["packets"] if p.get("attacker") == "Kael")["attack_total"]
            assert required_player(ctx.userdata.combat_state, pid).conditions == []
            saved = await db_mutations.load_combat_state(state.combat_id, conn=pool)
            assert required_player(saved, pid).conditions == []
            assert ui_player(ctx, pid)["conditions"] == []
        finally:
            await db_mutations.delete_combat_state(state.combat_id, conn=pool)
    assert totals["kaelen"] - totals["none"] == 2


async def test_encounter_end_drops_gift_and_recharges(reset_db_pool):
    pool = await db.get_pool()
    pid = "cap_232_recharge"
    state = _build_state(f"combat_{pid}", pid, [_enemy("goblin_a", hp=1)])
    pc = required_player(state, pid)
    pc.hp_current, pc.hp_max = 4, 20
    pc.conditions = conditions.apply_condition([], "exhausted", source="march")
    ctx = make_context(pid, room=make_mock_room())
    ctx.userdata.party.primary.patron_id = "kaelen"
    assert trigger_iron_resolve(ctx.userdata, pc, 10)
    try:
        await _start_combat(pool, pid, state, ctx)
        await _declare_attacks(ctx, pid, "goblin_a", ["goblin_a"])
        with (
            patch("check_resolution.dice_roll", return_value=_d20(20)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(6)),
        ):
            result = await _resolve_round(ctx)
        assert isinstance(result, tuple)
        assert ctx.userdata.combat_state is None
        assert await db_mutations.load_combat_state(state.combat_id, conn=pool) is None
        stored = await db_mutations_conditions.read_player_conditions(pid, conn=pool)
        assert [c["type"] for c in stored] == ["exhausted"]
        new_state = _build_state(f"combat_{pid}_next", pid, [_enemy("goblin_a", hp=100)])
        await _start_combat(pool, pid, new_state, ctx)
        fresh = required_player(ctx.userdata.combat_state, pid)
        assert not fresh.iron_resolve_spent
        assert fresh.conditions == []
        fresh.hp_current, fresh.hp_max = 4, 20
        assert trigger_iron_resolve(ctx.userdata, fresh, 10) == "Iron Resolve"
        await db_mutations.delete_combat_state(new_state.combat_id, conn=pool)
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
