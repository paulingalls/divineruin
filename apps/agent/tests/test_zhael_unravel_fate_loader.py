from unittest.mock import patch

import asyncpg
import pytest
from _zhael_unravel_fixtures import GIFT, activate, favor, opening
from _zhael_unravel_fixtures import unravel as unravel
from combat._round_checkpoint_helpers import Fight
from livekit.agents.llm import ToolError

import combat_round_checkpoint as checkpoints


@pytest.mark.parametrize("legacy", ["previous_image", "whole_row"])
async def test_rewind_preserves_unknown_aggression(unravel: Fight, legacy: str) -> None:
    guest = unravel.ids[1]
    await favor(unravel, guest, "valdris")
    row = await opening(unravel, 1)
    previous, current = row["round_checkpoints"]
    del previous["combat"]["encounter_facts"]
    if legacy == "whole_row":
        del current["combat"]["encounter_facts"]
        del row["encounter_facts"]
    await unravel.write_row(row)
    await unravel.reload()

    receipt = await activate(unravel)
    assert (receipt["id"], receipt["round"]) == (GIFT, 1)
    saved = await unravel.row()
    assert saved["encounter_facts"]["party_aggressors"] is None
    (checkpoint,) = saved["round_checkpoints"]
    assert checkpoint["combat"]["encounter_facts"]["party_aggressors"] is None
    assert unravel.session.combat_state.encounter_facts["party_aggressors"] is None

    with pytest.raises(ToolError, match="aggression history is unknown"):
        await unravel.call("activate", actor=guest, id="valdris_the_scales_verdict", target_id="mawling_1")


async def test_rewind_holds_combat_row_lock_until_commit(unravel: Fight) -> None:
    await opening(unravel, 1)
    combat_id = unravel.combats[-1]
    lock_row = "SELECT data FROM combat_instances WHERE combat_id=$1 FOR UPDATE NOWAIT"
    read_party = checkpoints.read_party

    async with unravel.pool.acquire() as competitor:

        async def read_while_locked(conn: asyncpg.Connection, player_ids: list[str]) -> dict[str, dict]:
            with pytest.raises(asyncpg.LockNotAvailableError):
                async with competitor.transaction():
                    await competitor.fetchval(lock_row, combat_id)
            return await read_party(conn, player_ids)

        with patch.object(checkpoints, "read_party", read_while_locked):
            receipt = await activate(unravel)
        assert (receipt["id"], receipt["round"]) == (GIFT, 1)
        saved = await unravel.row()
        assert saved["round_number"] == 1
        async with competitor.transaction():
            assert await competitor.fetchval(lock_row, combat_id) is not None
