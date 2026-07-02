"""Multi-player combat phase-loop tests (M14 story-004).

The phase loop resolves N player declarations per phase: each player's ability Focus is
pre-validated against its OWN for_update row, each cast resolves against the declaring
member's OWN caster pool, and the WRAP Resonance decay sheds from EACH member's own pool
(once per phase, never shared, never double). Solo (1-member) parity is guarded by the
existing tests/combat/test_phase_loop.py — here every party has ≥2 members.

The casts themselves are mocked (cast_resolver._resolve_cast); the wiring/identity/decay is
under test, not the spell internals (covered by tests/test_spell_casting.py).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver, _fake_db_mod
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

from combat_turn import _resolve_phase_impl
from session_data import CombatParticipant, CombatState
from spell_casting import _UNCHANGED, CastResult


def _mp_state(*, player_ids=("player_1", "player_2"), enemy_hp=20):
    """A 2-player + 1-enemy CombatState parked at RESOLUTION: each player declares an ABILITY and
    the enemy attacks player_1. Players get descending initiative (declaration order is initiative),
    the enemy resolves last so combat continues this phase."""
    participants = []
    initiative = 20
    for pid in player_ids:
        participants.append(
            CombatParticipant(
                id=pid,
                name=pid,
                type="player",
                initiative=initiative,
                hp_current=25,
                hp_max=25,
                ac=14,
            )
        )
        initiative -= 5
    participants.append(
        CombatParticipant(
            id="goblin_1",
            name="Goblin",
            type="enemy",
            initiative=1,
            hp_current=enemy_hp,
            hp_max=enemy_hp,
            ac=13,
            action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}],
            xp_value=50,
        )
    )
    pending = {pid: {"type": "ability", "action": "arcane_bolt"} for pid in player_ids}
    pending["goblin_1"] = {"type": "attack", "action": "Scimitar", "target_id": player_ids[0]}
    return CombatState(
        combat_id="combat_mp",
        participants=participants,
        initiative_order=[*player_ids, "goblin_1"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="resolution",
        pending_declarations=pending,
    )


def _resonance_deps():
    res_mut = MagicMock()
    res_mut.update_player_resonance = AsyncMock()
    res_evt = MagicMock()
    res_evt.publish_resonance_changed = AsyncMock()
    return {"resonance_mutations": res_mut, "resonance_events_mod": res_evt}


def _resolve_deps(*, focus_by_id=None):
    """DI bundle for _resolve_phase_impl with a per-actor get_player (each member locks its OWN row).
    ``focus_by_id`` overrides a member's Focus so the AC1 negative can starve one player."""
    focus_by_id = focus_by_id or {}

    async def _get_player(pid, conn=None, for_update=False):
        return {"player_id": pid, "focus": {"current": focus_by_id.get(pid, 10), "max": 10}}

    queries = MagicMock()
    queries.get_player = AsyncMock(side_effect=_get_player)
    queries.get_player_inventory = AsyncMock(return_value=[])
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
    mutations = MagicMock()
    mutations.save_combat_state = AsyncMock()
    mutations.update_player_hp = AsyncMock()
    mutations.delete_combat_state = AsyncMock()
    return {
        "mutations": mutations,
        "queries": queries,
        "resolver": _damage_resolver(3),
        "concentration_break_mod": break_mod,
        "db_mod": _fake_db_mod(),
    }


def _cast_resolver_recording(new_resonance_by_id=None):
    """A cast_resolver whose _resolve_cast records the caster it was handed per call and returns a
    CastResult carrying that caster's new_resonance (from ``new_resonance_by_id``, default None)."""
    new_resonance_by_id = new_resonance_by_id or {}
    seen_casters = []

    async def _resolve(session, spell_id, *, caster=None, **kwargs):
        seen_casters.append(caster)
        return CastResult(
            packet={"effect": "A bolt of force.", "state": "flickering"},
            new_resonance=new_resonance_by_id.get(caster.player_id if caster else None),
            concentration_spell_id=_UNCHANGED,
            generated=6,
            events=[],
        )

    mod = MagicMock()
    mod._resolve_cast = AsyncMock(side_effect=_resolve)
    mod._gate_spell = MagicMock()  # affordable by default; overridden per-test for the negative
    return mod, seen_casters


class TestMultiplayerPrevalidation:
    """AC1: two players each declare an ability → each is prevalidated against its OWN for_update
    row (get_player once per id), both resolve, and _resolve_cast is handed the matching caster."""

    @pytest.mark.asyncio
    async def test_each_player_ability_prevalidated_and_resolved_against_own_caster(self):
        ctx = make_context(party_member_ids=["player_2"])
        ctx.userdata.combat_state = _mp_state()
        deps = _resolve_deps()
        res = _resonance_deps()
        cast_resolver, seen_casters = _cast_resolver_recording()

        raw = await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)

        assert isinstance(raw, str)  # combat continues -> JSON, not the end-of-combat tuple
        packets = {p["actor_id"]: p for p in json.loads(raw)["packets"]}

        # Each player's OWN row was locked for_update, once per id.
        locked = [c.args[0] for c in deps["queries"].get_player.await_args_list if c.kwargs.get("for_update")]
        assert sorted(locked) == ["player_1", "player_2"]
        # Both abilities resolved, each cast handed its matching caster (its own pool).
        assert packets["player_1"]["resolved"] is True
        assert packets["player_2"]["resolved"] is True
        assert sorted(c.player_id for c in seen_casters) == ["player_1", "player_2"]

    @pytest.mark.asyncio
    async def test_unaffordable_second_player_raises_before_any_write(self):
        # NEGATIVE: player_2 cannot afford its ability → the pre-validation fails loud BEFORE the
        # resolution loop, so no cast runs and player_1 is never written.
        ctx = make_context(party_member_ids=["player_2"])
        ctx.userdata.combat_state = _mp_state()
        deps = _resolve_deps(focus_by_id={"player_2": 0})
        res = _resonance_deps()
        cast_resolver, seen_casters = _cast_resolver_recording()

        # _gate_spell raises only for the starved player_2 row (real gate discipline).
        def _gate(player, action, **kwargs):
            if (player.get("focus") or {}).get("current", 0) <= 0:
                raise ToolError("Not enough Focus")

        cast_resolver._gate_spell = MagicMock(side_effect=_gate)

        with pytest.raises(ToolError, match="Focus"):
            await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)

        # No packet resolved, no writes, player_1 untouched (the loop never ran).
        cast_resolver._resolve_cast.assert_not_called()
        assert seen_casters == []
        deps["mutations"].save_combat_state.assert_not_called()
        deps["mutations"].update_player_hp.assert_not_called()
        res["resonance_mutations"].update_player_resonance.assert_not_called()
