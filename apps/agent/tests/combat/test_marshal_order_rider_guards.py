"""Reject corrupt order riders at the persisted combat loading boundary."""

from copy import deepcopy

import pytest
from combat.test_marshal_direct_strike import arrange, order, round_packets
from combat.test_marshal_orders import marshal as marshal
from combat.test_marshal_orders import mock_combat_agent_factory as mock_combat_agent_factory

import db_mutations


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recipient", "unknown"),
        ("list", {}),
        ("duplicate", None),
        ("extra", 1),
        ("kind", "unknown"),
        ("order_id", "unknown"),
        ("source_id", "unknown"),
        ("target_id", "unknown"),
        ("expires_round", True),
    ],
    ids=[
        "recipient",
        "list",
        "duplicate",
        "extra",
        "kind",
        "order",
        "source",
        "target",
        "expiry-bool",
    ],
)
async def test_loader_rejects_malformed_order_riders(marshal, field, value) -> None:
    fight = await arrange(marshal)
    _, ally, _ = fight.players
    await round_packets(fight, order(fight, fight.enemies[0]))
    state = await fight.reload()
    original = state.to_dict()
    row = deepcopy(original)
    riders = row["order_riders"]
    [rider] = riders[ally]
    if field == "recipient":
        riders[value] = riders.pop(ally)
    elif field == "list":
        riders[ally] = value
    elif field == "duplicate":
        riders[ally].append(rider)
    else:
        rider[field] = value
    try:
        await db_mutations.save_combat_state(state.combat_id, row)
        with pytest.raises(ValueError, match="order_riders"):
            await db_mutations.load_combat_state(state.combat_id)
    finally:
        await db_mutations.save_combat_state(state.combat_id, original)
