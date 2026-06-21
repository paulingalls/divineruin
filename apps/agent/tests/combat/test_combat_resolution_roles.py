"""M4.7 encounter-role overlay — XP regression guard + Boss legendary-action runtime (story-003).

Two engine concerns, both pure/synchronous:

1. XP applied EXACTLY ONCE. story-001 already scales each enemy's ``xp_value`` by the role
   ``xp_mult`` at combat init (``encounter_roles.derive_role_stats``). ``calculate_combat_xp``
   merely SUMS those pre-scaled values; these tests pin that it never re-multiplies (a Boss is
   worth x2 its base XP, not x4).

2. Boss legendary actions. A Boss has a 1/round legendary-action budget. The phase engine resets
   it at the WRAP loop-back and surfaces the available legendary on ``PhaseAdvance`` for the DM to
   narrate (never auto-fired); ``consume_legendary_action`` spends it and fails loud on overspend.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver, _fake_db_mod
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

from combat_phase import (
    PhaseBeat,
    advance_combat_phase,
    consume_legendary_action,
)
from combat_resolution import calculate_combat_xp
from combat_turn import _consume_legendary_action_impl, _resolve_phase_impl
from encounter_roles import EncounterRole, derive_role_stats
from session_data import CombatParticipant, CombatState


def _boss_combat_state(*, boss_legendary=1, boss_fallen=False, enemy_fallen=False):
    """A CombatState parked at WRAP with a living player, a Boss enemy, and a Standard enemy.
    The Boss carries the role-overlay fields derive_role_stats sets at init."""
    return CombatState(
        combat_id="combat_boss123",
        participants=[
            CombatParticipant(
                id="player_1",
                name="Kael",
                type="player",
                initiative=15,
                hp_current=25,
                hp_max=25,
                ac=14,
            ),
            CombatParticipant(
                id="warlord_1",
                name="Hollow Warlord",
                type="enemy",
                initiative=12,
                hp_current=40,
                hp_max=40,
                ac=15,
                xp_value=200,  # already x2 from a base of 100 at init
                role=EncounterRole.BOSS,
                legendary_actions=boss_legendary,
                signature_ability={"name": "Sundering Roar", "damage": "3d6"},
                is_fallen=boss_fallen,
            ),
            CombatParticipant(
                id="grunt_1",
                name="Hollow Grunt",
                type="enemy",
                initiative=8,
                hp_current=7,
                hp_max=7,
                ac=12,
                xp_value=50,
                role=EncounterRole.STANDARD,
                is_fallen=enemy_fallen,
            ),
        ],
        initiative_order=["player_1", "warlord_1", "grunt_1"],
        round_number=1,
        beat=PhaseBeat.WRAP,
    )


class TestCombatXpAppliedOnce:
    """Regression guard: the role xp_mult is applied ONCE (at init via derive_role_stats);
    calculate_combat_xp sums the pre-scaled values without re-multiplying."""

    def test_boss_xp_is_summed_not_re_multiplied(self):
        # derive_role_stats already turned base 100 into 200 (x2). calculate_combat_xp must
        # report 200 — NOT 400 (the double-count bug a naive re-multiply would produce).
        derived = derive_role_stats({"xp_value": 100}, EncounterRole.BOSS)
        assert derived["xp_value"] == 200

        enemy_dicts = [{"xp_value": derived["xp_value"]}]
        assert calculate_combat_xp(enemy_dicts) == 200

    def test_mixed_roster_sums_each_pre_scaled_value(self):
        # Boss (100 base -> 200) + Minion (80 base -> 40, x0.5) + Standard (50 -> 50).
        boss = derive_role_stats({"xp_value": 100}, EncounterRole.BOSS)
        minion = derive_role_stats({"xp_value": 80}, EncounterRole.MINION)
        standard = derive_role_stats({"xp_value": 50}, EncounterRole.STANDARD)
        assert (boss["xp_value"], minion["xp_value"], standard["xp_value"]) == (200, 40, 50)

        roster = [{"xp_value": boss["xp_value"]}, {"xp_value": minion["xp_value"]}, {"xp_value": standard["xp_value"]}]
        # Sum of the pre-scaled values: 200 + 40 + 50 = 290. Re-multiplying any role would break this.
        assert calculate_combat_xp(roster) == 290

    def test_participant_xp_value_feeds_calculate_unchanged(self):
        # The end_combat path feeds {"xp_value": participant.xp_value} straight through; the
        # participant already holds the scaled value, so the total equals the raw participant sum.
        state = _boss_combat_state()
        enemy_dicts = [{"xp_value": p.xp_value} for p in state.participants if p.type == "enemy"]
        assert calculate_combat_xp(enemy_dicts) == 250  # 200 (boss) + 50 (standard grunt)


class TestLegendaryActionReset:
    """A Boss's legendary budget refreshes to 1 at the WRAP loop-back; a non-Boss has 0."""

    def test_boss_budget_resets_to_one_on_non_ending_wrap(self):
        # Boss spent its legendary this round (budget 0); the WRAP into the next round refreshes it.
        state = _boss_combat_state(boss_legendary=0)
        next_state, advance = advance_combat_phase(state)

        assert advance.wrap is not None and advance.wrap.combat_ended is False
        assert next_state.beat == PhaseBeat.DECLARATION  # looped to the next round
        boss = next_state.get_participant("warlord_1")
        assert boss is not None and boss.legendary_actions == 1

    def test_non_boss_enemy_has_no_legendary_budget(self):
        state = _boss_combat_state(boss_legendary=0)
        next_state, _ = advance_combat_phase(state)

        grunt = next_state.get_participant("grunt_1")
        player = next_state.get_participant("player_1")
        assert grunt is not None and grunt.legendary_actions == 0
        assert player is not None and player.legendary_actions == 0

    def test_available_boss_legendary_surfaced_on_phase_advance(self):
        state = _boss_combat_state(boss_legendary=0)
        _, advance = advance_combat_phase(state)

        assert len(advance.legendary_available) == 1
        surfaced = advance.legendary_available[0]
        assert surfaced["actor_id"] == "warlord_1"
        assert surfaced["legendary_actions"] == 1  # reflects the post-reset budget
        assert surfaced["signature_ability"] == {"name": "Sundering Roar", "damage": "3d6"}

    def test_fallen_boss_is_not_reset_or_surfaced(self):
        # A downed Boss takes no legendary actions: skipped by the reset, absent from the surface.
        # The standard grunt is still up, so combat continues (non-ending wrap).
        state = _boss_combat_state(boss_legendary=0, boss_fallen=True)
        next_state, advance = advance_combat_phase(state)

        assert advance.wrap is not None and advance.wrap.combat_ended is False
        boss = next_state.get_participant("warlord_1")
        assert boss is not None and boss.legendary_actions == 0
        assert advance.legendary_available == []

    def test_terminal_wrap_surfaces_no_legendary(self):
        # All enemies down -> victory ends combat; no next round, so nothing is surfaced or reset.
        state = _boss_combat_state(boss_legendary=0, boss_fallen=True, enemy_fallen=True)
        next_state, advance = advance_combat_phase(state)

        assert advance.wrap is not None and advance.wrap.combat_ended is True
        assert advance.wrap.outcome == "victory"
        assert advance.legendary_available == []
        # The ending wrap does not loop back, so it does not run the budget reset either.
        boss = next_state.get_participant("warlord_1")
        assert boss is not None and boss.legendary_actions == 0


