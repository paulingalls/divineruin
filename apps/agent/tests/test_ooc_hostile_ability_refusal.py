from unittest.mock import MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import ability_tools


@pytest.mark.asyncio
async def test_charge_refuses_before_transaction_or_lock():
    context = make_context(party_member_ids=["player_1", "ally_1"])
    db_mod = MagicMock()
    db_mod.transaction.side_effect = AssertionError("transaction opened")
    queries = MagicMock()

    with pytest.raises(ToolError, match="Charge needs a foe — use it in a fight"):
        await ability_tools._request_ability_activation_impl(
            context,
            "warrior_unstoppable_charge",
            target_id="ally_1",
            db_mod=db_mod,
            queries_mod=queries,
        )

    db_mod.transaction.assert_not_called()
    queries.get_players_for_update.assert_not_called()
