"""A swap fails atomically even after either completed transfer."""

from unittest.mock import patch

import asyncpg
import pytest
from acceptance._capstone_helpers import _d20
from acceptance.quick_fingers_harness import POCKET, FingersFight
from acceptance.quick_fingers_harness import fingers as fingers
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import combat_quick_fingers
import db_mutations
import event_types as E
from combat_events import EventSink


@pytest.mark.parametrize("leg", ["plant", "steal"])
async def test_swap_rolls_back_both_legs_and_buffered_events(fingers: FingersFight, leg: str):
    await db_mutations.add_inventory_item(fingers.actor, "wolf_pelt", 1, tainted=True)
    await fingers.declare(fingers.attack("swap", "tainted:wolf_pelt"))
    before = await fingers.snapshot()
    events = fingers.inventory_events()
    inventories = await fingers.inventory()
    plant = combat_quick_fingers._plant
    emit = EventSink.emit
    injected = False

    async def fail_after_plant(*args, **kwargs) -> None:
        nonlocal injected
        with pytest.raises(asyncpg.LockNotAvailableError):
            await fingers.pool.fetchval(
                "SELECT data FROM player_inventory WHERE player_id=$1 AND item_id='wolf_pelt' "
                "AND tainted FOR UPDATE NOWAIT",
                fingers.actor,
            )
        await plant(*args, **kwargs)
        injected = True
        raise ConnectionError("Swap fault after plant")

    async def fail_after_events(sink, room, event_type: str, payload: dict, **kwargs) -> None:
        nonlocal injected
        await emit(sink, room, event_type, payload, **kwargs)
        if event_type == E.INVENTORY_UPDATED:
            assert [event.event_type for event in sink.captured][-2:] == [E.ITEM_ACQUIRED, E.INVENTORY_UPDATED]
            injected = True
            raise ConnectionError("Swap fault after steal and both inventory events")

    fault = (
        patch.object(combat_quick_fingers, "_plant", side_effect=fail_after_plant)
        if leg == "plant"
        else patch.object(EventSink, "emit", fail_after_events)
    )
    with (
        fault,
        patch("check_resolution.dice_roll", return_value=_d20(11)),
        patch("combat_quick_fingers.dice.roll", return_value=_d20(2)),
    ):
        await fingers.command("resolve_phase", {}, error=True)
    assert injected
    assert await fingers.snapshot() == before
    assert await fingers.inventory() == inventories
    assert fingers.inventory_events() == events

    with patch("combat_quick_fingers.dice.roll", return_value=_d20(2)):
        receipt = (await fingers.swing(11, 17))["quick_fingers"]
    assert receipt["planted"]["name"] == "Wolf Pelt" and receipt["stolen"]["name"] == "Rend Shard"
    assert await fingers.inventory() == {("rend_shard", True): 3}
    assert (await fingers.target()).carried_items == [
        POCKET[0],
        {"item_id": "wolf_pelt", "quantity": 1, "tainted": True},
    ]
    assert await fingers.resources() == (8, 10)
    assert [e["type"] for e in fingers.inventory_events()[len(events) :]] == [E.ITEM_ACQUIRED, E.INVENTORY_UPDATED]
