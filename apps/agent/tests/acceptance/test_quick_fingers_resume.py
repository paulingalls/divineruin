"""Fate reloads across Quick Fingers' skill check and the subsequent weapon roll."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.quick_fingers_harness import POCKET, FingersFight
from acceptance.quick_fingers_harness import fingers as fingers
from acceptance.test_architect_entomb import favor
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import db_mutations
import db_mutations_inventory
import event_types as E

PLANT = {"item_id": "wolf_pelt", "quantity": 1, "tainted": True}


@pytest.mark.parametrize("mode,face", [("steal", 15), ("plant", 15), ("swap", 15), ("steal", 7)])
async def test_skill_then_weapon_fate_pauses_preserve_one_check_cost_and_transfer(
    fingers: FingersFight, mode: str, face: int
):
    await favor(fingers)
    planting = mode != "steal"
    stealing = mode != "plant" and face == 15
    if planting:
        await db_mutations.add_inventory_item(fingers.actor, PLANT["item_id"], 1, tainted=True)
    await fingers.declare(fingers.attack(mode, "tainted:wolf_pelt" if planting else ""))
    events = fingers.inventory_events()
    before = await fingers.inventory()
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face), _d20(17)]) as d20,
        patch("combat_quick_fingers.dice.roll", return_value=_d20(2)) as selection,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        first = await fingers.command("resolve_phase", {})
        assert first["fate_offer"]["roll_kind"] == "skill"
        target = await fingers.target()
        state = fingers.sd.combat_state
        assert state is not None and state.ally_continuation is not None
        assert state.ally_continuation["steps"]["quick_fingers"]["skill"]
        assert target.hp_current == 100 and target.carried_items == POCKET
        assert await fingers.resources() == (10, 10)
        assert await fingers.inventory() == before and fingers.inventory_events() == events
        assert d20.call_count == 1
        selection.assert_not_called()
        await fresh_session(fingers, state)

        second = await fingers.command("resolve_phase", {})
        assert second["fate_offer"]["roll_kind"] == "attack"
        target = await fingers.target()
        state = fingers.sd.combat_state
        assert state is not None and state.ally_continuation is not None
        receipt = state.ally_continuation["attack"]["quick_fingers"]
        expected_pocket = [*(POCKET[:1] if stealing else POCKET), *([PLANT] if planting else [])]
        assert target.hp_current == 100 and target.carried_items == expected_pocket
        assert receipt["success"] is (face == 15)
        assert bool(state.quick_fingers_wary) is (face == 7)
        assert await fingers.resources() == (8, 10)
        assert await fingers.inventory() == ({("rend_shard", True): 3} if stealing else {})
        expected_events = ([E.ITEM_ACQUIRED] if stealing else []) + (
            [E.INVENTORY_UPDATED] if planting or stealing else []
        )
        assert [e["type"] for e in fingers.inventory_events()[len(events) :]] == expected_events
        assert selection.call_count == int(stealing)
        damage.assert_not_called()
        await fresh_session(fingers, state)

        packets = await fingers.drain()
    assert d20.call_count == 2 and selection.call_count == int(stealing)
    assert damage.called
    packet = next(p for p in packets if p["actor_id"] == fingers.actor)
    assert packet["hit"] and packet["quick_fingers"] == receipt
    assert (await fingers.target()).carried_items == expected_pocket
    assert await fingers.resources() == (8, 10)
    assert await fingers.inventory() == ({("rend_shard", True): 3} if stealing else {})
    assert [e["type"] for e in fingers.inventory_events()[len(events) :]] == expected_events


@pytest.mark.parametrize("change,reason", [("equipped", "Unequip"), ("worn", "worn"), ("missing", "no longer carries")])
async def test_selected_plant_row_is_rechecked_after_the_skill_pause(fingers: FingersFight, change: str, reason: str):
    await favor(fingers)
    item = "longsword_guild"
    await db_mutations.add_inventory_item(fingers.actor, item, 1, tainted=True)
    await fingers.declare(fingers.attack("plant", f"tainted:{item}"))
    events = fingers.inventory_events()
    with patch("check_resolution.dice_roll", return_value=_d20(11)) as d20:
        first = await fingers.command("resolve_phase", {})
        assert first["fate_offer"]["roll_kind"] == "skill"
        if change == "equipped":
            await fingers.pool.execute(
                "UPDATE player_inventory SET data=data || '{\"equipped\":true}'::jsonb "
                "WHERE player_id=$1 AND item_id=$2 AND tainted",
                fingers.actor,
                item,
            )
        elif change == "worn":
            await db_mutations_inventory.update_item_durability(fingers.actor, item, 1, tainted=True)
        else:
            await db_mutations.remove_inventory_item(fingers.actor, item, tainted=True)
        before = await fingers.inventory()
        await fresh_session(fingers, await fingers.reload())
        packets = await fingers.drain()
    packet = next(p for p in packets if p["actor_id"] == fingers.actor)
    assert not packet["resolved"] and reason in packet["reason"]
    d20.assert_called_once()
    assert await fingers.resources() == (10, 10)
    assert await fingers.inventory() == before and fingers.inventory_events() == events
    target = await fingers.target()
    assert target.carried_items == POCKET and target.hp_current == 100
