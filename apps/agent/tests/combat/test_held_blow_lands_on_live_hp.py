"""A pause gives the DM a turn to change HP. Apply held damage to live HP, not the roll-time snapshot."""

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
    """The pause and Inner Fire are sequential; a lock cannot fix a later write based on stale roll-time HP."""

    @pytest.mark.asyncio
    async def test_hp_spent_during_the_pause_is_not_healed_back_by_the_held_blow(self):
        ctx = _ctx_at_resolution(player_hp=25, enemy_hp=20, reaction_ids=("skirmisher_sidestep", "rogue_uncanny_dodge"))
        deps = _deps()

        await _call(ctx, deps)  # the ally commit; the enemy blow is held
        await _call(ctx, deps)  # the pre-roll window
        await _call(ctx, deps)  # the roll happens; the damage is still held
        assert _p(ctx).hp_current == 25, "the held blow must not have landed yet"

        _p(ctx).hp_current = 19

        await _call(ctx, deps)  # the window closes and the held blow lands

        assert _p(ctx).hp_current == 16
        assert deps["mutations"].update_player_hp.await_args.args[1] == 16

    @pytest.mark.asyncio
    async def test_the_fall_verdict_is_computed_against_the_hp_the_target_actually_has(self):
        """Leave the target at 2 HP so the wasted-action gate cannot suppress the held apply and hide this defect."""
        ctx = _ctx_at_resolution(player_hp=25, enemy_hp=20, reaction_ids=("skirmisher_sidestep", "rogue_uncanny_dodge"))
        deps = _deps()

        for _ in range(3):
            await _call(ctx, deps)
        _p(ctx).hp_current = 2  # the burn left them standing, but only just

        await _call(ctx, deps)

        assert _p(ctx).hp_current == 0
        assert _p(ctx).is_fallen is True
