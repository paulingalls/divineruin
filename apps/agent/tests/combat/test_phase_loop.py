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

from check_resolution_attack import AttackResult
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
    # The ability Focus pre-validation fetches the player for_update; a sufficient-Focus default so
    # the happy-path ability tests pass the gate (the all-attacks tests never fetch — no ability).
    queries.get_player = AsyncMock(return_value={"player_id": "player_1", "focus": {"current": 10, "max": 10}})
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

    def _resolve(attacker_data, action, target_ac, target_hp, attack_mod=0, damage_mult=1.0):
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


class TestResolvePhaseExhaustionNarration:
    """M4.3 story-005: resolve_phase surfaces a Beat-3 exhaustion_narration map for the DM to
    speak, derived from each participant's Exhausted stacks. This is the live caller for the
    otherwise-dead get_exhaustion_narrative."""

    @pytest.mark.asyncio
    async def test_exhausted_participant_gets_flavor_text(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        state = _resolution_state(player_hp=25, enemy_hp=7)
        player = state.get_participant("player_1")
        assert player is not None
        player.conditions = [{"type": "exhausted", "duration": 99, "source": "forced_march", "stacks": 2}]
        ctx.userdata.combat_state = state

        raw = await _resolve_phase_impl(ctx, **deps)
        assert isinstance(raw, str)
        result = json.loads(raw)

        assert result["exhaustion_narration"] == {"player_1": "Every movement is an effort"}

    @pytest.mark.asyncio
    async def test_no_exhaustion_yields_empty_map(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(player_hp=25, enemy_hp=7)

        raw = await _resolve_phase_impl(ctx, **deps)
        assert isinstance(raw, str)
        result = json.loads(raw)

        assert result["exhaustion_narration"] == {}


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
        assert ctx.userdata.party.primary.weapon_used is True

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

        assert ctx.userdata.party.primary.weapon_used is True
        assert ctx.userdata.party.primary.weapon_crit_vs_heavy is False

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

    @pytest.mark.asyncio
    async def test_malformed_stored_declaration_raises_tool_error(self):
        # A combat persisted at the RESOLUTION beat before the explicit-type change has an
        # untyped pending declaration. resolve_phase re-validates via the engine and must
        # translate the ValueError into a ToolError (like declare_phase) so the DM re-prompts
        # instead of crashing the turn with a raw exception.
        deps = _resolve_deps()
        ctx = make_context()
        cs = _resolution_state()
        cs.pending_declarations = {"goblin_scout_1": {"action": "Scimitar", "target_id": "player_1"}}  # no "type"
        ctx.userdata.combat_state = cs

        with pytest.raises(ToolError, match="type"):
            await _resolve_phase_impl(ctx, **deps)


class TestResolvePhaseDramatic:
    """story-004: the phase loop surfaces the M4.5 dramatic verdict on each packet summary,
    layering the encounter-context signals (first_attack, last_enemy) the per-attack resolver
    can't see. _damage_resolver returns a non-dramatic intrinsic verdict, so a dramatic packet
    here is purely the emission-site promotion."""

    @pytest.mark.asyncio
    async def test_opening_strike_is_dramatic_and_flips_the_flag(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(player_hp=25, enemy_hp=7)
        assert ctx.userdata.combat_state.first_attack_resolved is False

        raw = await _resolve_phase_impl(ctx, **deps)
        assert isinstance(raw, str)  # non-ending phase loops back, returns JSON
        result = json.loads(raw)

        # The player's opening strike (first attack of the combat) earns the dice; first_attack
        # outranks last_enemy in the catalog, so that's the surfaced label.
        player_packet = next(p for p in result["packets"] if p["actor_id"] == "player_1")
        assert player_packet["dramatic"] is True
        assert player_packet["context"] == "first_attack"
        # The combat-scoped flag flipped, so a later attack no longer earns the first-attack dice.
        assert ctx.userdata.combat_state.first_attack_resolved is True

    @pytest.mark.asyncio
    async def test_every_packet_summary_carries_the_dramatic_keys(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(player_hp=25, enemy_hp=7)

        raw = await _resolve_phase_impl(ctx, **deps)
        assert isinstance(raw, str)
        result = json.loads(raw)

        for p in result["packets"]:
            assert "dramatic" in p and isinstance(p["dramatic"], bool)
            assert "context" in p

    @pytest.mark.asyncio
    async def test_multi_swing_later_kill_reports_the_dramatic_swings_context(self):
        # Regression: an extra_attack expands to two swings; the FIRST is routine
        # (not dramatic) and the SECOND lands the killing blow (intrinsic dramatic,
        # context="killing_blow"). The aggregated summary must report dramatic=True
        # AND the killing swing's context — not the first swing's "" — or the DM
        # narrates a dramatic moment with no reason label (code-review finding 1).
        cs = _resolution_state(player_hp=25, enemy_hp=8)
        # Two enemies standing so neither swing earns the last_enemy promotion, and a
        # prior attack already resolved so neither earns first_attack — the only
        # dramatic source is the second swing's intrinsic killing blow.
        cs.first_attack_resolved = True
        cs.participants.append(
            CombatParticipant(
                id="goblin_scout_2",
                name="Goblin Scout",
                type="enemy",
                initiative=10,
                hp_current=8,
                hp_max=8,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}],
                xp_value=50,
            )
        )
        cs.initiative_order = ["player_1", "goblin_scout_1", "goblin_scout_2"]
        player = cs.get_participant("player_1")
        assert player is not None
        player.enhancers = ["extra_attack"]  # two swings from one ATTACK declaration
        cs.pending_declarations = {
            "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"},
        }

        # Stateful resolver: first swing deals 5 (8 -> 3, survives, routine); second swing
        # deals 5 again (3 -> 0, the intrinsic killing blow fires dramatic="killing_blow").
        swings = iter(
            [
                AttackResult(
                    hit=True,
                    roll=12,
                    attack_modifier=3,
                    attack_total=15,
                    target_ac=13,
                    damage=5,
                    damage_type="slashing",
                    critical_success=False,
                    critical_failure=False,
                    target_hp_remaining=3,
                    target_killed=False,
                    narrative_hint="A solid hit.",
                ),
                AttackResult(
                    hit=True,
                    roll=14,
                    attack_modifier=3,
                    attack_total=17,
                    target_ac=13,
                    damage=5,
                    damage_type="slashing",
                    critical_success=False,
                    critical_failure=False,
                    target_hp_remaining=0,
                    target_killed=True,
                    narrative_hint="The finishing blow.",
                    dramatic=True,
                    context="killing_blow",
                ),
            ]
        )
        resolver = MagicMock()
        resolver.resolve_attack = MagicMock(side_effect=lambda *a, **k: next(swings))

        deps = _resolve_deps()
        deps["resolver"] = resolver
        ctx = make_context()
        ctx.userdata.combat_state = cs

        raw = await _resolve_phase_impl(ctx, **deps)
        assert isinstance(raw, str)  # one enemy still stands -> non-ending phase
        result = json.loads(raw)

        player_packet = next(p for p in result["packets"] if p["actor_id"] == "player_1")
        assert len(player_packet["attacks"]) == 2
        assert player_packet["dramatic"] is True
        assert player_packet["context"] == "killing_blow"


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
    async def test_defeat_ends_and_hands_off(self, monkeypatch):
        import resurrection

        # Stub the defeat-path resurrection; this test asserts the defeat handoff, not the
        # resurrection flow. The defeat router now routes fallen players through
        # resurrect_party_on_defeat (M14 story-006) — one fallen player -> a one-context list.
        monkeypatch.setattr(
            resurrection, "resurrect_party_on_defeat", AsyncMock(return_value=[{"anchor": "accord_guild_hall"}])
        )
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

    @pytest.mark.asyncio
    async def test_fallen_defender_grants_no_ac_bonus(self):
        # A Defend from an actor who has already fallen this phase grants no AC bonus —
        # the pre-pass mirrors the per-packet "actor unavailable" guard.
        deps = _resolve_deps()
        ctx = make_context()
        cs = _resolution_state()
        player = cs.get_participant("player_1")
        assert player is not None
        player.is_fallen = True
        cs.pending_declarations = {"player_1": {"type": "defend"}}
        ctx.userdata.combat_state = cs

        await _resolve_phase_impl(ctx, **deps)

        assert ctx.userdata.combat_state.ac_modifiers == {}


class TestResolvePhaseAbility:
    """story-007: an in-combat ABILITY declaration resolves via the shared cast resolver and appears
    as a resolved packet in initiative order alongside attacks. The cast itself is mocked here — the
    wiring/ordering is under test, not the spell internals (covered by test_spell_casting)."""

    def _ability_state(self):
        state = _resolution_state()
        # Player declares an ABILITY instead of an attack; the enemy still swings.
        state.pending_declarations["player_1"] = {"type": "ability", "action": "arcane_bolt"}
        return state

    def _cast_resolver(self, result):
        mod = MagicMock()
        mod._resolve_cast = AsyncMock(return_value=result)
        return mod

    @pytest.mark.asyncio
    async def test_player_ability_resolves_in_initiative_order(self):
        from spell_casting import _UNCHANGED, CastResult

        ctx = make_context()
        ctx.userdata.combat_state = self._ability_state()
        result = CastResult(
            packet={"effect": "A bolt of force.", "state": "flickering", "resonance_generated": 6},
            new_resonance=6,
            concentration_spell_id=_UNCHANGED,
            generated=6,
            events=[],
        )
        cast_resolver = self._cast_resolver(result)
        deps = _resolve_deps()
        res = _resonance_deps()  # the ability generates resonance -> the WRAP write path is exercised

        raw = await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)
        assert isinstance(raw, str)  # combat continues -> JSON response (not the end-of-combat tuple)
        packets = json.loads(raw)["packets"]

        # Player (initiative 15) resolves before the enemy (initiative 12).
        assert packets[0]["actor_id"] == "player_1"
        assert packets[0]["resolved"] is True
        assert packets[0]["declaration_type"] == "ability"
        assert packets[0]["cast"]["effect"] == "A bolt of force."
        # The enemy's attack still resolves the same phase.
        assert packets[1]["actor_id"] == "goblin_scout_1"
        cast_resolver._resolve_cast.assert_awaited_once()


