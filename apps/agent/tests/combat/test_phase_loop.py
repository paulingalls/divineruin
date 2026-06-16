"""Tests for the live phase-loop tools (story-003): declare_phase + resolve_phase.

These drive the deterministic 4-beat engine (combat_phase.advance_combat_phase) from
the live CombatAgent: declare_phase collects a phase's declarations (DECLARATION ->
RESOLUTION); resolve_phase resolves the packets, narrates (engine no-op), wraps, and
either loops to the next declaration beat or fires the end-of-combat handoff.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver, _fake_db_mod, _make_combat_state, _resolution_state
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

from check_resolution import AttackResult
from combat_turn import _declare_phase_impl, _resolve_phase_impl
from session_data import CombatParticipant


def _make_mutations():
    m = MagicMock()
    m.save_combat_state = AsyncMock()
    m.update_player_hp = AsyncMock()
    m.delete_combat_state = AsyncMock()
    return m


def _resolve_deps(damage=3):
    """DI bundle for resolve_phase: a deterministic damage resolver plus the
    mutations/queries/concentration mocks the packet path touches, and a no-op db_mod
    so the per-phase transaction wrapper runs without a real connection."""
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])  # no equipped items
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
    return {
        "mutations": _make_mutations(),
        "queries": queries,
        "resolver": _damage_resolver(damage),
        "concentration_break_mod": break_mod,
        "db_mod": _fake_db_mod(),
    }


def _miss_resolver():
    """A resolve_attack that always misses — no damage, target HP unchanged."""

    def _resolve(attacker_data, action, target_ac, target_hp):
        return AttackResult(
            hit=False,
            roll=3,
            attack_modifier=3,
            attack_total=6,
            target_ac=target_ac,
            damage=0,
            damage_type="slashing",
            critical_success=False,
            critical_failure=False,
            target_hp_remaining=target_hp,
            target_killed=False,
            narrative_hint="The blade whistles wide.",
        )

    r = MagicMock()
    r.resolve_attack = MagicMock(side_effect=_resolve)
    return r


def _declarations():
    return {
        "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"},
        "goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
    }


class TestDeclarePhase:
    @pytest.mark.asyncio
    async def test_advances_to_resolution_and_stores_declarations(self):
        mutations = _make_mutations()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()  # beat defaults to "declaration"

        result = json.loads(await _declare_phase_impl(ctx, _declarations(), mutations=mutations))

        cs = ctx.userdata.combat_state
        assert cs.beat == "resolution"
        assert cs.pending_declarations == _declarations()
        assert set(result["accepted_actors"]) == {"player_1", "goblin_scout_1"}
        assert result["beat"] == "resolution"
        mutations.save_combat_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_declarations_raises(self):
        mutations = _make_mutations()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        with pytest.raises(ToolError):
            await _declare_phase_impl(ctx, {}, mutations=mutations)
        mutations.save_combat_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_beat_raises(self):
        mutations = _make_mutations()
        ctx = make_context()
        cs = _make_combat_state()
        cs.beat = "resolution"  # not the declaration beat
        ctx.userdata.combat_state = cs

        with pytest.raises(ToolError, match="declaration beat"):
            await _declare_phase_impl(ctx, _declarations(), mutations=mutations)
        mutations.save_combat_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_in_combat_raises(self):
        ctx = make_context()  # no combat_state

        with pytest.raises(ToolError, match="Not in combat"):
            await _declare_phase_impl(ctx, _declarations())


class TestResolvePhaseNonEnding:
    @pytest.mark.asyncio
    async def test_resolves_packets_in_initiative_order_and_loops(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(player_hp=25, enemy_hp=7)

        raw = await _resolve_phase_impl(ctx, **deps)
        assert isinstance(raw, str)  # non-ending phase loops back, returns JSON (not a handoff tuple)
        result = json.loads(raw)

        cs = ctx.userdata.combat_state
        goblin = cs.get_participant("goblin_scout_1")
        kael = cs.get_participant("player_1")
        assert goblin is not None and kael is not None
        # Player (init 15) attacks the goblin (7-3); goblin (init 12) attacks Kael (25-3).
        assert goblin.hp_current == 4
        assert kael.hp_current == 22
        # Resolution order is initiative-desc: player before enemy.
        assert [p["actor_id"] for p in result["packets"]] == ["player_1", "goblin_scout_1"]
        assert all(p["resolved"] for p in result["packets"])
        # No one fell -> engine loops back to the next declaration beat.
        assert result["beat"] == "declaration"
        assert result["round"] == 2
        assert result["death_saves_due"] == []
        deps["mutations"].save_combat_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sets_weapon_flags_on_player_hit(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state()

        await _resolve_phase_impl(ctx, **deps)

        # The player's weapon swung this encounter (end_combat reads this for durability).
        assert ctx.userdata.weapon_used_this_encounter is True

    @pytest.mark.asyncio
    async def test_sets_weapon_used_even_when_player_misses(self):
        # Regression: a swing arms the per-encounter durability accrual whether it
        # hits or misses (the old request_attack set this on any swing). Only the
        # crit-vs-heavy bonus is gated on a landing crit.
        deps = _resolve_deps()
        deps["resolver"] = _miss_resolver()
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state()

        await _resolve_phase_impl(ctx, **deps)

        assert ctx.userdata.weapon_used_this_encounter is True
        assert ctx.userdata.weapon_crit_vs_heavy is False

    @pytest.mark.asyncio
    async def test_wasted_when_target_already_fell(self):
        # A lower-initiative actor whose target was dropped earlier this phase is wasted,
        # not resolved. Engineer it: goblin dies to the player's strike (enemy_hp=3, dmg=3),
        # but the goblin's own declaration still targets the (living) player and resolves —
        # so instead assert the player's packet kills, and a second enemy's packet wasted.
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        cs = _resolution_state(enemy_hp=3)
        # Add a second enemy that targets the first goblin (which the player kills first).
        cs.participants.append(
            CombatParticipant(
                id="goblin_scout_2",
                name="Goblin Two",
                type="enemy",
                initiative=5,
                hp_current=7,
                hp_max=7,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}],
            )
        )
        cs.pending_declarations["goblin_scout_2"] = {
            "type": "attack",
            "action": "Scimitar",
            "target_id": "goblin_scout_1",
        }
        ctx.userdata.combat_state = cs

        raw = await _resolve_phase_impl(ctx, **deps)
        assert isinstance(raw, str)
        result = json.loads(raw)

        by_actor = {p["actor_id"]: p for p in result["packets"]}
        # Player (init 15) kills goblin_scout_1 (3-3=0); goblin_scout_2 (init 5) targeted it -> wasted.
        assert by_actor["goblin_scout_2"]["resolved"] is False
        assert "already" in by_actor["goblin_scout_2"]["reason"]

    @pytest.mark.asyncio
    async def test_wrong_beat_raises(self):
        deps = _resolve_deps()
        ctx = make_context()
        cs = _resolution_state()
        cs.beat = "declaration"  # not the resolution beat
        ctx.userdata.combat_state = cs

        with pytest.raises(ToolError, match="resolution beat"):
            await _resolve_phase_impl(ctx, **deps)


class TestResolvePhaseEnding:
    @pytest.mark.asyncio
    async def test_victory_ends_and_hands_off(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        # Player (init 15) strikes the goblin for 3; goblin has 3 HP -> it falls before
        # it can act (its own declaration is wasted). All enemies down -> victory.
        ctx.userdata.combat_state = _resolution_state(enemy_hp=3)

        raw = await _resolve_phase_impl(ctx, **deps)

        assert isinstance(raw, tuple)  # combat ended -> (gameplay_agent, json) handoff
        _agent, json_str = raw
        result = json.loads(json_str)
        assert result["outcome"] == "victory"
        assert ctx.userdata.combat_state is None
        deps["mutations"].delete_combat_state.assert_awaited_once()
        # The ending phase is never persisted back (state was deleted instead).
        deps["mutations"].save_combat_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_defeat_ends_and_hands_off(self):
        deps = _resolve_deps()
        ctx = make_context()
        cs = _resolution_state()
        player = cs.get_participant("player_1")
        assert player is not None
        # The player has already burned three failed death saves (from prior request_death_save
        # calls) and is down; this phase's wrap reads that and ends in defeat.
        player.is_fallen = True
        player.hp_current = 0
        player.death_save_failures = 3
        cs.pending_declarations = {"goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"}}
        ctx.userdata.combat_state = cs

        raw = await _resolve_phase_impl(ctx, **deps)

        assert isinstance(raw, tuple)
        _agent, json_str = raw
        assert json.loads(json_str)["outcome"] == "defeat"
        assert ctx.userdata.combat_state is None


def _resonance_deps():
    res_mut = MagicMock()
    res_mut.update_player_resonance = AsyncMock()
    res_evt = MagicMock()
    res_evt.publish_resonance_changed = AsyncMock()
    return {"resonance_mutations": res_mut, "resonance_events_mod": res_evt}


class TestResolvePhaseResonanceDecay:
    @pytest.mark.asyncio
    async def test_decays_one_step_on_non_ending_wrap(self):
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state()
        ctx.userdata.resonance.current = 5

        await _resolve_phase_impl(ctx, **deps, **res)

        # WRAP is the canonical combat decay clock: one step per phase.
        assert ctx.userdata.resonance.current == 4
        # The resonance write runs inside the phase transaction, so it carries the conn the
        # db_mod.transaction() context yields (not the implicit None default).
        write = res["resonance_mutations"].update_player_resonance.await_args
        assert write.args == ("player_1", 4)
        assert "conn" in write.kwargs
        res["resonance_events_mod"].publish_resonance_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_decay_or_write_at_zero(self):
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state()
        ctx.userdata.resonance.current = 0

        await _resolve_phase_impl(ctx, **deps, **res)

        assert ctx.userdata.resonance.current == 0
        res["resonance_mutations"].update_player_resonance.assert_not_called()
        res["resonance_events_mod"].publish_resonance_changed.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_decay_when_combat_ends(self):
        # Decay happens during the fight, not on the terminal wrap that ends combat.
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(enemy_hp=3)  # victory this phase
        ctx.userdata.resonance.current = 5

        raw = await _resolve_phase_impl(ctx, **deps, **res)

        assert isinstance(raw, tuple)  # combat ended
        assert ctx.userdata.resonance.current == 5  # unchanged
        res["resonance_mutations"].update_player_resonance.assert_not_called()


class TestPhaseLoopE2E:
    """AC4: a live encounter advances declaration -> resolution -> narration -> wrap
    across rounds to victory through the phase tools (declare_phase + resolve_phase),
    with the engine firing the end-of-combat handoff itself."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_to_victory(self):
        deps = _resolve_deps(damage=4)
        ctx = make_context()
        # Start parked at the declaration beat, as combat_init leaves a fresh encounter.
        cs = _resolution_state(player_hp=25, enemy_hp=7)
        cs.beat = "declaration"
        cs.pending_declarations = {}
        ctx.userdata.combat_state = cs

        decls = {
            "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"},
            "goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
        }

        # --- Round 1: declaration -> resolution -> (combat continues) -> declaration ---
        d1 = json.loads(await _declare_phase_impl(ctx, decls, mutations=deps["mutations"]))
        assert d1["beat"] == "resolution"

        r1 = await _resolve_phase_impl(ctx, **deps)
        assert isinstance(r1, str), "round 1 does not end combat"
        r1j = json.loads(r1)
        assert r1j["beat"] == "declaration" and r1j["round"] == 2
        assert len([p for p in r1j["packets"] if p["resolved"]]) == 2
        goblin = ctx.userdata.combat_state.get_participant("goblin_scout_1")
        assert goblin is not None and goblin.hp_current == 3  # 7 - 4

        # --- Round 2: declaration -> resolution -> wrap -> victory handoff ---
        await _declare_phase_impl(ctx, decls, mutations=deps["mutations"])
        r2 = await _resolve_phase_impl(ctx, **deps)

        assert isinstance(r2, tuple), "the winning wrap returns the (gameplay_agent, json) handoff"
        _agent, json_str = r2
        assert json.loads(json_str)["outcome"] == "victory"
        assert ctx.userdata.combat_state is None
        deps["mutations"].delete_combat_state.assert_awaited_once()


