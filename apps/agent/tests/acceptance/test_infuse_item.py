"""Infuse Item expiry, capacity and bonuses through the registered tools."""

import pytest
from acceptance.infusion_harness import CLUB, DAGGER, HANDAXE, SHORTSWORD, InfusionWalk
from acceptance.infusion_harness import walk as walk
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory


@pytest.mark.parametrize(
    ("walk", "bonus", "capacity"), [((4, False, 12), 1, 1), ((10, False, 12), 2, 3)], indirect=["walk"]
)
@pytest.mark.parametrize("mode", ["ordinary", "reloaded", "held"])
async def test_infusion_reaches_weapon_attack(walk: InfusionWalk, bonus: int, capacity: int, mode: str) -> None:
    await walk.equip(SHORTSWORD, acquire=True)
    await walk.infuse(SHORTSWORD, bonus)
    assert await walk.lookup() == {
        "scope": "own_equipped_nonmagical_main_hand_weapon",
        "attack_bonus": bonus,
        "damage_bonus": bonus,
        "magical": True,
        "capacity": capacity,
        "expiry": "next_long_rest",
        "active": [{"item_id": SHORTSWORD, "bonus": bonus, "equipped": True}],
    }
    await walk.strike(bonus, mode=mode)


async def test_single_infusion_follows_item_and_replaces_old(walk: InfusionWalk) -> None:
    items = [SHORTSWORD, CLUB]
    catalog = await walk.pool.fetch("SELECT id, data FROM items WHERE id = ANY($1) ORDER BY id", items)
    await walk.equip(SHORTSWORD, acquire=True)
    assert (await walk.lookup())["active"] == []
    await walk.infuse(SHORTSWORD, 1)
    await walk.equip(CLUB, acquire=True)
    assert (await walk.lookup())["active"] == [{"item_id": SHORTSWORD, "bonus": 1, "equipped": False}]
    await walk.strike(0, finish=True)
    await walk.equip(SHORTSWORD)
    await walk.strike(1, finish=True)
    await walk.equip(CLUB)
    await walk.infuse(CLUB, 1, replaced=SHORTSWORD)
    await walk.strike(1, finish=True)
    await walk.equip(SHORTSWORD)
    assert (await walk.lookup())["active"] == [{"item_id": CLUB, "bonus": 1, "equipped": False}]
    await walk.strike(0)
    assert set(await walk.infusions()) == {CLUB}
    assert await walk.pool.fetch("SELECT id, data FROM items WHERE id = ANY($1) ORDER BY id", items) == catalog


@pytest.mark.parametrize("walk", [(10, False, 12)], indirect=True)
async def test_arcane_armory_retains_three_and_evicts_oldest(walk: InfusionWalk) -> None:
    first_three = (SHORTSWORD, CLUB, HANDAXE)
    for item in first_three:
        await walk.equip(item, acquire=True)
        await walk.infuse(item, 2)
    for item in first_three:
        await walk.equip(item)
        await walk.strike(2, finish=True)
    await walk.equip(DAGGER, acquire=True)
    await walk.infuse(DAGGER, 2, replaced=SHORTSWORD)
    assert {item: record["bonus"] for item, record in (await walk.infusions()).items()} == {
        CLUB: 2,
        HANDAXE: 2,
        DAGGER: 2,
    }
    for item in (*first_three, DAGGER):
        await walk.equip(item)
        await walk.strike(0 if item == SHORTSWORD else 2, finish=True, critical=item == DAGGER)


async def test_long_rest_expires_infusion(walk: InfusionWalk) -> None:
    await walk.equip(SHORTSWORD, acquire=True)
    await walk.infuse(SHORTSWORD, 1)
    await walk.command("rest", {"rest_type": "short"})
    assert (await walk.lookup())["active"] == [{"item_id": SHORTSWORD, "bonus": 1, "equipped": True}]
    await walk.command("rest", {"rest_type": "long"})
    assert await walk.infusions() == {}
    assert (await walk.lookup())["active"] == []
    await walk.strike(0)