class TestResolvePhaseAbilityResonance:
    """story-007: an in-combat ability GENERATES resonance during resolution (beat 2); the WRAP
    decay (beat 4) then sheds from the post-generation total, so the phase nets
    standing + generated - 1. The generated value is persisted by the cast inside the tx (mocked
    here); the loop seeds the WRAP base with it and syncs/pushes once post-commit."""

    def _ability_state(self):
        state = _resolution_state()  # enemy hp 7 -> combat continues this phase
        state.pending_declarations["player_1"] = {"type": "ability", "action": "arcane_bolt"}
        return state

    def _cast_resolver(self, *, new_resonance, generated=5, concentration=None, events=None):
        from spell_casting import _UNCHANGED, CastResult

        result = CastResult(
            packet={"effect": "A bolt of force.", "state": "flickering"},
            new_resonance=new_resonance,
            concentration_spell_id=concentration if concentration is not None else _UNCHANGED,
            generated=generated,
            events=events or [],
        )
        mod = MagicMock()
        mod._resolve_cast = AsyncMock(return_value=result)
        return mod

    @pytest.mark.asyncio
    async def test_generation_then_wrap_decay_nets_correctly(self):
        ctx = make_context()
        ctx.userdata.resonance.current = 3  # standing
        ctx.userdata.combat_state = self._ability_state()
        # The cast wrote standing(3)+generated(5)=8 inside the tx (mocked as new_resonance=8).
        cast_resolver = self._cast_resolver(new_resonance=8)
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()

        raw = await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)

        assert isinstance(raw, str)
        # WRAP decays the post-generation total by 1: 8 -> 7 (NOT standing 3 -> 2).
        assert ctx.userdata.resonance.current == 7
        write = res["resonance_mutations"].update_player_resonance.await_args
        assert write.args == ("player_1", 7)
        # The single authoritative per-phase HUD push (the ability suppressed its own).
        res["resonance_events_mod"].publish_resonance_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_killing_phase_ability_resonance_pushes_hud(self):
        """Regression (story-007 finding 2): an ability that GENERATES resonance on the same phase
        that ends combat must still push the qualitative Resonance HUD state. The sync + push run
        BEFORE the end-of-combat handoff return, so the client never keeps a stale state."""
        ctx = make_context()
        ctx.userdata.resonance.current = 3
        # Enemy already fallen -> the wrap reports victory THIS phase (combat ends).
        state = _resolution_state()
        enemy = state.get_participant("goblin_scout_1")
        assert enemy is not None
        enemy.is_fallen = True
        enemy.hp_current = 0
        state.pending_declarations = {"player_1": {"type": "ability", "action": "arcane_bolt"}}
        ctx.userdata.combat_state = state
        cast_resolver = self._cast_resolver(new_resonance=8)
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()

        raw = await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)

        assert isinstance(raw, tuple)  # combat ended -> handoff
        assert json.loads(raw[1])["outcome"] == "victory"
        # The generated resonance was synced AND its HUD push fired even though combat ended.
        assert ctx.userdata.resonance.current == 8
        res["resonance_events_mod"].publish_resonance_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cantrip_ability_adds_nothing_but_phase_still_decays(self):
        ctx = make_context()
        ctx.userdata.resonance.current = 3
        ctx.userdata.combat_state = self._ability_state()
        # A cantrip generates 0 -> the cast wrote no resonance (new_resonance None).
        cast_resolver = self._cast_resolver(new_resonance=None, generated=0)
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()

        await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)

        # No generation to seed the base, so the phase decays the standing value: 3 -> 2.
        assert ctx.userdata.resonance.current == 2
        write = res["resonance_mutations"].update_player_resonance.await_args
        assert write.args == ("player_1", 2)

    @pytest.mark.asyncio
    async def test_concentration_change_synced_post_commit(self):
        ctx = make_context()
        ctx.userdata.concentration.spell_id = None
        ctx.userdata.combat_state = self._ability_state()
        cast_resolver = self._cast_resolver(new_resonance=4, concentration="hold_flame")
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()

        await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)

        # The cast persisted concentration via conn; the loop syncs the in-memory SSOT IN-LOOP
        # (so a same-phase, lower-initiative concentration break sees the just-cast spell).
        assert ctx.userdata.concentration.spell_id == "hold_flame"

    @pytest.mark.asyncio
    async def test_inphase_concentration_break_sees_just_cast_spell(self):
        """Regression (story-007 finding 1): a player concentrating on spell A casts a concentration
        ABILITY for spell B at HIGHER initiative; a lower-initiative enemy hits the player the SAME
        phase. break_concentration_on_damage runs in-loop and MUST read the just-cast spell B (not the
        stale A), or it would save against the wrong spell and clear B from the DB while the session
        forced memory back to B — a silent divergence. The in-loop concentration sync fixes this."""
        ctx = make_context()
        ctx.userdata.concentration.spell_id = "spell_a"  # the prior concentration the cast replaces
        ctx.userdata.combat_state = self._ability_state()
        cast_resolver = self._cast_resolver(new_resonance=4, concentration="spell_b")

        # Spy break: record what concentration spell it observes when the lower-initiative enemy hits.
        seen: list[str | None] = []

        async def _spy_break(session, damage, incapacitated, *, damaged_player_id, combat_state=None, conn=None):
            seen.append(session.concentration.spell_id)
            return None

        deps = _resolve_deps(damage=3)
        deps["concentration_break_mod"].break_concentration_on_damage = AsyncMock(side_effect=_spy_break)
        res = _resonance_deps()

        await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)

        # The break (enemy attack, initiative 12) ran AFTER the ability cast (initiative 15) and saw
        # the just-cast spell B in memory — not the stale spell A.
        assert seen == ["spell_b"]

    @pytest.mark.asyncio
    async def test_cast_deferred_events_flushed_post_commit(self):
        emitted: list[str] = []

        async def _echo():
            emitted.append("hollow_echo")

        ctx = make_context()
        ctx.userdata.resonance.current = 0
        ctx.userdata.combat_state = self._ability_state()
        cast_resolver = self._cast_resolver(new_resonance=4, events=[lambda: _echo()])
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()

        await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)

        # The cast's own deferred client events (hollow echo, Vaelti warning) fire after commit.
        assert emitted == ["hollow_echo"]


