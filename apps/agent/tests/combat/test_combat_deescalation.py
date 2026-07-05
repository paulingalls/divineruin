"""Diplomat combat de-escalation MVP (M4.6a / story-004).

resolve_deescalation composes the spec's spine (gm_combat L175-183): a contested
CHA-vs-WIS gate enters the scene, then one argument round against a scene-local hostile
disposition decides whether combat ends. Every de-escalation roll is always-dramatic
(M4.5 ability="de_escalate"). The _wrap end-condition + combat_turn orchestration are
covered in the sibling test classes below.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import FixedRng

from combat_ability import _gate_deescalation, _resolve_deescalation_packet
from combat_phase import PhaseBeat, advance_combat_phase
from combat_resolution import DeescalationOutcome, resolve_deescalation
from conditions import apply_condition, has_condition
from declarations import DeclarationType
from session_data import CombatParticipant, CombatState
from tests.combat._helpers import _make_combat_state
from tools._helpers import SAMPLE_PLAYER

_DIPLOMAT = {**SAMPLE_PLAYER, "attributes": {**SAMPLE_PLAYER["attributes"], "charisma": 16}, "focus": {"current": 5}}


def _deescalation_session(enemy_fallen=False):
    session = MagicMock()
    session.player_id = "player_1"
    session.room = None
    session.event_bus = MagicMock()
    session.combat_state = _make_combat_state(enemy_fallen=enemy_fallen)
    session.record_event = MagicMock()
    return session


_DECL = SimpleNamespace(type=DeclarationType.ABILITY, action="de_escalate", target_id="goblin_scout_1")


async def _run(session, player, rng):
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    attacker = session.combat_state.get_participant("player_1")
    result = await _resolve_deescalation_packet(
        session,
        attacker,
        _DECL,
        state=session.combat_state,
        conn=None,
        player=player,
        sink=None,
        persistence=persistence,
        rng=rng,
    )
    return result, persistence


class TestResolveDeescalation:
    # base_dc 15 + hostile modifier (+6) = effective argument DC 21.

    def test_contested_failure_does_not_enter_or_end(self):
        out = resolve_deescalation(cha_total=10, enemy_wis_total=14, argument_total=30)
        assert isinstance(out, DeescalationOutcome)
        assert not out.scene_entered
        assert not out.ends_combat
        assert not out.success

    def test_contested_tie_loses_to_the_enemy(self):
        # resolve_contested_social: player must BEAT the enemy; a tie does not enter.
        out = resolve_deescalation(cha_total=14, enemy_wis_total=14, argument_total=30)
        assert not out.scene_entered

    def test_entered_and_argument_succeeds_ends_combat(self):
        out = resolve_deescalation(cha_total=18, enemy_wis_total=10, argument_total=22)
        assert out.scene_entered
        assert out.ends_combat
        assert out.success

    def test_entered_but_argument_fails_does_not_end(self):
        out = resolve_deescalation(cha_total=18, enemy_wis_total=10, argument_total=12)
        assert out.scene_entered
        assert not out.ends_combat
        assert not out.success

    def test_always_dramatic_with_de_escalate_context(self):
        for cha, wis, arg in ((10, 14, 30), (18, 10, 22), (18, 10, 12)):
            out = resolve_deescalation(cha_total=cha, enemy_wis_total=wis, argument_total=arg)
            assert out.dramatic
            assert out.context == "de_escalate"

    def test_every_outcome_carries_a_cue(self):
        for cha, wis, arg in ((10, 14, 30), (18, 10, 22), (18, 10, 12)):
            out = resolve_deescalation(cha_total=cha, enemy_wis_total=wis, argument_total=arg)
            assert out.narrative_cue

    def test_base_dc_and_disposition_shift_the_argument_threshold(self):
        # A friendlier scene disposition (lower modifier) makes the same argument land.
        hostile = resolve_deescalation(cha_total=18, enemy_wis_total=10, argument_total=16)
        friendly = resolve_deescalation(
            cha_total=18, enemy_wis_total=10, argument_total=16, enemy_disposition="neutral"
        )
        assert not hostile.ends_combat  # 16 < 15 + 6
        assert friendly.ends_combat  # 16 >= 15 + 0


class TestWrapDeescalationEndCondition:
    def _wrap_of(self, state):
        _, advance = advance_combat_phase(state)
        assert advance.wrap is not None
        return advance.wrap

    def test_deescalated_ends_combat_while_enemies_still_stand(self):
        # Precedence: the enemy is alive (no victory), yet a landed argument ends combat.
        state = _make_combat_state(enemy_fallen=False)
        state.beat = PhaseBeat.WRAP
        state.deescalated = True
        wrap = self._wrap_of(state)
        assert wrap.combat_ended
        assert wrap.outcome == "deescalated"

    def test_no_deescalation_leaves_ongoing_combat_unchanged(self):
        state = _make_combat_state(enemy_fallen=False)
        state.beat = PhaseBeat.WRAP
        wrap = self._wrap_of(state)
        assert not wrap.combat_ended
        assert wrap.outcome is None

    def test_no_deescalation_still_resolves_victory(self):
        # Regression: the existing all-enemies-fallen victory path is untouched.
        state = _make_combat_state(enemy_fallen=True)
        state.beat = PhaseBeat.WRAP
        wrap = self._wrap_of(state)
        assert wrap.combat_ended
        assert wrap.outcome == "victory"


class TestParticipantResistanceTags:
    """M15 story-002: CombatParticipant carries the per-enemy Tier-3 resistance_tags,
    loaded at combat init and serialized like enhancers/conditions."""

    def test_resistance_tags_round_trip(self):
        state = _make_combat_state()
        enemy = state.get_participant("goblin_scout_1")
        assert enemy is not None
        enemy.resistance_tags = ["pragmatic", "suspicious"]
        rebuilt = CombatState.from_dict(state.to_dict())
        rebuilt_enemy = rebuilt.get_participant("goblin_scout_1")
        assert rebuilt_enemy is not None
        assert rebuilt_enemy.resistance_tags == ["pragmatic", "suspicious"]

    def test_legacy_row_without_field_defaults_empty(self):
        # A participant row written before the field existed omits it; from_dict rebuilds via
        # CombatParticipant(**p), so the default_factory covers the missing key.
        state = _make_combat_state()
        data = state.to_dict()
        for p in data["participants"]:
            p.pop("resistance_tags", None)
        rebuilt = CombatState.from_dict(data)
        rebuilt_enemy = rebuilt.get_participant("goblin_scout_1")
        assert rebuilt_enemy is not None
        assert rebuilt_enemy.resistance_tags == []

    def test_default_is_empty_list(self):
        assert (
            CombatParticipant(
                id="e", name="E", type="enemy", initiative=1, hp_current=1, hp_max=1, ac=1
            ).resistance_tags
            == []
        )


class TestGateDeescalation:
    """M15 story-002: the once-per-encounter MVP lockout became a per-round cap (MAX 4 rounds);
    Focus (3) is still gated per round, with NO state writes at declare time."""

    def test_round_cap_blocks_further_attempts(self):
        state = _make_combat_state()
        state.deescalation_scene.round_counter = 4  # MAX_DEESCALATION_ROUNDS
        with pytest.raises(ToolError, match="stopped listening"):
            _gate_deescalation(_DIPLOMAT, state)

    def test_insufficient_focus_fails_loud(self):
        state = _make_combat_state()
        broke = {**_DIPLOMAT, "focus": {"current": 2}}
        with pytest.raises(ToolError, match="Focus"):
            _gate_deescalation(broke, state)

    def test_affordable_first_round_passes(self):
        _gate_deescalation(_DIPLOMAT, _make_combat_state())  # round_counter 0 -> no raise


class TestResolveDeescalationPacket:
    """M15 story-002: the packet resolves ONE round of a group argument — spends Focus, rolls one
    persuasion total, shifts each living enemy independently, advances round_counter, and emits an
    always-dramatic de_escalate roll. Whole-group surrender (ends_combat True) is covered in
    tests/combat/test_deescalation_orchestration.py; here a single hostile no-tag enemy needs more
    than one round, so this round ends_combat False."""

    @pytest.mark.asyncio
    async def test_spends_focus_and_emits_dramatic_dice_roll(self):
        session = _deescalation_session()
        result, persistence = await _run(session, _DIPLOMAT, FixedRng(20))
        assert result["resolved"]
        persistence.update_player_resources.assert_awaited_once()
        assert persistence.update_player_resources.await_args.kwargs["focus"] == 2  # 5 - 3
        events = [c.args[0] for c in session.event_bus.publish.call_args_list]
        dice = next(e for e in events if e.payload.get("roll_type") == "de_escalate")
        assert dice.payload["dramatic"] and dice.payload["context"] == "de_escalate"

    @pytest.mark.asyncio
    async def test_packet_reports_round_and_per_enemy_breakdown(self):
        session = _deescalation_session()
        result, _ = await _run(session, _DIPLOMAT, FixedRng(20))
        deesc = result["deescalation"]
        assert deesc["round"] == 1  # round_counter advanced
        assert deesc["ends_combat"] is False  # one hostile enemy can't cross +2 in a single round
        assert [pe["id"] for pe in deesc["per_enemy"]] == ["goblin_scout_1"]
        assert session.combat_state.deescalation_scene.round_counter == 1
        assert not session.combat_state.deescalated

    @pytest.mark.asyncio
    async def test_no_living_enemy_is_wasted(self):
        session = _deescalation_session(enemy_fallen=True)
        result, persistence = await _run(session, _DIPLOMAT, FixedRng(20))
        assert not result["resolved"]
        persistence.update_player_resources.assert_not_awaited()


class TestDeescalationBeneficialDie:
    """M4.8 story-011 carried into M15: de_escalate folds an Inspired ally's single-use +1d4 into
    its ONE per-round persuasion total and must consume it EXACTLY ONCE, sourced from the in-combat
    SSOT (the participant), not the stale DB row. FixedRng(9) fixes both the d20 AND the d4 to 9:
    the folded +1d4 lifts the round's argument_total, so the enemy's cumulative_shift is HIGHER with
    the die than the baseline — the observable proof the die folded and was read from the participant."""

    _ENEMY = "goblin_scout_1"

    async def _run_with(self, *, participant_conditions, db_row_conditions, rng):
        session = _deescalation_session()
        attacker = session.combat_state.get_participant("player_1")
        attacker.conditions = participant_conditions
        player = {**_DIPLOMAT, "conditions": db_row_conditions}
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        result = await _resolve_deescalation_packet(
            session,
            attacker,
            _DECL,
            state=session.combat_state,
            conn=None,
            player=player,
            sink=None,
            persistence=persistence,
            rng=rng,
        )
        shift = next(pe["cumulative_shift"] for pe in result["deescalation"]["per_enemy"] if pe["id"] == self._ENEMY)
        return shift, attacker

    @pytest.mark.asyncio
    async def test_inspired_on_participant_folds_and_is_consumed_once(self):
        # +1d4 lifts the argument_total, so the enemy softens more than baseline (delta 0 vs -1),
        # AND Inspired is removed from the participant exactly once (no permanent die).
        shift, attacker = await self._run_with(
            participant_conditions=apply_condition([], "inspired"),
            db_row_conditions=[],
            rng=FixedRng(9),
        )
        assert shift == 0  # 9 + cha_mod 3 + d4 9 = 21 vs hostile DC 21 -> margin 0 -> +0
        assert not has_condition(attacker.conditions, "inspired")

    @pytest.mark.asyncio
    async def test_no_beneficial_condition_baseline(self):
        # Same seed, no die: bare argument 12 vs hostile DC 21 -> margin -9 -> -1; conditions untouched.
        shift, attacker = await self._run_with(
            participant_conditions=[],
            db_row_conditions=[],
            rng=FixedRng(9),
        )
        assert shift == -1
        assert attacker.conditions == []

    @pytest.mark.asyncio
    async def test_stale_db_row_inspired_does_not_apply(self):
        # Guards the double-dip fix: an Inspired present only on the stale DB row (not the
        # participant) must NOT fold -> the enemy shifts by the baseline -1, proving the die is
        # read from the participant SSOT, not players.data.
        shift, attacker = await self._run_with(
            participant_conditions=[],
            db_row_conditions=apply_condition([], "inspired"),
            rng=FixedRng(9),
        )
        assert shift == -1
        assert attacker.conditions == []
