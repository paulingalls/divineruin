from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context, make_db_mod

import combat_resolution
import creation_deities
from combat_death_save import _request_death_save_impl
from dice import DiceResult


def _death_save_mutations():
    """Mock mutations for _request_death_save_impl — keeps the tool off the real DB."""
    m = MagicMock()
    m.save_combat_state = AsyncMock()
    m.update_player_hp = AsyncMock()
    return m


def _force_roll(value: int):
    """Patch combat_resolution.dice_roll to a fixed d20 value."""
    return patch(
        "combat_resolution.dice_roll",
        return_value=DiceResult(notation="d20", rolls=[value], dropped=[], total=value),
    )


class TestDeathSaveBonus:
    def test_bonus_flips_a_marginal_failure_to_success(self):
        with _force_roll(8):
            base = combat_resolution.resolve_death_save(0, 0)
            boosted = combat_resolution.resolve_death_save(0, 0, bonus=2)
        assert base.success is False
        assert boosted.success is True
        assert base.roll == 8 and boosted.roll == 8

    def test_bonus_does_not_change_crit_success_or_failure(self):
        with _force_roll(20):
            crit = combat_resolution.resolve_death_save(0, 0, bonus=2)
        assert crit.critical_success is True
        with _force_roll(1):
            fail = combat_resolution.resolve_death_save(0, 0, bonus=2)
        assert fail.critical_failure is True and fail.total_failures == 2

    def test_default_bonus_is_zero_backward_compatible(self):
        with _force_roll(9):
            result = combat_resolution.resolve_death_save(0, 0)
        assert result.success is False  # 9 < 10, no bonus


class TestPatronHooks:
    def test_mortaen_gets_plus_two_death_save_bonus(self):
        assert creation_deities.patron_death_save_bonus("mortaen") == 2

    def test_non_patron_gets_no_death_save_bonus(self):
        assert creation_deities.patron_death_save_bonus("none") == 0
        assert creation_deities.patron_death_save_bonus("kaelen") == 0

    def test_mortaen_first_ever_death_is_waived(self):
        assert creation_deities.patron_waives_first_death("mortaen", 0) is True

    def test_mortaen_second_death_is_not_waived(self):
        assert creation_deities.patron_waives_first_death("mortaen", 1) is False

    def test_non_patron_first_death_is_not_waived(self):
        assert creation_deities.patron_waives_first_death("none", 0) is False
        assert creation_deities.patron_waives_first_death("kaelen", 0) is False


class TestDeathSaveBonusWiredLive:
    @pytest.mark.asyncio
    async def test_mortaen_session_applies_plus_two(self):
        ctx = make_context()
        ctx.userdata.patron_id = "mortaen"
        ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

        with patch(
            "combat_death_save.combat_resolution.resolve_death_save",
            wraps=combat_resolution.resolve_death_save,
        ) as spy:
            await _request_death_save_impl(ctx, mutations=_death_save_mutations(), db_mod=make_db_mod()[0])

        assert spy.call_args.kwargs.get("bonus") == 2

    @pytest.mark.asyncio
    async def test_non_patron_session_applies_no_bonus(self):
        ctx = make_context()
        ctx.userdata.patron_id = "none"
        ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

        with patch(
            "combat_death_save.combat_resolution.resolve_death_save",
            wraps=combat_resolution.resolve_death_save,
        ) as spy:
            await _request_death_save_impl(ctx, mutations=_death_save_mutations(), db_mod=make_db_mod()[0])

        assert spy.call_args.kwargs.get("bonus", 0) == 0
