from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from worker_suite._helpers import txn_db
from worker_suite._samples import SAMPLE_PLAYER

from async_worker_training import apply_skill_practice_advancement


class TestSkillAccrualIdempotency:
    @pytest.mark.asyncio
    async def test_skips_increment_when_already_claimed(self):
        training = AsyncMock()
        training.claim_training_accrual = AsyncMock(return_value=False)
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        with patch("async_worker_training.skill_persistence.apply_skill_use_with_persistence") as mock_apply:
            result = await apply_skill_practice_advancement(
                "player_1", "perception", 2, "train_x", db_mod=txn_db(), queries=queries, training=training
            )
        assert result is None
        training.claim_training_accrual.assert_awaited_once()
        assert training.claim_training_accrual.await_args.args[0] == "train_x"
        queries.get_player.assert_not_awaited()
        mock_apply.assert_not_called()

    @pytest.mark.asyncio
    async def test_applies_increment_on_fresh_claim(self):
        training = AsyncMock()
        training.claim_training_accrual = AsyncMock(return_value=True)
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        adv = MagicMock(advanced=True, new_tier="journeyman")
        with patch(
            "async_worker_training.skill_persistence.apply_skill_use_with_persistence",
            new_callable=AsyncMock,
            return_value=adv,
        ) as mock_apply:
            result = await apply_skill_practice_advancement(
                "player_1", "athletics", 2, "train_y", db_mod=txn_db(), queries=queries, training=training
            )

        assert result == {"advanced": True, "new_tier": "journeyman"}
        queries.get_player.assert_awaited_once_with("player_1", conn=ANY)
        assert mock_apply.await_args is not None
        assert mock_apply.await_args.kwargs["initial_tier"] == "trained"
