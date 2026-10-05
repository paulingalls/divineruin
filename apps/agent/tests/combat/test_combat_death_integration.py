"""Companion auto-stabilization protects them from the death-save grind."""

from combat._helpers import _make_combat_state

import combat_phase
from combat_phase import _DEATH_SAVE_LIMIT, _STABILIZE_LIMIT, advance_combat_phase
from session_data import CombatParticipant, CombatState


def _with_companion(cs, *, failures: int, successes: int = 0):
    companion = CombatParticipant(
        id="companion_1",
        name="Sable",
        type="companion",
        initiative=10,
        hp_current=0,
        hp_max=18,
        ac=13,
        is_fallen=True,
        death_save_failures=failures,
        death_save_successes=successes,
    )
    cs.participants.append(companion)
    return companion


class TestCompanionAutoStabilize:
    def test_companion_at_failure_limit_is_clamped_to_stabilized(self):
        cs = _make_combat_state()
        companion = _with_companion(cs, failures=_DEATH_SAVE_LIMIT)

        combat_phase._wrap(cs)

        assert companion.death_save_successes == _STABILIZE_LIMIT
        assert companion.death_save_failures == _DEATH_SAVE_LIMIT - 1
        assert companion.is_dead is False
        assert companion.is_fallen is True  # stays down, just no longer dying

    def test_stabilized_companion_drops_out_of_death_saves_due(self):
        cs = _make_combat_state()
        _with_companion(cs, failures=_DEATH_SAVE_LIMIT)

        wrap = combat_phase._wrap(cs)
        assert "companion_1" not in wrap.death_saves_due

    def test_companion_failures_do_not_end_combat(self):
        cs = _make_combat_state()
        _with_companion(cs, failures=_DEATH_SAVE_LIMIT)

        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is False

    def test_companion_below_limit_is_untouched(self):
        cs = _make_combat_state()
        companion = _with_companion(cs, failures=1)

        wrap = combat_phase._wrap(cs)
        assert companion.death_save_failures == 1
        assert companion.death_save_successes == 0
        assert "companion_1" in wrap.death_saves_due  # still dying, still rolls


class TestDeathSaveCounterPersistence:
    def test_counters_survive_to_dict_from_dict_roundtrip(self):
        cs = _make_combat_state()
        player = cs.get_participant("player_1")
        assert player is not None
        player.is_fallen = True
        player.death_save_failures = 2
        player.death_save_successes = 1

        restored = CombatState.from_dict(cs.to_dict())
        rp = restored.get_participant("player_1")
        assert rp is not None
        assert rp.death_save_failures == 2
        assert rp.death_save_successes == 1
        assert rp.is_fallen is True


class TestInstantDeathE2E:
    def test_wrap_reports_instant_dead_player_and_stabilized_companion(self):
        cs = _make_combat_state()  # enemy still alive (hp 7) so victory does not pre-empt defeat
        player = cs.get_participant("player_1")
        assert player is not None
        player.is_fallen = True
        player.is_dead = True  # an overkill blow this round set this at the damage site
        player.death_save_failures = 0

        companion = CombatParticipant(
            id="companion_1",
            name="Sable",
            type="companion",
            initiative=10,
            hp_current=0,
            hp_max=18,
            ac=13,
            is_fallen=True,
            death_save_failures=_DEATH_SAVE_LIMIT,
        )
        cs.participants.append(companion)

        cs.beat = "wrap"
        next_state, advance = advance_combat_phase(cs)

        assert advance.wrap is not None
        assert advance.wrap.combat_ended is True
        assert advance.wrap.outcome == "defeat"
        assert "player_1" not in advance.wrap.death_saves_due

        stabilized = next_state.get_participant("companion_1")
        assert stabilized is not None
        assert stabilized.death_save_successes == _STABILIZE_LIMIT
        assert stabilized.is_dead is False
        assert "companion_1" not in advance.wrap.death_saves_due