class TestResolvePhaseDefend:
    @pytest.mark.asyncio
    async def test_defend_grants_plus_two_ac_against_attacks_this_phase(self):
        # Player Defends (init 15, resolves first); the goblin then attacks the player and
        # must roll against the defended AC (14 base + 2), regardless of initiative order.
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        cs = _resolution_state()  # player ac 14
        cs.pending_declarations = {
            "player_1": {"type": "defend"},
            "goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
        }
        ctx.userdata.combat_state = cs

        raw = await _resolve_phase_impl(ctx, **deps)
        assert isinstance(raw, str)
        result = json.loads(raw)
        summaries = {s["actor_id"]: s for s in result["packets"]}

        # Defend resolves as a no-op stance carrying the +2 bonus (no attack).
        assert summaries["player_1"]["resolved"] is True
        assert summaries["player_1"]["declaration_type"] == "defend"
        assert summaries["player_1"]["ac_bonus"] == 2

        # The goblin's attack resolves against the defended AC (14 + 2 = 16).
        assert summaries["goblin_scout_1"]["target_ac"] == 16
        deps["resolver"].resolve_attack.assert_called_once()
        assert deps["resolver"].resolve_attack.call_args.args[2] == 16

    @pytest.mark.asyncio
    async def test_defend_ac_bonus_clears_next_phase(self):
        # After a Defend phase, the wrap loop-back clears ac_modifiers so the bonus
        # does not bleed into the next round.
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        cs = _resolution_state()
        cs.pending_declarations = {
            "player_1": {"type": "defend"},
            "goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
        }
        ctx.userdata.combat_state = cs

        await _resolve_phase_impl(ctx, **deps)

        assert ctx.userdata.combat_state.ac_modifiers == {}