class TestResolvePhaseAbilityFocusGate:
    """story-007 AC2: an in-combat ability with insufficient Focus fails loud (ToolError) with NO
    state writes, validated BEFORE the resolution loop so no other actor's HP write is rolled back."""

    def _ability_state(self):
        state = _resolution_state()
        state.pending_declarations["player_1"] = {"type": "ability", "action": "arcane_shield_spell"}
        return state

    @pytest.mark.asyncio
    async def test_insufficient_focus_raises_before_any_write(self):
        ctx = make_context()
        ctx.userdata.combat_state = self._ability_state()
        deps = _resolve_deps(damage=3)
        # The player can't afford the ability; the pre-validation runs the real cast gate and raises.
        deps["queries"].get_player = AsyncMock(return_value={"player_id": "player_1", "focus": {"current": 0}})
        res = _resonance_deps()
        cast_resolver = MagicMock()
        cast_resolver._gate_spell = MagicMock(side_effect=ToolError("Not enough Focus for Arcane Shield"))
        cast_resolver._resolve_cast = AsyncMock()

        with pytest.raises(ToolError, match="Focus"):
            await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)

        # AC2: nothing was written and the loop never ran — the ability is rejected pre-loop.
        cast_resolver._resolve_cast.assert_not_called()
        deps["mutations"].update_player_hp.assert_not_called()
        deps["mutations"].save_combat_state.assert_not_called()
        res["resonance_mutations"].update_player_resonance.assert_not_called()

    @pytest.mark.asyncio
    async def test_player_row_is_passed_through_to_the_cast(self):
        # The pre-validation fetches the player for_update ONCE and threads it to the cast, so the
        # cast does not re-fetch (single lock). The mock cast records the player it was handed.
        from spell_casting import _UNCHANGED, CastResult

        ctx = make_context()
        ctx.userdata.combat_state = self._ability_state()
        deps = _resolve_deps(damage=3)
        player_row = {"player_id": "player_1", "focus": {"current": 9}}
        deps["queries"].get_player = AsyncMock(return_value=player_row)
        res = _resonance_deps()
        cast_resolver = MagicMock()
        cast_resolver._gate_spell = MagicMock()  # affordable -> no raise
        cast_resolver._resolve_cast = AsyncMock(
            return_value=CastResult(
                packet={"effect": "ward"}, new_resonance=None, concentration_spell_id=_UNCHANGED, generated=0, events=[]
            )
        )

        await _resolve_phase_impl(ctx, cast_resolver=cast_resolver, **deps, **res)

        _args, kwargs = cast_resolver._resolve_cast.call_args
        assert kwargs["player"] is player_row
