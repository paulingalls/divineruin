"""An unexpanded composite must refuse rather than silently lose its strikes."""

from unittest.mock import patch

import pytest
from acceptance.test_mawling_multiattack import maw as maw


@pytest.fixture
def mock_combat_agent_factory():
    return None


async def test_unexpanded_composite_rolls_back_public_resolution(maw):
    await maw.declare(maw.players)
    await maw.command("resolve_phase", {})
    state = await maw.reload()
    head = next(h for h in state.held_actions if h.get("composite"))
    head["declaration"] = state.pending_declarations[head["actor_id"]]
    head.pop("composite")
    head.pop("strike_index")
    state.held_actions = [head]
    import db_mutations

    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    before = await maw.snapshot()
    # Bypass window lookup so the injected packet reaches the resolver's expansion guard.
    with patch("combat_hold._opens_windows", return_value=False):
        await maw.command("resolve_phase", {}, error=True)
    assert await maw.snapshot() == before
