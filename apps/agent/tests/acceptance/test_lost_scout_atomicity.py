"""A failed phase save must leave the scout's one-time cue available on retry."""

import json
from unittest.mock import patch

from acceptance.test_lost_scout import (
    mock_combat_agent_factory as mock_combat_agent_factory,
)
from acceptance.test_lost_scout import scout as scout

import db_mutations
import db_queries


async def test_phase_save_rolls_back_residue_and_retries(scout):
    await scout.start_scout()
    await scout.declare_scout(scout.defend_action())
    before = await scout.snapshot()
    save = db_mutations.save_combat_state
    writes = []

    async def fail_after_save(*args, **kwargs):
        player = await db_queries.get_player(scout.players[0], conn=kwargs["conn"])
        assert player is not None
        writes.append(json.loads(player["flags"]["lost_scout"])["residue_delivered"])
        await save(*args, **kwargs)
        raise RuntimeError("injected Lost Scout phase checkpoint failure")

    with patch("db_mutations.save_combat_state", side_effect=fail_after_save):
        await scout.command("resolve_phase", {}, error=True)
    assert writes == [True]
    assert await scout.snapshot() == before
    assert "Tam" in (await scout.command("resolve_phase", {}))["lost_scout_residue"]
    await scout.reload()
    assert "lost_scout_residue" not in await scout.command("resolve_phase", {})
