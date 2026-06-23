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
from declarations import DeclarationType
from tests.combat._helpers import _make_combat_state
from tools._helpers import SAMPLE_PLAYER

_DIPLOMAT = {**SAMPLE_PLAYER, "attributes": {**SAMPLE_PLAYER["attributes"], "charisma": 16}, "focus": {"current": 5}}
_TIMID = {**SAMPLE_PLAYER, "focus": {"current": 5}}  # charisma 8 -> negative modifier


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


class TestGateDeescalation:
    def test_lockout_after_one_attempt(self):
        state = _make_combat_state()
        state.deescalation_used = True
        with pytest.raises(ToolError, match="once per encounter"):
            _gate_deescalation(_DIPLOMAT, state)

    def test_insufficient_focus_fails_loud(self):
        state = _make_combat_state()
        broke = {**_DIPLOMAT, "focus": {"current": 2}}
        with pytest.raises(ToolError, match="Focus"):
            _gate_deescalation(broke, state)

    def test_affordable_first_attempt_passes(self):
        _gate_deescalation(_DIPLOMAT, _make_combat_state())  # no raise


class TestResolveDeescalationPacket:
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
        assert session.combat_state.deescalation_used

    @pytest.mark.asyncio
    async def test_success_sets_deescalated(self):
        # CHA 16 beats WIS 10 (enters), nat-20 argument clears the hostile DC -> ends combat.
        session = _deescalation_session()
        result, _ = await _run(session, _DIPLOMAT, FixedRng(20))
        assert result["deescalation"]["ends_combat"]
        assert session.combat_state.deescalated

    @pytest.mark.asyncio
    async def test_failed_argument_uses_attempt_without_ending(self):
        # Enters the scene (CHA>WIS) but a low argument roll misses the hostile DC.
        session = _deescalation_session()
        result, _ = await _run(session, _DIPLOMAT, FixedRng(3))
        assert result["deescalation"]["scene_entered"]
        assert not result["deescalation"]["ends_combat"]
        assert session.combat_state.deescalation_used
        assert not session.combat_state.deescalated

    @pytest.mark.asyncio
    async def test_contested_failure_does_not_enter(self):
        # Low CHA (8 -> -1) loses the contested gate; the enemy never pauses.
        session = _deescalation_session()
        result, _ = await _run(session, _TIMID, FixedRng(12))
        assert not result["deescalation"]["scene_entered"]
        assert session.combat_state.deescalation_used
        assert not session.combat_state.deescalated

    @pytest.mark.asyncio
    async def test_no_living_enemy_is_wasted(self):
        session = _deescalation_session(enemy_fallen=True)
        result, persistence = await _run(session, _DIPLOMAT, FixedRng(20))
        assert not result["resolved"]
        persistence.update_player_resources.assert_not_awaited()
