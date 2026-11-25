import pytest
from _zhael_unravel_fixtures import GIFT, activate, adopt_opening, cached, durable, opening, patch_player
from _zhael_unravel_fixtures import unravel as unravel

import db_mutations


async def test_late_restore_failure_rolls_back_before_adoption(unravel, monkeypatch) -> None:
    fight = unravel
    actor, guest = fight.ids
    third = await opening(fight)
    checkpoint = third["round_checkpoints"][0]
    start = checkpoint["players"][actor]["data"]
    await patch_player(fight, actor, hp={"current": 1, "max": start["hp"]["max"]}, resonance={"current": 40})
    await fight.pool.execute("DELETE FROM player_inventory WHERE player_id=$1", guest)
    await fight.pool.execute(
        """INSERT INTO player_inventory(player_id, item_id, data)
        VALUES ($1, 'healing_potion_minor', '{"quantity": 1}')""",
        actor,
    )
    await adopt_opening(fight)
    before, scratch = await durable(fight), cached(fight)
    state = fight.session.combat_state
    save = db_mutations.save_combat_state
    reached = False

    async def fail_after_save(combat_id, data, *, conn) -> None:
        nonlocal reached
        await save(combat_id, data, conn=conn)
        tentative = await durable(fight, conn=conn)
        restored = tentative["players"][actor]["data"]
        assert restored["hp"] == start["hp"]
        assert restored["resonance"]["current"] == start["resonance"]["current"] + 8
        assert restored["patron_gifts"][GIFT]["spent"]
        assert any(slot["player_id"] == guest for slot in tentative["slots"])
        assert not any(
            slot["player_id"] == actor and slot["item_id"] == "healing_potion_minor" for slot in tentative["slots"]
        )
        assert tentative["combat"]["round_number"] == 2
        reached = True
        raise RuntimeError("injected rewind write failure")

    with monkeypatch.context() as patch:
        patch.setattr(db_mutations, "save_combat_state", fail_after_save)
        with pytest.raises(RuntimeError, match="injected rewind write failure"):
            await activate(fight)
    assert reached
    assert await durable(fight) == before
    assert fight.session.combat_state is state
    assert cached(fight) == scratch
    assert (await activate(fight))["id"] == GIFT
