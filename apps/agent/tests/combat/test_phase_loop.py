"""Tests for the live phase-loop tools (story-003): declare_phase + resolve_phase.

These drive the deterministic 4-beat engine (combat_phase.advance_combat_phase) from
the live CombatAgent: declare_phase collects a phase's declarations (DECLARATION ->
RESOLUTION); resolve_phase resolves the packets, narrates (engine no-op), wraps, and
either loops to the next declaration beat or fires the end-of-combat handoff.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state, _make_context
from livekit.agents.llm import ToolError

from check_resolution import AttackResult
from combat_turn import _declare_phase_impl, _resolve_phase_impl
from session_data import CombatParticipant, CombatState


def _make_mutations():
    m = MagicMock()
    m.save_combat_state = AsyncMock()
    m.update_player_hp = AsyncMock()
    return m


def _resolve_deps(damage=3):
    """DI bundle for resolve_phase: a deterministic damage resolver plus the
    mutations/queries/concentration mocks the packet path touches."""
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])  # no equipped items
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
    return {
        "mutations": _make_mutations(),
        "queries": queries,
        "resolver": _damage_resolver(damage),
        "concentration_break_mod": break_mod,
    }


def _damage_resolver(damage):
    """A resolve_attack that always hits for a fixed damage, computing the target's
    remaining HP from the call args so multiple packets resolve coherently."""

    def _resolve(attacker_data, action, target_ac, target_hp):
        remaining = max(0, target_hp - damage)
        return AttackResult(
            hit=True,
            roll=15,
            attack_modifier=3,
            attack_total=18,
            target_ac=target_ac,
            damage=damage,
            damage_type="slashing",
            critical=False,
            critical_success=False,
            critical_failure=False,
            target_hp_remaining=remaining,
            target_killed=remaining == 0,
            narrative_hint="A clean strike.",
        )

    r = MagicMock()
    r.resolve_attack = MagicMock(side_effect=_resolve)
    return r


def _resolution_state(player_hp=25, enemy_hp=7):
    """A CombatState parked at the RESOLUTION beat with player+enemy declarations
    pending. The player carries a synthesized weapon action_pool (story-003 step 6
    builds this at init; constructed inline here)."""
    return CombatState(
        combat_id="combat_test123",
        participants=[
            CombatParticipant(
                id="player_1",
                name="Kael",
                type="player",
                initiative=15,
                hp_current=player_hp,
                hp_max=25,
                ac=14,
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
            ),
            CombatParticipant(
                id="goblin_scout_1",
                name="Goblin Scout",
                type="enemy",
                initiative=12,
                hp_current=enemy_hp,
                hp_max=7,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}],
                xp_value=50,
            ),
        ],
        initiative_order=["player_1", "goblin_scout_1"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="resolution",
        pending_declarations={
            "player_1": {"action": "Longsword", "target_id": "goblin_scout_1"},
            "goblin_scout_1": {"action": "Scimitar", "target_id": "player_1"},
        },
    )


def _declarations():
    return {
        "player_1": {"action": "Longsword", "target_id": "goblin_scout_1"},
        "goblin_scout_1": {"action": "Scimitar", "target_id": "player_1"},
    }


class TestDeclarePhase:
    @pytest.mark.asyncio
    async def test_advances_to_resolution_and_stores_declarations(self):
        mutations = _make_mutations()
        ctx = _make_context()
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
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        with pytest.raises(ToolError):
            await _declare_phase_impl(ctx, {}, mutations=mutations)
        mutations.save_combat_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_beat_raises(self):
        mutations = _make_mutations()
        ctx = _make_context()
        cs = _make_combat_state()
        cs.beat = "resolution"  # not the declaration beat
        ctx.userdata.combat_state = cs

        with pytest.raises(ToolError, match="declaration beat"):
            await _declare_phase_impl(ctx, _declarations(), mutations=mutations)
        mutations.save_combat_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_in_combat_raises(self):
        ctx = _make_context()  # no combat_state

        with pytest.raises(ToolError, match="Not in combat"):
            await _declare_phase_impl(ctx, _declarations())


class TestResolvePhaseNonEnding:
    @pytest.mark.asyncio
    async def test_resolves_packets_in_initiative_order_and_loops(self):
        deps = _resolve_deps(damage=3)
        ctx = _make_context()
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
        ctx = _make_context()
        ctx.userdata.combat_state = _resolution_state()

        await _resolve_phase_impl(ctx, **deps)

        # The player's weapon swung this encounter (end_combat reads this for durability).
        assert ctx.userdata.weapon_used_this_encounter is True

    @pytest.mark.asyncio
    async def test_wasted_when_target_already_fell(self):
        # A lower-initiative actor whose target was dropped earlier this phase is wasted,
        # not resolved. Engineer it: goblin dies to the player's strike (enemy_hp=3, dmg=3),
        # but the goblin's own declaration still targets the (living) player and resolves —
        # so instead assert the player's packet kills, and a second enemy's packet wasted.
        deps = _resolve_deps(damage=3)
        ctx = _make_context()
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
        cs.pending_declarations["goblin_scout_2"] = {"action": "Scimitar", "target_id": "goblin_scout_1"}
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
        ctx = _make_context()
        cs = _resolution_state()
        cs.beat = "declaration"  # not the resolution beat
        ctx.userdata.combat_state = cs

        with pytest.raises(ToolError, match="resolution beat"):
            await _resolve_phase_impl(ctx, **deps)
