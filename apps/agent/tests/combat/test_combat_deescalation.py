"""Diplomat combat de-escalation MVP (M4.6a / story-004).

resolve_deescalation composes the spec's spine (gm_combat L175-183): a contested
CHA-vs-WIS gate enters the scene, then one argument round against a scene-local hostile
disposition decides whether combat ends. Every de-escalation roll is always-dramatic
(M4.5 ability="de_escalate"). The _wrap end-condition + combat_turn orchestration are
covered in the sibling test classes below.
"""

from combat_resolution import DeescalationOutcome, resolve_deescalation


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
