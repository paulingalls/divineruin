"""Tests for request_death_save: success/stabilize/death, nat-20 revive, nat-1, errors, events."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _make_combat_state, _make_context, _make_mock_room
from livekit.agents.llm import ToolError

import event_types as E
from combat_turn import _request_death_save_impl


def _make_death_save_mocks():
    """Create mock modules for request_death_save DI params."""
    mock_mutations = MagicMock()
    mock_mutations.save_combat_state = AsyncMock()
    mock_mutations.update_player_hp = AsyncMock()
    return mock_mutations


class TestRequestDeathSave:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_mutations = _make_death_save_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

        result = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations))

        assert "roll" in result
        assert "success" in result
        assert "total_successes" in result
        assert "total_failures" in result
        mock_mutations.save_combat_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_nat_20_restores_hp(self):
        """If we get a nat 20, player should be revived with 1 HP."""
        mock_mutations = _make_death_save_mocks()

        import random

        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                # We need to patch dice.roll to use this seed
                break
        else:
            pytest.skip("Could not find seed for nat 20")

        with patch("combat_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[20], dropped=[], total=20)

            ctx = _make_context()
            ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

            result = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations))

            assert result["critical_success"] is True
            assert result["revived"] is True
            mock_mutations.update_player_hp.assert_called_once_with("player_1", 1)

            # Player should no longer be fallen
            player = ctx.userdata.combat_state.participants[0]
            assert player.is_fallen is False
            assert player.hp_current == 1

    @pytest.mark.asyncio
    async def test_nat_1_double_fail(self):
        mock_mutations = _make_death_save_mocks()

        with patch("combat_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[1], dropped=[], total=1)

            ctx = _make_context()
            ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

            result = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations))

            assert result["critical_failure"] is True
            assert result["total_failures"] == 2

    @pytest.mark.asyncio
    async def test_stabilize(self):
        mock_mutations = _make_death_save_mocks()

        with patch("combat_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[15], dropped=[], total=15)

            ctx = _make_context()
            cs = _make_combat_state(player_hp=0, player_fallen=True)
            # Set 2 existing successes
            cs.participants[0].death_save_successes = 2
            ctx.userdata.combat_state = cs

            result = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations))

            assert result["stabilized"] is True
            assert result["total_successes"] == 3

    @pytest.mark.asyncio
    async def test_death(self):
        mock_mutations = _make_death_save_mocks()

        with patch("combat_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[5], dropped=[], total=5)

            ctx = _make_context()
            cs = _make_combat_state(player_hp=0, player_fallen=True)
            cs.participants[0].death_save_failures = 2
            ctx.userdata.combat_state = cs

            result = json.loads(await _request_death_save_impl(ctx, mutations=mock_mutations))

            assert result["dead"] is True
            assert result["total_failures"] == 3

    @pytest.mark.asyncio
    async def test_error_if_not_fallen(self):
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state(player_hp=25, player_fallen=False)

        with pytest.raises(ToolError, match="not fallen"):
            await _request_death_save_impl(ctx)

    @pytest.mark.asyncio
    async def test_error_if_not_in_combat(self):
        ctx = _make_context()

        with pytest.raises(ToolError, match="Not in combat"):
            await _request_death_save_impl(ctx)

    @pytest.mark.asyncio
    async def test_publishes_events(self):
        mock_mutations = _make_death_save_mocks()
        room = _make_mock_room()
        ctx = _make_context(room=room)
        ctx.userdata.combat_state = _make_combat_state(player_hp=0, player_fallen=True)

        await _request_death_save_impl(ctx, mutations=mock_mutations)

        # dice_roll event + at least one play_sound
        assert room.local_participant.publish_data.call_count >= 2
        calls = [json.loads(c[0][0]) for c in room.local_participant.publish_data.call_args_list]
        types = [c["type"] for c in calls]
        assert E.DICE_ROLL in types
        death_save_event = next(c for c in calls if c.get("type") == E.DICE_ROLL)
        assert death_save_event["roll_type"] == "death_save"