class TestConsumeLegendaryAction:
    """The DM spends a Boss legendary via consume_legendary_action — decrement on use, fail loud."""

    def test_consume_decrements_the_boss_budget(self):
        state = _boss_combat_state(boss_legendary=1)
        after = consume_legendary_action(state, "warlord_1")

        boss = after.get_participant("warlord_1")
        assert boss is not None and boss.legendary_actions == 0

    def test_consume_is_pure_and_does_not_mutate_input(self):
        state = _boss_combat_state(boss_legendary=1)
        before = state.to_dict()

        consume_legendary_action(state, "warlord_1")

        assert state.to_dict() == before  # input untouched; a new state was returned

    def test_second_consume_in_same_round_fails_loud(self):
        state = _boss_combat_state(boss_legendary=1)
        after = consume_legendary_action(state, "warlord_1")

        with pytest.raises(ValueError, match="no legendary action remaining"):
            consume_legendary_action(after, "warlord_1")

    def test_consume_on_non_boss_fails_loud(self):
        state = _boss_combat_state()
        with pytest.raises(ValueError, match="not a Boss"):
            consume_legendary_action(state, "grunt_1")

    def test_consume_on_unknown_participant_fails_loud(self):
        state = _boss_combat_state()
        with pytest.raises(ValueError, match="unknown participant"):
            consume_legendary_action(state, "no_such_id")


