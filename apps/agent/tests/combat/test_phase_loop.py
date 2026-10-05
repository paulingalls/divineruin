import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from _combat_end_fixtures import combat_end_mutations
from combat._helpers import _damage_resolver, _fake_db_mod, _make_combat_state, _resolution_state, _resolve_round
from inventory_snapshot_fixture import snapshot_query
from livekit.agents.llm import ToolError
from sample_fixtures import make_context
from voice_condition_fixtures import place_actors

from check_resolution_attack import AttackResult
from combat_turn import _declare_phase_impl
from session_data import CombatParticipant


def _make_mutations():
    m = combat_end_mutations()
    m.save_combat_state = AsyncMock()
    m.update_player_hp = AsyncMock()
    return m


def _resolve_deps(damage=3):
    """DI bundle for resolve_phase: a deterministic damage resolver plus the
    mutations/queries/concentration mocks the packet path touches, and a no-op db_mod
    so the per-phase transaction wrapper runs without a real connection."""
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])  # no equipped items
    queries.get_inventory_snapshot = snapshot_query([])
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

    def _resolve(attacker_data, action, target_ac, target_hp, attack_mod=0, damage_mult=1.0, target_conditions=()):
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
    @pytest.mark.asyncio
    async def test_exhausted_participant_gets_flavor_text(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        state = _resolution_state(player_hp=25, enemy_hp=7)
        player = state.get_participant("player_1")
        assert player is not None
        player.conditions = [{"type": "exhausted", "duration": 99, "source": "forced_march", "stacks": 2}]
        ctx.userdata.combat_state = state

        result = await _resolve_round(ctx, **deps)

        assert result["exhaustion_narration"] == {"player_1": "Every movement is an effort"}

    @pytest.mark.asyncio
    async def test_no_exhaustion_yields_empty_map(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(player_hp=25, enemy_hp=7)

        result = await _resolve_round(ctx, **deps)

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
    async def test_unknown_attack_action_fails_before_persisting(self):
        mutations = _make_mutations()
        ctx = make_context()
        state = _make_combat_state()
        ctx.userdata.combat_state = state
        declarations = _declarations()
        declarations["goblin_scout_1"]["action"] = "Claw"
        with pytest.raises(ToolError) as raised:
            await _declare_phase_impl(ctx, declarations, mutations=mutations)

        assert all(value in str(raised.value) for value in ("Goblin Scout", "goblin_scout_1", "Claw", "Scimitar"))
        assert ctx.userdata.combat_state is state
        assert state.beat == "declaration" and state.pending_declarations == {}
        mutations.save_combat_state.assert_not_awaited()

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

        result = await _resolve_round(ctx, **deps)

        cs = ctx.userdata.combat_state
        goblin = cs.get_participant("goblin_scout_1")
        kael = cs.get_participant("player_1")
        assert goblin is not None and kael is not None
        assert goblin.hp_current == 4
        assert kael.hp_current == 22
        assert [p["actor_id"] for p in result["packets"]] == ["player_1", "goblin_scout_1"]
        assert all(p["resolved"] for p in result["packets"])
        assert result["beat"] == "declaration"
        assert result["round"] == 2
        assert result["death_saves_due"] == []
        assert deps["mutations"].save_combat_state.await_count == 2

    @pytest.mark.asyncio
    async def test_sets_weapon_flags_on_player_hit(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state()

        await _resolve_round(ctx, **deps)

        assert ctx.userdata.party.primary.weapon_used is True

    @pytest.mark.asyncio
    async def test_sets_weapon_used_even_when_player_misses(self):
        deps = _resolve_deps()
        deps["resolver"] = _miss_resolver()
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state()

        await _resolve_round(ctx, **deps)

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
        place_actors(cs)
        cs.pending_declarations["goblin_scout_2"] = {
            "type": "attack",
            "action": "Scimitar",
            "target_id": "goblin_scout_1",
        }
        ctx.userdata.combat_state = cs

        result = await _resolve_round(ctx, **deps)

        by_actor = {p["actor_id"]: p for p in result["packets"]}
        assert by_actor["goblin_scout_2"]["resolved"] is False
        assert "already" in by_actor["goblin_scout_2"]["reason"]

    @pytest.mark.asyncio
    async def test_wrong_beat_raises(self):
        deps = _resolve_deps()
        ctx = make_context()
        cs = _resolution_state()
        cs.beat = "declaration"  # not the resolution beat
        ctx.userdata.combat_state = cs

        with pytest.raises(ToolError, match="resolution or narration beat"):
            await _resolve_round(ctx, **deps)

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
            await _resolve_round(ctx, **deps)


class TestResolvePhaseEnding:
    @pytest.mark.asyncio
    async def test_victory_ends_and_hands_off(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(enemy_hp=3)

        result = await _resolve_round(ctx, **deps)

        assert isinstance(result, tuple)  # combat ended -> (gameplay_agent, json) handoff
        _agent, json_str = result
        result = json.loads(json_str)
        assert result["outcome"] == "victory"
        assert ctx.userdata.combat_state is None
        deps["mutations"].delete_combat_state.assert_awaited_once()
        assert deps["mutations"].save_combat_state.await_count == 1

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
        player.is_fallen = True
        player.hp_current = 0
        player.death_save_failures = 3
        cs.pending_declarations = {"goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"}}
        ctx.userdata.combat_state = cs

        raw = await _resolve_round(ctx, **deps)

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

        await _resolve_round(ctx, **deps, **res)

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

        await _resolve_round(ctx, **deps, **res)

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

        raw = await _resolve_round(ctx, **deps, **res)

        assert isinstance(raw, tuple)  # combat ended
        assert ctx.userdata.resonance.current == 5  # unchanged
        res["resonance_mutations"].update_player_resonance.assert_not_called()


class TestResolvePhaseDefend:
    @pytest.mark.asyncio
    async def test_defend_grants_plus_two_ac_against_attacks_this_phase(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        cs = _resolution_state()  # player ac 14
        cs.pending_declarations = {
            "player_1": {"type": "defend"},
            "goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
        }
        ctx.userdata.combat_state = cs

        result = await _resolve_round(ctx, **deps)
        summaries = {s["actor_id"]: s for s in result["packets"]}

        assert summaries["player_1"]["resolved"] is True
        assert summaries["player_1"]["declaration_type"] == "defend"
        assert summaries["player_1"]["ac_bonus"] == 2

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

        await _resolve_round(ctx, **deps)

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

        await _resolve_round(ctx, **deps)

        assert ctx.userdata.combat_state.ac_modifiers == {}
