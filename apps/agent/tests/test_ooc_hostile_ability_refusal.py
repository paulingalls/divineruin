from unittest.mock import MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import ability_tools
from session_data import CombatState


@pytest.mark.asyncio
@pytest.mark.parametrize("in_combat", [False, True])
async def test_charge_refuses_before_transaction_or_lock(in_combat):
    context = make_context(party_member_ids=["player_1", "ally_1"])
    if in_combat:
        context.userdata.combat_state = CombatState(combat_id="charge", participants=[], initiative_order=[])
    db_mod = MagicMock()
    db_mod.transaction.side_effect = AssertionError("transaction opened")
    queries = MagicMock()

    with pytest.raises(ToolError, match="charge needs a foe"):
        await ability_tools._request_ability_activation_unlocked(
            context,
            "warrior_unstoppable_charge",
            target_id="ally_1",
            db_mod=db_mod,
            queries_mod=queries,
        )

    db_mod.transaction.assert_not_called()
    queries.get_players_for_update.assert_not_called()
