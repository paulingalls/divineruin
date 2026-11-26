"""A failed phase save rolls back the legacy pocket initialization."""

from random import Random
from unittest.mock import patch

from acceptance.test_enemy_pockets import (
    DROPS,
    defend,
    enemy_rows,
    fixture_pocket_fight,  # noqa: F401
    load_legacy,
    mock_combat_agent_factory,  # noqa: F401
    pockets,
    raw_row,
)

import db_mutations


async def test_failed_save_keeps_pockets_uninitialized_until_retry(pocket_fight) -> None:
    async with pocket_fight() as (h, ids, generate):
        image = await raw_row(h)
        enemy_rows(image)[1].pop("carried_items")
        enemy_rows(image["round_checkpoints"][0]["combat"])[1].pop("carried_items")
        await load_legacy(h, image)
        await defend(h)
        persisted_before = await raw_row(h)
        adopted_before = h.sd.combat_state.to_dict()
        save = db_mutations.save_combat_state

        async def fail_after_save(combat_id: str, data: dict, *, conn) -> None:
            assert pockets(data)[1] == DROPS[1]
            await save(combat_id, data, conn=conn)
            raise ConnectionError("injected failure after writing pockets")

        generate.reset_mock()
        with patch.object(db_mutations, "save_combat_state", side_effect=fail_after_save):
            result = await h.command("resolve_phase", {}, error=True)
        assert "try again" in result.lower()
        assert [c.args[0]["id"] for c in generate.call_args_list] == [ids[1]]
        assert (await raw_row(h)) == persisted_before
        assert h.sd.combat_state.to_dict() == adopted_before

        with patch("enemy_pockets.Random", return_value=Random(1)):
            await h.drain()
        assert pockets((await h.reload()).to_dict()) == DROPS
        assert [c.args[0]["id"] for c in generate.call_args_list] == [ids[1], ids[1]]
