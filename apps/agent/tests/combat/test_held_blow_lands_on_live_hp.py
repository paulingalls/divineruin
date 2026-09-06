"""A held blow lands on the HP the target HAS, not the HP the roll was made against.

The Beat-3 hold (M29, story-016) captures an ABSOLUTE ``target_hp_remaining`` when it rolls and
applies it when the window closes, which is a whole DM turn later. story-018 recorded that as
harmless on the grounds that "nothing at NARRATION mutates a standing target's HP between the
pause and the apply" — but a pause hands the floor back to the DM, and the combat prompt names
Inner Fire as one of exactly three things the DM may activate mid-fight. ``draethar_inner_fire``
writes that participant's ``hp_current`` directly, so the premise is false at the seam between
story-016's hold and story-026's self-damage door.

The end-to-end version of the same claim, driving the REAL Inner Fire tool against a REAL pause,
is ``tests/test_draethar_inner_fire.py::test_inner_fire_at_a_pause_is_not_undone_by_the_held_blow``.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _call, _ctx_at_resolution, _resolve_deps


def _deps(damage=3):
    """resolve_phase deps plus the resonance module the WRAP's per-member decay writes through."""
    deps = _resolve_deps(damage=damage)
    deps["resonance_mutations"] = MagicMock(update_player_resonance=AsyncMock())
    return deps


def _p(ctx, participant_id="player_1"):
    """Re-read the participant AFTER a call: resolve_phase adopts a deep copy each time, so a
    reference captured earlier is stale and every assertion on it passes vacuously."""
    return ctx.userdata.combat_state.get_participant(participant_id)


class TestTheHeldBlowLandsOnLiveHp:
    """A pause is a return to the DM, and the DM may spend the pause changing the target's HP.

    The roll persists an ABSOLUTE ``target_hp_remaining`` (combat_support.serialize_roll), and the
    apply half writes it to ``hp_current``. story-018 recorded that as harmless because "nothing at
    NARRATION mutates a standing target's HP between the pause and the apply" — but the combat
    prompt names Inner Fire as one of exactly three things the DM may activate mid-fight, and
    ``draethar_inner_fire`` writes that participant's ``hp_current`` directly. So the premise is
    false at the seam between story-016's hold and story-026's self-damage door, and the blow
    lands from the HP the roll was made against rather than the HP the target actually has.

    The lock story-026 owes changes nothing here: the pause has already returned, so Inner Fire and
    the held blow never overlap — they are strictly ordered, and the second one overwrites.
    """

    @pytest.mark.asyncio
    async def test_hp_spent_during_the_pause_is_not_healed_back_by_the_held_blow(self):
        ctx = _ctx_at_resolution(player_hp=25, enemy_hp=20)
        deps = _deps()

        await _call(ctx, deps)  # the ally commit; the enemy blow is held
        await _call(ctx, deps)  # the pre-roll window
        await _call(ctx, deps)  # the roll happens; the damage is still held
        assert _p(ctx).hp_current == 25, "the held blow must not have landed yet"

        # Inner Fire at the pause: 6 self-damage, written straight onto the live participant.
        _p(ctx).hp_current = 19

        await _call(ctx, deps)  # the window closes and the held blow lands

        # 19 - 3, never 25 - 3: the burn is not undone by a blow rolled before it.
        assert _p(ctx).hp_current == 16
        # ...and players.data agrees, because it is written from the same number.
        assert deps["mutations"].update_player_hp.await_args.args[1] == 16

    @pytest.mark.asyncio
    async def test_the_fall_verdict_is_computed_against_the_hp_the_target_actually_has(self):
        """The sharp end of the same defect. A blow that is survivable from full HP is lethal from
        2, and which of those it is has to be decided when the damage LANDS, not when it was rolled
        — ``_handle_hp_zero`` only runs on the number the apply half writes. Left stale, the burned
        Draethar is stood back up at 22 of 25 and never falls, so nothing owes them a death save.

        The target is at 2 rather than 0: a target already fallen at the pause makes the held
        action WASTED (``combat_hold._is_wasted``), which suppresses the apply for its own reason
        and would leave this guard passing whatever the apply half does.
        """
        ctx = _ctx_at_resolution(player_hp=25, enemy_hp=20)
        deps = _deps()

        for _ in range(3):
            await _call(ctx, deps)
        _p(ctx).hp_current = 2  # the burn left them standing, but only just

        await _call(ctx, deps)

        assert _p(ctx).hp_current == 0
        assert _p(ctx).is_fallen is True