def _boss_resolution_state(*, boss_hp=40):
    """A RESOLUTION-beat state (player + living Boss, declarations pending) so driving
    _resolve_phase_impl loops back to the next round and surfaces the Boss's refreshed legendary."""
    return CombatState(
        combat_id="combat_boss_live",
        participants=[
            CombatParticipant(
                id="player_1",
                name="Kael",
                type="player",
                initiative=15,
                hp_current=25,
                hp_max=25,
                ac=14,
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
            ),
            CombatParticipant(
                id="warlord_1",
                name="Hollow Warlord",
                type="enemy",
                initiative=12,
                hp_current=boss_hp,
                hp_max=boss_hp,
                ac=15,
                xp_value=200,
                role=EncounterRole.BOSS,
                legendary_actions=1,
                signature_ability={"name": "Sundering Roar", "damage": "3d6"},
                action_pool=[{"name": "Cleaver", "damage": "1d10", "damage_type": "slashing", "properties": []}],
            ),
        ],
        initiative_order=["player_1", "warlord_1"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="resolution",
        pending_declarations={
            "player_1": {"type": "attack", "action": "Longsword", "target_id": "warlord_1"},
            "warlord_1": {"type": "attack", "action": "Cleaver", "target_id": "player_1"},
        },
    )


def _resolve_deps(damage=3):
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])
    queries.get_player = AsyncMock(return_value={"player_id": "player_1", "focus": {"current": 10, "max": 10}})
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
    mutations = MagicMock()
    mutations.save_combat_state = AsyncMock()
    mutations.update_player_hp = AsyncMock()
    mutations.delete_combat_state = AsyncMock()
    return {
        "mutations": mutations,
        "queries": queries,
        "resolver": _damage_resolver(damage),
        "concentration_break_mod": break_mod,
        "db_mod": _fake_db_mod(),
    }


class TestResolvePhaseSurfacesLegendary:
    """story-009: the LIVE resolve_phase response surfaces legendary_available so the Boss beat
    reaches the DM. The pure engine surfaced it on PhaseAdvance, but combat_turn used to drop it."""

    @pytest.mark.asyncio
    async def test_continuing_round_response_lists_living_boss_legendary(self):
        ctx = make_context()
        ctx.userdata.combat_state = _boss_resolution_state(boss_hp=40)

        raw = await _resolve_phase_impl(ctx, **_resolve_deps(damage=3))
        assert isinstance(raw, str), "the Boss survives 3 damage, so combat continues (not a handoff)"
        result = json.loads(raw)

        surfaced = result["legendary_available"]
        assert [s["actor_id"] for s in surfaced] == ["warlord_1"]
        assert surfaced[0]["legendary_actions"] == 1  # refreshed at the wrap loop-back


class TestConsumeLegendaryActionTool:
    """story-009: the consume_legendary_action TOOL wraps the pure fn — decrements + persists the
    SSOT, and surfaces the engine's fail-loud as a ToolError so the DM re-prompts."""

    @pytest.mark.asyncio
    async def test_tool_decrements_and_persists(self):
        ctx = make_context()
        ctx.userdata.combat_state = _boss_combat_state(boss_legendary=1)
        mutations = MagicMock()
        mutations.save_combat_state = AsyncMock()

        raw = await _consume_legendary_action_impl(ctx, "warlord_1", mutations=mutations)

        assert json.loads(raw) == {"actor_id": "warlord_1", "legendary_actions_remaining": 0}
        boss = ctx.userdata.combat_state.get_participant("warlord_1")
        assert boss is not None and boss.legendary_actions == 0
        mutations.save_combat_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tool_overspend_raises_toolerror(self):
        ctx = make_context()
        ctx.userdata.combat_state = _boss_combat_state(boss_legendary=0)
        mutations = MagicMock()
        mutations.save_combat_state = AsyncMock()

        with pytest.raises(ToolError, match="no legendary action remaining"):
            await _consume_legendary_action_impl(ctx, "warlord_1", mutations=mutations)
        mutations.save_combat_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tool_on_non_boss_raises_toolerror(self):
        ctx = make_context()
        ctx.userdata.combat_state = _boss_combat_state()
        mutations = MagicMock()
        mutations.save_combat_state = AsyncMock()

        with pytest.raises(ToolError, match="not a Boss"):
            await _consume_legendary_action_impl(ctx, "grunt_1", mutations=mutations)
