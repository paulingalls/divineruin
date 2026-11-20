"""Registered spoken commands persist a loadout and martial choices."""

import json
from pathlib import Path
from unittest.mock import patch

from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.attribute_increase_walk import IncreaseWalk
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_martial_core_kit import adjacent_foe, declare, weapon_attack
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import abilities
import ability_persistence
import db_content_queries
import db_mutations
import db_mutations_inventory
import db_queries
import event_types as E
from inventory_tools import transact
from mode_tools import enter_mode
from session_data import SessionData

CONTENT = Path(__file__).resolve().parents[4] / "content"

# The named technique pools in the archetype profiles.
DESIGNED_POOLS = {
    "bard": (4,),
    "diplomat": (4, 8),
    "guardian": (4, 8),
    "marshal": (4, 8),
    "paladin": (4,),
    "rogue": (4, 8),
    "skirmisher": (4, 8),
    "spy": (4, 8),
    "warrior": (4, 8),
}


async def call(walk, name, *, actor=None, **arguments):
    receipt = await walk.command(name, arguments, actor=actor)
    assert not receipt.is_error, receipt.output
    return json.loads(receipt.output)


async def enter_fight(walk):
    await call(walk, "enter_mode", mode="combat", encounter_id="ruins_mawling_pair")
    fight = MawlingHarness()
    fight.pool, fight.sd, fight.model, fight.session = walk.pool, walk.sd, walk.model, walk.session
    fight.players = [walk.player]
    return fight


def test_award_and_select_electives(harness, monkeypatch):
    original = db_content_queries.get_quest

    async def quest(quest_id, **kwargs):
        result = await original(quest_id, **kwargs)
        assert result is not None
        result = json.loads(json.dumps(result))
        stage = result["stages"][7]
        stage["on_complete"].update(xp=1850, favor=0)
        return result

    monkeypatch.setattr(db_content_queries, "get_quest", quest)

    async def check():
        authored = {}
        for row in json.loads((CONTENT / "archetype_abilities.json").read_text()):
            if row["ability_type"] == "elective" and row["level_requirement"] in (4, 8):
                authored.setdefault(row["archetype_id"], set()).add(row["level_requirement"])
        for archetype in sorted(authored.keys() | DESIGNED_POOLS.keys()):
            levels = DESIGNED_POOLS.get(archetype, ())
            walk = await IncreaseWalk().setup(harness, tools=[enter_mode])
            await walk.seed(3, archetype)
            award = await call(walk, "update_quest", quest_id="greyvale_anomaly", new_stage_id=8)
            offers = award["elective_choices"]
            offered_levels = [offer["level"] for offer in offers]
            assert set(levels) <= set(offered_levels), f"{archetype} is missing a designed elective pool"
            assert offered_levels == sorted(authored[archetype])
            assert next(e for e in walk.events if e["type"] == E.LEVEL_UP)["elective_choices"] == offers
            query = await call(walk, "query_info", kind="abilities")
            assert query["elective_choices"] == offers
            for offer in offers:
                assert offer["player_id"] == walk.player
                assert offer["resolve_with"] == "select"
                assert "aloud" in offer["narration_cue"] and "spoken" in offer["narration_cue"]
                pool = [
                    ability
                    for ability in abilities.get_archetype_abilities(archetype)
                    if ability.ability_type == "elective" and ability.level_requirement == offer["level"]
                ]
                assert pool
                if offer["level"] in levels:
                    assert len(pool) == 4
                assert offer["options"] == [
                    {"id": a.id, "name": a.name, "effect": a.effect, "narration_cue": a.narration_cue} for a in pool
                ]
            if archetype in {"warrior", "rogue"}:
                await walk.reload(harness)
                await call(walk, "rest", rest_type="long")
                assert (await call(walk, "query_info", kind="abilities"))["elective_choices"] == offers
            for index, offer in enumerate(offers):
                option = next(
                    (o["id"] for o in offer["options"] if o["id"] == "warrior_unstoppable_charge"),
                    offer["options"][0]["id"],
                )
                await call(walk, "select", choice_id=offer["choice_id"], option=option)
                assert await ability_persistence.owns_elective(walk.player, option)
                owned = await ability_persistence.get_character_abilities(walk.player)
                assert any(row["ability_id"] == option and row["equipped"] for row in owned)
                query = await call(walk, "query_info", kind="abilities")
                assert query["elective_choices"] == offers[index + 1 :]
                picked = next(a for a in query["abilities"] if a["id"] == option)
                assert picked["combat"] is (option == "warrior_unstoppable_charge")
            if archetype == "warrior":
                fight = await enter_fight(walk)
                foe = await adjacent_foe(fight)
                await declare(fight, "warrior_unstoppable_charge", [foe])
                stamina = (await walk.row())["stamina"]["current"]
                with patch("check_resolution.dice_roll", return_value=_d20(1)):
                    packets = await fight.drain()
                charge = next(packet for packet in packets if packet.get("action") == "warrior_unstoppable_charge")
                assert charge["condition_inflicted"] == "prone" and not charge["save_success"]
                target = (await fight.reload()).get_participant(foe)
                assert target is not None and any(c["type"] == "prone" for c in target.conditions)
                assert (await walk.row())["stamina"]["current"] == stamina - 4

    harness.run_sync(check())


