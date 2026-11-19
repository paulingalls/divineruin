import pytest
from _item_heal_fixtures import BERRY, GOODBERRY, POTION, heal_roll
from _item_heal_fixtures import item_heal_walk as item_heal_walk
from sample_fixtures import published_payloads

import db_mutations
import db_queries
import event_types as E
import spells
from session_data import CompanionState


@pytest.mark.parametrize("hp,healed", [(5, 7), (19, 1)])
async def test_consume_is_a_combat_action_with_one_committed_spend(walk, hp, healed):
    await walk.patch(hp={"current": hp, "max": 20})
    await walk.put()
    await walk.fight()
    await walk.declare_item()
    assert await walk.quantity() == 2
    assert (await walk.row())["hp"]["current"] == hp
    with heal_roll(7) as roll:
        result = await walk.resolve_item()
    roll.assert_called_once_with("2d4+2")
    assert result["item_id"] == POTION
    assert result["item_name"] == "Healing Potion"
    assert result["remaining_quantity"] == 1
    assert result["healing_results"] == [
        {
            "target_id": walk.player,
            "rolled": 7,
            "modifier": 0,
            "healed": healed,
            "hp_current": hp + healed,
            "hp_max": 20,
        }
    ]
    walk.sd.combat_state = await walk.checkpoint()
    assert not any(p.get("healing_results") for p in await walk.wrap())
    assert await walk.quantity() == 1
    assert (await walk.row())["hp"]["current"] == hp + healed
    assert (await walk.checkpoint()).get_participant(walk.player).hp_current == hp + healed
    assert {p["type"] for p in published_payloads(walk.sd.room)} >= {E.COMBAT_UI_UPDATE, E.INVENTORY_UPDATED}


@pytest.mark.parametrize("companion", [False, True])
async def test_holder_administers_potion_to_a_dying_ally(walk, companion):
    await walk.put()
    ally = "companion" if companion else await walk.add_player(hp=0)
    if companion:
        walk.sd.companion = CompanionState(id=ally, name="Kael", is_conscious=False)
    state = await walk.fight(companion=companion)
    fallen = state.get_participant(ally)
    fallen.hp_current = 0
    fallen.is_fallen = True
    fallen.death_save_successes = 1
    fallen.death_save_failures = 2
    await walk.save()
    await walk.declare_item(target=ally)
    with heal_roll(7):
        result = await walk.resolve_item()
    assert result["player_id"] == walk.player
    assert result["healing_results"][0]["target_id"] == ally
    assert await walk.quantity() == 1
    revived = (await walk.checkpoint()).get_participant(ally)
    assert (revived.hp_current, revived.is_fallen, revived.death_save_successes, revived.death_save_failures) == (
        7,
        False,
        0,
        0,
    )
    if companion:
        assert walk.sd.companion_can_act
        await walk.wrap()
        await walk.register_end()
        await walk.command("end_combat", {"outcome": "fled"})
        assert walk.sd.companion_can_act
    else:
        assert (await walk.read(ally))["hp"]["current"] == 7
        assert await walk.pool.fetchval("SELECT count(*) FROM player_inventory WHERE player_id=$1", ally) == 0


async def test_combat_goodberry_grants_items_then_feeds_an_ally(walk):
    await walk.prepare(GOODBERRY)
    ally = await walk.add_player()
    await walk.fight()
    cast = await walk.cast(GOODBERRY, combat=True)
    assert cast["created_items"][0]["player_id"] == walk.player
    assert cast["created_items"][0]["quantity"] == await walk.quantity(BERRY) == 5
    assert await walk.focus() == 30 - spells.get_spell(GOODBERRY).focus_cost
    assert {p["type"] for p in published_payloads(walk.sd.room)} >= {E.PLAY_SOUND, E.ITEM_ACQUIRED, E.INVENTORY_UPDATED}
    await walk.declare_item(BERRY, ally)
    await walk.resolve_item()
    assert (await walk.read(ally))["hp"]["current"] == 4
    assert await walk.quantity(BERRY) == 4


async def test_invalid_combat_consumes_leave_the_declaration_and_inventory_unchanged(walk):
    await walk.put(quantity=1)
    await walk.put("torch_bundle", 1)
    dead = await walk.add_player(hp=0)
    state = await walk.fight(companion=True)
    fallen = state.get_participant(dead)
    fallen.is_fallen = True
    fallen.death_save_failures = 3
    await walk.save()

    async def snapshot():
        return (
            await db_queries.get_inventory_snapshot(walk.player),
            await walk.row(),
            await walk.read(dead),
            (await walk.checkpoint()).to_dict(),
        )

    before = await snapshot()
    assert "declare_phase" in await walk.consume(error=True)
    for item in ("torch_bundle", "unknown_item"):
        assert "not a healing item" in await walk.declare_item(item, error=True)
    for target in ("foe", "missing"):
        assert "ally in the fight" in await walk.declare_item(target=target, error=True)
    assert "dead ally" in await walk.declare_item(target=dead, error=True)
    assert "conscious party player" in await walk.declare_item(actor="companion", error=True)
    assert await snapshot() == before

    await walk.declare_item()
    with heal_roll(7):
        await walk.resolve_item()
    await walk.wrap()
    after = await snapshot()
    assert "has no untainted Healing Potion" in await walk.declare_item(error=True)
    assert await snapshot() == after


async def test_stack_removed_after_declaration_refuses_before_phase_writes(walk):
    await walk.put(quantity=1)
    await walk.fight()
    await walk.declare_item()
    assert await db_mutations.remove_inventory_item(walk.player, POTION)
    prior_events = published_payloads(walk.sd.room)
    with heal_roll(7) as roll:
        result = await walk.command("resolve_phase", {}, error=True)
    roll.assert_not_called()
    assert "re-declare the whole phase" in result
    assert (await walk.checkpoint()).beat == "declaration"
    assert (await walk.row())["hp"]["current"] == 5
    assert await walk.quantity() == 0
    assert published_payloads(walk.sd.room) == prior_events
