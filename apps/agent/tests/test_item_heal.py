import json

import pytest
from _item_heal_fixtures import BERRY, GOODBERRY, POTION, heal_roll
from _item_heal_fixtures import item_heal_walk as item_heal_walk
from sample_fixtures import published_payloads
from test_wire_contract import FIXTURE

import db_mutations
import db_queries
import event_types as E
import spells


@pytest.mark.parametrize("hp,kaelen,healed,maximum", [(5, False, 7, 20), (19, False, 1, 20), (23, True, 2, 25)])
async def test_consume_from_registered_inventory_query(walk, hp, kaelen, healed, maximum):
    await walk.patch(
        hp={"current": hp, "max": 20}, divine_favor={"patron": "kaelen", "level": 40, "max": 100} if kaelen else None
    )
    await walk.put()
    inventory = await walk.command("query_info", {"kind": "inventory"})
    potion = next(i for i in inventory["items"] if i["id"] == POTION)
    with heal_roll(7) as roll:
        result = await walk.command("activate", {"id": potion["consume_id"]})
    roll.assert_called_once_with("2d4+2")
    assert result["item_id"] == POTION
    assert result["item_name"] == potion["name"]
    assert result["remaining_quantity"] == await walk.quantity() == 1
    assert result["healing_results"] == [
        {
            "target_id": walk.player,
            "rolled": 7,
            "modifier": 0,
            "healed": healed,
            "hp_current": hp + healed,
            "hp_max": maximum,
        }
    ]
    assert (await walk.row())["hp"] == {"current": hp + healed, "max": 20}
    assert {p["type"] for p in published_payloads(walk.sd.room)} >= {E.HP_CHANGED, E.INVENTORY_UPDATED}
    assert any(
        call.kwargs.get("destination_identities") == [walk.player]
        for call in walk.sd.room.local_participant.publish_data.await_args_list
    )


async def test_goodberry_grants_items_then_the_caster_feeds_an_ally(walk):
    await walk.prepare(GOODBERRY)
    ally = await walk.add_player()
    cast = await walk.cast(GOODBERRY)
    assert cast["created_items"] == [
        {
            "item_id": BERRY,
            "item_name": "Goodberry",
            "quantity": 5,
            "player_id": walk.player,
            "consume_id": "consume:goodberry",
        }
    ]
    assert await walk.quantity(BERRY) == 5
    spell = spells.get_spell(GOODBERRY)
    assert await walk.focus() == 30 - spell.focus_cost
    assert {p["type"] for p in published_payloads(walk.sd.room)} >= {E.PLAY_SOUND, E.ITEM_ACQUIRED, E.INVENTORY_UPDATED}
    await walk.patch_row(ally, temp_hp=7)
    await walk.consume(BERRY, ally)
    hp_pushes = [
        (json.loads(call.args[0]), call.kwargs.get("destination_identities"))
        for call in walk.sd.room.local_participant.publish_data.await_args_list
        if json.loads(call.args[0])["type"] == E.HP_CHANGED
    ]
    assert hp_pushes == [(FIXTURE["events"]["temp_hp_event_item"], [ally])]
    assert (await walk.read(ally))["hp"]["current"] == 4
    assert await walk.quantity(BERRY) == 4


async def test_exploration_refuses_wrong_items_and_recipients_without_mutation(walk):
    await walk.put(quantity=1)
    await walk.put("torch_bundle", 1)
    remote = await walk.add_player(location="accord_guild_hall")
    outside_party = await walk.add_player(party=False)
    missing = await walk.add_player()
    await walk.pool.execute("DELETE FROM players WHERE player_id=$1", missing)

    async def snapshot():
        return (
            await db_queries.get_inventory_snapshot(walk.player),
            [await walk.read(pid) for pid in (walk.player, remote, outside_party)],
            published_payloads(walk.sd.room),
        )

    before = await snapshot()
    for target in (remote, outside_party, missing):
        assert "party player at the holder's location" in await walk.consume(target=target, error=True)
    for item in ("torch_bundle", "unknown_item"):
        assert "not a healing item" in await walk.consume(item, error=True)
    assert await snapshot() == before

    with heal_roll(7):
        await walk.consume()
    await walk.put(tainted=True, quantity=1)
    after = await snapshot()
    assert "has no untainted Healing Potion" in await walk.consume(error=True)
    assert await snapshot() == after


async def test_restoration_salve_reports_hp_and_the_unapplied_condition_effect(walk):
    salve = "restoration_salve"
    conditions = [{"type": "poisoned"}, {"type": "wounded"}]
    await walk.patch(conditions=conditions)
    await walk.put(salve, 1)
    with heal_roll(4) as roll:
        result = await walk.consume(salve)
    roll.assert_called_once_with("1d4+1")
    assert result["healing_results"][0]["healed"] == 4
    assert result["condition_removal"] == {"applied": False, "reason": "The salve has no condition selection rule."}
    assert (await walk.row())["conditions"] == conditions
    assert await walk.quantity(salve) == 0


async def test_full_hp_consumes_from_the_authenticated_holders_stack(walk):
    holder = await walk.add_player(hp=20)
    await walk.put(quantity=2)
    await db_mutations.add_inventory_item(holder, POTION, 1, tainted=False)
    with heal_roll(7):
        result = await walk.consume(actor=holder)
    assert result["player_id"] == holder
    assert result["remaining_quantity"] == 0
    assert result["healing_results"][0]["healed"] == 0
    assert (await walk.read(holder))["hp"]["current"] == 20
    assert await db_queries.get_inventory_item(holder, POTION) is None
    assert await walk.quantity() == 2