def test_equip_replaces_owned_gear(harness):
    async def check():
        walk = await IncreaseWalk().setup(harness, tools=[transact, enter_mode])
        for item in (
            "dagger_balanced",
            "longsword_guild",
            "chain_shirt",
            "half_plate",
            "greatsword_steel",
            "plate_armor",
        ):
            await call(walk, "transact", action="exchange", item_id=item, delta=1)
            walk.events.clear()
            await call(walk, "transact", action="equip", item_id=item, delta=0)
            assert E.ITEM_ACQUIRED not in [event["type"] for event in walk.events]
            snapshot = next(event for event in walk.events if event["type"] == E.SESSION_INIT)
            assert snapshot["character"]["equipment"] == (await walk.row())["equipment"]
            updated = next(event for event in walk.events if event["type"] == E.INVENTORY_UPDATED)
            assert updated["player_id"] == walk.player
            assert updated["inventory"] == (await db_queries.get_inventory_snapshot(walk.player))["inventory"]
            if item == "half_plate":
                assert snapshot["character"]["ac"] == 17
            if item == "dagger_balanced":
                # Its "ranged" tag means it can be thrown; a melee weapon still swings in melee.
                assert "ranged" not in snapshot["character"]["equipment"]["main_hand"]
        row = await walk.row()
        assert row["equipment"]["main_hand"]["name"] == "Steel Greatsword"
        assert row["equipment"]["main_hand"]["damage"] == "2d6"
        assert row["equipment"]["main_hand"]["damage_type"] == "slashing"
        assert row["equipment"]["armor"]["name"] == "Plate Armor"
        for item, equipped in (
            ("dagger_balanced", False),
            ("longsword_guild", False),
            ("chain_shirt", False),
            ("half_plate", False),
            ("greatsword_steel", True),
            ("plate_armor", True),
        ):
            stack = await db_queries.get_inventory_item(walk.player, item)
            assert stack is not None and stack["quantity"] == 1 and stack["equipped"] is equipped

        before_retry = await gear_state(walk)
        await call(walk, "transact", action="equip", item_id="plate_armor", delta=0)
        assert await gear_state(walk) == before_retry

        await walk.reload(harness)
        fight = await enter_fight(walk)
        state = await fight.reload()
        actor = state.get_participant(walk.player)
        assert actor is not None and actor.ac == 18
        assert [(item["name"], item["damage"], item["properties"]) for item in actor.action_pool] == [
            ("Steel Greatsword", "2d6", ["heavy", "two-handed"])
        ]
        foe = await adjacent_foe(fight)
        await fight.command(
            "declare_phase",
            {
                "declarations": [
                    {**weapon_attack(walk.player, foe, ""), "action": "Steel Greatsword"},
                    {**weapon_attack(foe, walk.player, ""), "action": "Claw"},
                    *(
                        {"kind": "defend", "actor_id": pid, "reshape": []}
                        for pid in state.initiative_order
                        if pid not in {walk.player, foe}
                    ),
                ]
            },
        )
        with (
            patch("check_resolution.dice_roll", return_value=_d20(19)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
        ):
            packets = await fight.drain()
        assert "2d6" in [call.args[0] for call in damage.call_args_list]
        assert any(packet.get("action") == "Steel Greatsword" and packet.get("damage", 0) > 0 for packet in packets)
        plate = await db_queries.get_inventory_item(walk.player, "plate_armor")
        chain = await db_queries.get_inventory_item(walk.player, "chain_shirt")
        assert plate is not None and plate["current_hits"] > 0
        assert chain is not None and "current_hits" not in chain

        await walk.session.current_agent.update_tools([transact])
        before = await gear_state(walk)
        walk.events.clear()
        refused = await walk.command("transact", {"action": "equip", "item_id": "longsword_guild", "delta": 0})
        assert refused.is_error and "outside combat" in refused.output
        assert await gear_state(walk) == before and not walk.events

    harness.run_sync(check())


async def gear_state(walk):
    stacks = await walk.pool.fetch(
        "SELECT item_id, tainted, data FROM player_inventory WHERE player_id=$1 ORDER BY item_id, tainted",
        walk.player,
    )
    return await walk.row(), stacks


def test_equip_refusals_and_atomic_slot_replacement(harness, monkeypatch):
    async def check():
        walk = await IncreaseWalk().setup(harness, tools=[transact])
        await walk.seed(3, "rogue")
        for item in ("healing_poultice", "travelers_cloak", "plate_armor", "reinforced_shield", "longsword_guild"):
            await call(walk, "transact", action="exchange", item_id=item, delta=1)
        await db_mutations.add_inventory_item(walk.player, "greatsword_steel", 1, tainted=True)
        await db_mutations.add_inventory_item(walk.player, "padded_armor", 1, tainted=False)
        await walk.pool.execute(
            "UPDATE player_inventory SET data = jsonb_set(data, '{quantity}', '0') "
            "WHERE player_id=$1 AND item_id='padded_armor'",
            walk.player,
        )
        before = await gear_state(walk)
        walk.events.clear()
        for item, reason in (
            ("chain_shirt", "not owned"),
            ("padded_armor", "not owned"),
            ("healing_poultice", "cannot be equipped"),
            ("travelers_cloak", "cannot be equipped"),
            ("plate_armor", "lack heavy proficiency"),
            ("reinforced_shield", "lack shield proficiency"),
            ("greatsword_steel", "dispel_corruption"),
        ):
            refused = await walk.command("transact", {"action": "equip", "item_id": item, "delta": 0})
            assert refused.is_error and reason in refused.output, refused.output
            assert await gear_state(walk) == before and not walk.events
        await call(walk, "transact", action="equip", item_id="longsword_guild", delta=0)

        await walk.seed(3, "druid")
        for item in ("hide_armor", "chain_shirt"):
            await call(walk, "transact", action="exchange", item_id=item, delta=1)
        await call(walk, "transact", action="equip", item_id="hide_armor", delta=0)
        before = await gear_state(walk)
        walk.events.clear()
        refused = await walk.command("transact", {"action": "equip", "item_id": "chain_shirt", "delta": 0})
        assert refused.is_error and "lack medium proficiency" in refused.output
        assert await gear_state(walk) == before and not walk.events

        guest = walk.player + "_guest"
        await walk.seed(3)
        await db_mutations.create_player(guest, None, await walk.row())
        walk.sd.party.members.append(SessionData(player_id=guest, location_id="millhaven_inn").party.primary)
        host_before = await gear_state(walk)
        for item in ("longsword_guild", "reinforced_shield", "shield_iron"):
            await call(walk, "transact", actor=guest, action="exchange", item_id=item, delta=1)
            await call(walk, "transact", actor=guest, action="equip", item_id=item, delta=0)
        assert await gear_state(walk) == host_before
        guest_row = await db_queries.get_player(guest)
        assert guest_row is not None and guest_row["equipment"]["shield"]["id"] == "shield_iron"
        for item, equipped in (("reinforced_shield", False), ("shield_iron", True), ("longsword_guild", True)):
            stack = await db_queries.get_inventory_item(guest, item)
            assert stack is not None and stack["equipped"] is equipped

        walk.events.clear()

        flag_write_seen = False

        async def fail_after_flags(pid, equipment, ac, *, conn):
            nonlocal flag_write_seen
            old = await db_queries.get_inventory_item(pid, "shield_iron", conn=conn)
            new = await db_queries.get_inventory_item(pid, "reinforced_shield", conn=conn)
            assert old is not None and not old["equipped"]
            assert new is not None and new["equipped"]
            flag_write_seen = True
            raise RuntimeError("injected loadout write failure")

        monkeypatch.setattr(db_mutations_inventory, "save_loadout", fail_after_flags)
        refused = await walk.command(
            "transact", {"action": "equip", "item_id": "reinforced_shield", "delta": 0}, actor=guest
        )
        assert flag_write_seen and refused.is_error and not walk.events
        assert await db_queries.get_player(guest) == guest_row
        for item, equipped in (("reinforced_shield", False), ("shield_iron", True)):
            stack = await db_queries.get_inventory_item(guest, item)
            assert stack is not None and stack["equipped"] is equipped

    harness.run_sync(check())


def test_select_refuses_without_changing_ownership(harness):
    async def check():
        walk = await IncreaseWalk().setup(harness)
        option = "warrior_cleaving_blow"
        guest = walk.player + "_guest"
        await walk.seed(8, "mage")
        await db_mutations.create_player(guest, None, await walk.row())
        walk.sd.party.members.append(SessionData(player_id=guest, location_id="millhaven_inn").party.primary)

        async def refuse(level, pick, reason, *, actor=walk.player):
            row = await db_queries.get_player(actor)
            owned = await ability_persistence.get_character_abilities(actor)
            receipt = await walk.command(
                "select", {"choice_id": f"elective_technique_{level}", "option": pick}, actor=actor
            )
            assert receipt.is_error and reason in receipt.output, receipt.output
            assert row == await db_queries.get_player(actor)
            assert owned == await ability_persistence.get_character_abilities(actor)

        await refuse(4, option, "no elective technique pool", actor=guest)
        await walk.seed(3)
        await refuse(4, option, "not reached")
        await walk.seed(8)
        await refuse(4, "warrior_unstoppable_charge", "not in your level 4")
        await refuse(4, "rogue_dirty_trick", "not in your level 4")
        assert (await call(walk, "select", choice_id="elective_technique_4", option=option))["chosen"] == option
        await refuse(4, option, "already chosen")
        await refuse(4, "warrior_precision_strike", "already chosen")
        await ability_persistence.set_elective_equipped(walk.player, option, False)
        await refuse(4, "warrior_precision_strike", "already chosen")

        host_before = await ability_persistence.get_character_abilities(walk.player)
        player = await walk.row()
        await walk.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", guest, json.dumps(player))
        query = await call(walk, "query_info", actor=guest, kind="abilities")
        assert [offer["player_id"] for offer in query["elective_choices"]] == [guest, guest]
        await call(walk, "select", actor=guest, choice_id="elective_technique_4", option=option)
        assert await ability_persistence.owns_elective(guest, option)
        assert await ability_persistence.get_character_abilities(walk.player) == host_before

    harness.run_sync(check())
