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


def _mp_state(*, player_ids=("player_1", "player_2"), enemy_hp=20, attacks_only=False):
    """A 2-player + 1-enemy CombatState parked at RESOLUTION: each player declares an ABILITY (or an
    ATTACK when ``attacks_only``) and the enemy attacks player_1. Players get descending initiative
    (declaration order is initiative), the enemy resolves last so combat continues this phase."""
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
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
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
    if attacks_only:
        pending = {pid: {"type": "attack", "action": "Longsword", "target_id": "goblin_1"} for pid in player_ids}
    else:
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


def _member(ctx, pid):
    """Fetch a party member (asserting it exists) so its resonance track can be read/written."""
    m = ctx.userdata.party.member(pid)
    assert m is not None
    return m


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


class TestMultiplayerWrapDecay:
    """AC2: the WRAP decays EACH member's own standing Resonance once per phase — one write + one
    push per member that actually moved, keyed to that member's pool, never a shared value."""

    @pytest.mark.asyncio
    async def test_each_member_decays_own_pool_with_conn_and_pushes(self):
        ctx = make_context(party_member_ids=["player_2"])
        ctx.userdata.resonance.current = 5  # player_1 (primary)
        _member(ctx, "player_2").resonance.current = 3
        ctx.userdata.combat_state = _mp_state(attacks_only=True)
        deps = _resolve_deps()
        res = _resonance_deps()

        raw = await _resolve_phase_impl(ctx, cast_resolver=MagicMock(), **deps, **res)
        assert isinstance(raw, str)

        # Each member decayed one step against its OWN pool: 5->4, 3->2.
        assert ctx.userdata.resonance.current == 4
        assert _member(ctx, "player_2").resonance.current == 2
        writes = res["resonance_mutations"].update_player_resonance.await_args_list
        assert sorted((c.args[0], c.args[1]) for c in writes) == [("player_1", 4), ("player_2", 2)]
        assert all("conn" in c.kwargs for c in writes)  # each write rides the phase tx
        # Two HUD pushes, each under its own member's caster_id.
        pushes = res["resonance_events_mod"].publish_resonance_changed.await_args_list
        assert sorted(c.kwargs["caster_id"] for c in pushes) == ["player_1", "player_2"]

    @pytest.mark.asyncio
    async def test_member_at_zero_is_neither_written_nor_pushed(self):
        # 0-floor: a member already at 0 doesn't move, so no write and no push for that member —
        # only the member that actually decayed touches the DB/HUD.
        ctx = make_context(party_member_ids=["player_2"])
        ctx.userdata.resonance.current = 5
        _member(ctx, "player_2").resonance.current = 0
        ctx.userdata.combat_state = _mp_state(attacks_only=True)
        deps = _resolve_deps()
        res = _resonance_deps()

        await _resolve_phase_impl(ctx, cast_resolver=MagicMock(), **deps, **res)

        assert ctx.userdata.resonance.current == 4
        assert _member(ctx, "player_2").resonance.current == 0
        writes = res["resonance_mutations"].update_player_resonance.await_args_list
        assert [(c.args[0], c.args[1]) for c in writes] == [("player_1", 4)]
        pushes = res["resonance_events_mod"].publish_resonance_changed.await_args_list
        assert [c.kwargs["caster_id"] for c in pushes] == ["player_1"]


class TestSoloRegression:
    """AC3: the per-member phase loop collapses to exactly ONE write + ONE push for a solo party —
    byte-identical to the single-player decay path."""

    @pytest.mark.asyncio
    async def test_solo_decay_is_one_write_and_one_push(self):
        ctx = make_context()  # 1-member party (player_1 only)
        ctx.userdata.resonance.current = 5
        ctx.userdata.combat_state = _mp_state(player_ids=("player_1",), attacks_only=True)
        deps = _resolve_deps()
        res = _resonance_deps()

        await _resolve_phase_impl(ctx, cast_resolver=MagicMock(), **deps, **res)

        assert ctx.userdata.resonance.current == 4
        res["resonance_mutations"].update_player_resonance.assert_awaited_once()
        write = res["resonance_mutations"].update_player_resonance.await_args
        assert write.args == ("player_1", 4)
        assert "conn" in write.kwargs
        res["resonance_events_mod"].publish_resonance_changed.assert_awaited_once()
        assert res["resonance_events_mod"].publish_resonance_changed.await_args.kwargs["caster_id"] == "player_1"


class TestMultiplayerGenerationDecayE2E:
    """AC4: across two rounds, two players each cast a GENERATING ability with a distinct per-caster
    new_resonance; each member nets generated - decay against its OWN pool with no cross-leak."""

    @pytest.mark.asyncio
    async def test_two_rounds_net_per_pool_with_no_cross_leak(self):
        from combat_turn import _declare_phase_impl

        ctx = make_context(party_member_ids=["player_2"])
        ctx.userdata.resonance.current = 3  # player_1 standing
        player_2 = _member(ctx, "player_2")
        player_2.resonance.current = 1  # player_2 standing
        cs = _mp_state()
        cs.beat = "declaration"
        cs.pending_declarations = {}
        ctx.userdata.combat_state = cs

        # A generating cast: new_resonance = the caster's OWN standing + a fixed generation (5),
        # mirroring the real in-combat generate-without-decay path. Reading caster.resonance.current
        # (synced post-commit each round) makes round 2 build on round 1 — per pool.
        async def _resolve(session, spell_id, *, caster=None, **kwargs):
            assert caster is not None  # the phase loop always hands the declaring member
            return CastResult(
                packet={"effect": "bolt", "state": "flickering"},
                new_resonance=caster.resonance.current + 5,
                concentration_spell_id=_UNCHANGED,
                generated=5,
                events=[],
            )

        cast_resolver = MagicMock()
        cast_resolver._resolve_cast = AsyncMock(side_effect=_resolve)
        cast_resolver._gate_spell = MagicMock()
        deps = _resolve_deps()
        res = _resonance_deps()

        decls = {
            "player_1": {"type": "ability", "action": "arcane_bolt"},
            "player_2": {"type": "ability", "action": "arcane_bolt"},
            "goblin_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
        }

        # Round 1: p1 3+5=8 -> wrap 7; p2 1+5=6 -> wrap 5.
        await _declare_phase_impl(ctx, decls, mutations=deps["mutations"])
        r1 = await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)
        assert isinstance(r1, str)
        assert ctx.userdata.resonance.current == 7
        assert player_2.resonance.current == 5

        # Round 2: p1 7+5=12 -> wrap 11; p2 5+5=10 -> wrap 9. Each pool advanced on its OWN prior
        # value — no cross-leak between the two members.
        await _declare_phase_impl(ctx, decls, mutations=deps["mutations"])
        r2 = await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)
        assert isinstance(r2, str)
        assert ctx.userdata.resonance.current == 11
        assert player_2.resonance.current == 9
