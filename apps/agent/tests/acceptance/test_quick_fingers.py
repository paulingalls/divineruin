"""Quick Fingers through the registered combat tools."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.quick_fingers_harness import ABILITY, POCKET, FingersFight
from acceptance.quick_fingers_harness import fingers as fingers
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import ability_persistence
import db_mutations
import db_mutations_inventory
import event_types as E
import mentor_variant_progress

PELT = "wolf_pelt"


async def test_quick_fingers_discovery(fingers: FingersFight):
    for tainted in (False, True):
        await db_mutations.add_inventory_item(fingers.actor, PELT, 2, tainted=tainted)
    abilities = await fingers.command("query_info", {"kind": "abilities"})
    ability = next(row for row in abilities["abilities"] if row["id"] == ABILITY)
    assert ability["declaration"] == {
        "kind": "attack",
        "rider": "quick_fingers",
        "weapon": "melee",
        "quick_fingers_mode": ["steal", "plant", "swap"],
        "quick_fingers_item": "Use an owned inventory selector for plant or swap. Use an empty string for steal.",
    }
    inventory = await fingers.command("query_info", {"kind": "inventory"})
    assert {row["quick_fingers_item"] for row in inventory["items"] if row["id"] == PELT} == {
        "clean:wolf_pelt",
        "tainted:wolf_pelt",
    }
    recipe = ability["declaration"]
    payload = fingers.attack(recipe["quick_fingers_mode"][1], "tainted:wolf_pelt")
    payload.update(kind=recipe["kind"], rider=recipe["rider"])
    for malformed in (
        {**payload, "quick_fingers_mode": "peek"},
        {**payload, "quick_fingers_mode": "steal"},
        {**payload, "quick_fingers_item": ""},
        {**payload, "rider": ""},
        {"kind": "defend", "actor_id": fingers.actor, "reshape": [], "quick_fingers_mode": "plant"},
    ):
        assert "Quick Fingers" in await fingers.declare(malformed, error=True)
    assert (await fingers.declare(payload))["accepted_actors"] == [fingers.actor]


@pytest.mark.parametrize("fingers", [{"distance": 15}], indirect=True)
async def test_steal_precedes_the_killing_swing_and_cannot_pay_twice(fingers: FingersFight):
    target = await fingers.target()
    target.hp_current = 1
    state = fingers.sd.combat_state
    assert state is not None
    other = state.get_participant(fingers.enemies[1])
    assert other is not None
    other.hp_current = 0
    other.is_fallen = True
    other.carried_items = []
    await fingers.persist()
    await fingers.declare(fingers.attack("steal"))
    with patch("combat_quick_fingers.dice.roll", return_value=_d20(2)) as selection:
        packet = await fingers.swing(11, 17)
    selection.assert_called_once_with("1d2")
    assert packet["hit"] and packet["moved_ft"] == 10
    receipt = packet["quick_fingers"]
    assert receipt == {
        "mode": "steal",
        "planted": None,
        "stolen": {**POCKET[1], "name": "Rend Shard"},
        "total": 12,
        "dc": 12,
        "success": True,
        "wary": False,
        "pouch_empty": False,
    }
    assert await fingers.resources() == (8, 10)
    assert await fingers.inventory() == {("wolf_fangs", False): 1, ("rend_shard", True): 3}
    assert [
        (e["item_id"], e["quantity"], e["source"]) for e in fingers.inventory_events() if e["type"] == E.ITEM_ACQUIRED
    ] == [
        ("rend_shard", 3, "quick_fingers"),
        ("wolf_fangs", 1, "combat_loot"),
    ]


@pytest.mark.parametrize("tainted", [False, True])
async def test_plant_moves_one_exact_unit_and_victory_returns_its_taint(fingers: FingersFight, tainted: bool):
    for is_tainted in (False, True):
        await db_mutations.add_inventory_item(fingers.actor, PELT, 2 + is_tainted, tainted=is_tainted)
    inventory = await fingers.command("query_info", {"kind": "inventory"})
    item = next(row for row in inventory["items"] if row["id"] == PELT and row["tainted"] == tainted)
    await fingers.declare(fingers.attack("plant", item["quick_fingers_item"]))
    packet = await fingers.swing(11, 17)
    plant = {"item_id": PELT, "quantity": 1, "tainted": tainted}
    assert packet["hit"] and packet["quick_fingers"]["planted"] == {**plant, "name": "Wolf Pelt"}
    target = await fingers.target()
    assert target.carried_items == [*POCKET, plant]
    assert await fingers.inventory() == {(PELT, False): 2 - (not tainted), (PELT, True): 3 - tainted}
    assert await fingers.resources() == (8, 10)
    state = fingers.sd.combat_state
    assert state is not None
    for enemy in fingers.enemies:
        foe = state.get_participant(enemy)
        assert foe is not None
        foe.hp_current = 0
        foe.is_fallen = True
    await fingers.persist()
    await fingers.command("end_combat", {"outcome": "victory"})
    assert await fingers.inventory() == {
        (PELT, False): 2,
        (PELT, True): 3,
        ("wolf_fangs", False): 1,
        ("rend_shard", True): 3,
    }


@pytest.mark.parametrize("mode,face", [("steal", 11), ("steal", 10), ("swap", 11)])
@pytest.mark.parametrize("fingers", [{"empty": True}], indirect=True)
async def test_empty_pouch_still_spends_and_a_swap_plants(fingers: FingersFight, mode: str, face: int):
    if mode == "swap":
        await db_mutations.add_inventory_item(fingers.actor, PELT, 1, tainted=True)
    await fingers.declare(fingers.attack(mode, "tainted:wolf_pelt" if mode == "swap" else ""))
    events = fingers.inventory_events()
    with patch("combat_quick_fingers.dice.roll") as pick:
        receipt = (await fingers.swing(face, 17))["quick_fingers"]
    pick.assert_not_called()
    assert await fingers.resources() == (8, 10)
    assert receipt["total"] == face + 1 and receipt["dc"] == 12 and receipt["success"] is (face == 11)
    assert receipt["stolen"] is None and receipt["wary"] is (face == 10)
    assert await fingers.inventory() == {}
    target = await fingers.target()
    if mode == "swap":
        assert receipt["planted"]["name"] == "Wolf Pelt"
        assert target.carried_items == [{"item_id": PELT, "quantity": 1, "tainted": True}]
        assert [e["type"] for e in fingers.inventory_events()[len(events) :]] == [E.INVENTORY_UPDATED]
    else:
        assert target.carried_items == [] and fingers.inventory_events() == events
    if face == 11:
        assert receipt["pouch_empty"] and "pouch was empty" in receipt["reason"]


@pytest.mark.parametrize(
    "fingers,reason",
    [({"owned": False}, "hasn't learned"), ({"ranged": True}, "melee weapon"), ({}, "stamina")],
    indirect=["fingers"],
)
async def test_steal_refusals_before_rolling(fingers: FingersFight, reason: str):
    if reason == "stamina":
        await fingers.set_player(stamina={"current": 1, "max": 10})
    before = await fingers.snapshot()
    with patch("check_resolution.dice_roll") as roll:
        assert reason in (await fingers.declare(fingers.attack("steal"), error=True)).lower()
    roll.assert_not_called()
    assert await fingers.snapshot() == before


@pytest.mark.parametrize("status", ["equipped", "worn", "broken", "full"])
async def test_plant_equip_and_wear_refusals_before_rolling(fingers: FingersFight, status: str):
    item = "longsword_guild"
    await db_mutations.add_inventory_item(fingers.actor, item, 1, tainted=False)
    if status == "equipped":
        await fingers.pool.execute(
            "UPDATE player_inventory SET data=data || '{\"equipped\":true}'::jsonb WHERE player_id=$1 AND item_id=$2",
            fingers.actor,
            item,
        )
    elif status != "full":
        await db_mutations_inventory.update_item_durability(fingers.actor, item, int(status == "worn"))
    payload = fingers.attack("plant", f"clean:{item}")
    if status == "full":
        await fingers.declare(payload)
        assert (await fingers.swing(11, 17))["quick_fingers"]["planted"]["item_id"] == item
    else:
        before = await fingers.snapshot()
        with patch("check_resolution.dice_roll") as roll:
            error = await fingers.declare(payload, error=True)
        assert ("Unequip" if status == "equipped" else "worn") in error
        roll.assert_not_called()
        assert await fingers.snapshot() == before


@pytest.mark.parametrize("variant,stamina,focus", [("drathian", 3, 0), ("keldaran", 1, 1)])
async def test_active_variant_refusal_and_exact_prices(fingers: FingersFight, variant: str, stamina: int, focus: int):
    variant_id = f"{ABILITY}_{variant}"
    await mentor_variant_progress.record_unlocked(fingers.actor, variant_id)
    await ability_persistence.set_active_variant(fingers.actor, ABILITY, variant_id)
    await fingers.set_player(stamina={"current": stamina - (not focus), "max": 10}, focus={"current": 0, "max": 10})
    payload = fingers.attack("steal")
    before = await fingers.snapshot()
    with patch("check_resolution.dice_roll") as roll:
        assert ("focus" if focus else "stamina") in (await fingers.declare(payload, error=True)).lower()
    roll.assert_not_called()
    assert await fingers.snapshot() == before
    await fingers.set_player(stamina={"current": stamina, "max": 10}, focus={"current": focus, "max": 10})
    await fingers.declare(payload)
    assert (await fingers.swing(10, 17))["quick_fingers"]["success"] is False
    assert await fingers.resources() == (0, 0)


@pytest.mark.parametrize("fingers", [{"distance": 100}], indirect=True)
async def test_out_of_reach_approach_cannot_touch_the_pouch(fingers: FingersFight):
    await fingers.declare(fingers.attack("steal"))
    with patch("combat_quick_fingers.dice.roll") as selection:
        packet = await fingers.swing()
    selection.assert_not_called()
    assert packet["attack_resolved"] is False and "quick_fingers" not in packet
    assert await fingers.resources() == (10, 10)
    assert await fingers.inventory() == {}
    assert (await fingers.target()).carried_items == POCKET
