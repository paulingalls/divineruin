import json
from pathlib import Path
from unittest.mock import patch

from _zhael_fate_fixtures import attack, defend
from _zhael_unravel_fixtures import (
    GIFT,
    assert_restored,
    discovered,
    durable,
    favor,
    patch_player,
    unravel_fight,
)
from acceptance._capstone_helpers import _d20, _damage_die
from combat._round_checkpoint_helpers import Fight
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party

import event_types as E
from _gods_content import load_gods
from combat_ui_update import build_combat_ui_update
from resonance import get_resonance_state
from session_data import CompanionState


def test_unravel_fate_catalog_matches_design() -> None:
    zhael = next(god for god in load_gods() if god["god_id"] == "zhael")
    design = Path(__file__).resolve().parents[3] / "docs/game_mechanics/game_mechanics_patrons.md"
    row = next(line for line in design.read_text().splitlines() if line.startswith("| Exalted | Unravel Fate |"))
    assert zhael["layer_3_tier_abilities"]["exalted"]["effect"] == row.split("|")[3].strip()


async def whole_round(world) -> None:
    async with unravel_fight(world.pool) as fight:
        await exercise_rewind(fight)


async def exercise_rewind(fight: Fight) -> None:
    warrior, mage = fight.ids
    rogue, mover = await fight.join(), await fight.join()
    session = fight.session
    session.companion = CompanionState(id="companion_kael", name="Kael")
    assert fight.lifecycle is not None
    await fight.lifecycle.aclose()
    fight.lifecycle = _live_party(session, *fight.ids)
    await patch_player(fight, warrior, level=4, flags={"ignored": True})
    await favor(fight, rogue, "syrath", 70)
    await favor(fight, mover, "valdris", 60)
    await patch_player(
        fight,
        rogue,
        **{
            "class": "rogue",
            "archetype_id": "rogue",
            "hp": {"current": 49, "max": 50},
            "temp_hp": 2,
        },
    )
    for item, slot in (
        ("healing_potion_minor", {"quantity": 1}),
        ("leather_armor_basic", {"quantity": 1, "equipped": True, "current_hits": 10}),
    ):
        await fight.pool.execute(
            "INSERT INTO player_inventory (player_id,item_id,data) VALUES ($1,$2,$3::jsonb)",
            rogue,
            item,
            json.dumps(slot),
        )
    await fight.start("bandit_ambush")
    state = session.combat_state
    captain = state.get_participant("bandit_captain")
    captain.hp_current = captain.hp_max = 40
    state.get_participant("companion_kael").hp_current = 1
    positions = state.spatial["positions"]
    positions["bandit_captain"] = {"x": 5, "y": 0, "z": 0}
    positions["bandit_1"] = {"x": 5, "y": -8, "z": 0}
    positions["bandit_2"] = {"x": 5, "y": 5, "z": 0}
    positions[rogue] = {"x": 5, "y": -5, "z": 0}
    await fight.call("activate", actor=rogue, id="syrath_shadow_veil")
    await fight.declare()
    await fight.finish_round(2)
    start = (await fight.row())["round_checkpoints"][-1]
    assert start["players"][rogue]["data"]["flags"]["shadow_veil"]["remaining_rounds"] == 1
    await fight.call("activate", actor=rogue, id="syrath_veilstep", destination={"x": 5, "y": -4, "z": 0})
    await fight.call("activate", actor=mover, id="valdris_mark_of_justice", target_id="bandit_captain")
    await play_second_round(fight, warrior, mage, rogue, mover)
    third = await durable(fight)
    assert_round_changed(start, third, warrior, mage, rogue, mover)
    room = session.room
    before_events = published_payloads(room)
    last_inventory = {event["player_id"]: event for event in before_events if event["type"] == E.INVENTORY_UPDATED}
    assert rogue in last_inventory
    ability = await discovered(fight)
    assert ability["id"] == GIFT and ability["state"] == "ready"
    assert ability["eligible"] and ability["available"] and not ability["spent"]
    assert all(fragment in ability["activation_hint"] for fragment in ("round boundary", "everyone declares again"))

    observed = []

    async def observe(data, **kwargs) -> None:
        observed.append(
            (
                await durable(fight),
                session.combat_state.to_dict(),
                {m.player_id: (m.resonance.current, m.concentration.spell_id) for m in session.party.members},
                session.companion.is_conscious,
            )
        )
        if len(observed) == 1:
            raise RuntimeError("injected room send failure")

    room.local_participant.publish_data.side_effect = observe
    receipt = await fight.call("activate", id=ability["id"])
    room.local_participant.publish_data.side_effect = None
    assert receipt["id"] == GIFT and receipt["name"] == "Unravel Fate" and receipt["round"] == 2
    assert "unhappened" in receipt["dm_cue"] and "everyone declares again" in receipt["dm_cue"].lower()
    committed = await durable(fight)
    assert len(observed) == len(published_payloads(room)) - len(before_events)
    expected_tracks = {
        pid: (row["data"]["resonance"]["current"], (row["data"]["concentration"] or {}).get("spell_id"))
        for pid, row in committed["players"].items()
    }
    assert all(snap == (committed, committed["combat"], expected_tracks, True) for snap in observed)
    assert_restored(fight, committed, start, warrior)
    assert_snapshots(fight, before_events, start, last_inventory, committed, warrior, rogue, mover)

    await fight.declare()
    await fight.finish_round(3)
    replay = await fight.row()
    assert [point["round_number"] for point in replay["round_checkpoints"]] == [2, 3]
    assert replay["round_checkpoints"][0] == committed["combat"]["round_checkpoints"][0]
    assert replay["round_checkpoints"][1]["combat"]["beat"] == "declaration"
    assert all("round_checkpoints" not in point["combat"] for point in replay["round_checkpoints"])


async def play_second_round(fight: Fight, warrior: str, mage: str, rogue: str, mover: str) -> None:
    await fight.declare(
        {**defend(warrior), "kind": "ability", "action": "warrior_devastating_strike", "targets": ["bandit_captain"]},
        {**defend(mage), "kind": "ability", "action": "arcane_haste", "targets": [mage]},
        {"kind": "consume", "actor_id": rogue, "item_id": "healing_potion_minor", "target_id": rogue},
        {
            "kind": "move",
            "actor_id": mover,
            "movement_mode": "ground",
            "destination": {"x": -10, "y": 0, "z": 0},
            "reshape": [],
        },
        {**attack("bandit_1", rogue), "action": "Short Sword"},
        {**attack("bandit_2", "companion_kael"), "action": "Short Sword"},
        {**attack("bandit_3", warrior), "action": "Light Crossbow"},
        *(defend(pid) for pid in ("bandit_captain", "bandit_4", "companion_kael")),
    )
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
    ):
        for _ in range(20):
            result = await fight.call("resolve_phase")
            if offer := result.get("fate_offer"):
                await fight.call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"])
                await fight.call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")
                break
        else:
            raise AssertionError("No Fate's Thread offer during round 2")
        await fight.finish_round(3)


def assert_round_changed(start: dict, third: dict, warrior: str, mage: str, rogue: str, mover: str) -> None:
    prior = {pid: image["data"] for pid, image in start["players"].items()}
    after = {pid: row["data"] for pid, row in third["players"].items()}
    assert third["combat"]["round_checkpoints"][-1]["players"][warrior]["session_flags"]["weapon_used"]
    assert not start["players"][warrior]["session_flags"]["weapon_used"]
    assert after[warrior]["stamina"]["current"] < prior[warrior]["stamina"]["current"]
    assert after[warrior]["patron_gifts"]["zhael_fates_thread"]["uses_spent"] == 1
    assert after[mage]["focus"]["current"] < prior[mage]["focus"]["current"]
    assert after[mage]["resonance"]["current"] > prior[mage]["resonance"]["current"]
    assert after[mage]["concentration"]["spell_id"] == "arcane_haste"
    assert after[warrior]["hp"]["current"] < prior[warrior]["hp"]["current"]
    assert after[rogue]["hp"]["current"] < prior[rogue]["hp"]["current"]
    assert after[rogue]["temp_hp"] < prior[rogue]["temp_hp"]
    assert not after[rogue]["flags"].get("shadow_veil")
    inventory = {slot["item_id"]: slot["data"] for slot in third["slots"] if slot["player_id"] == rogue}
    assert "healing_potion_minor" not in inventory
    assert inventory["leather_armor_basic"]["current_hits"] < 10
    before_combat, combat = start["combat"], third["combat"]
    assert combat["spatial"]["positions"][mover] != before_combat["spatial"]["positions"][mover]
    before = {p["id"]: p for p in before_combat["participants"]}
    current = {p["id"]: p for p in combat["participants"]}
    assert current["bandit_captain"]["hp_current"] < before["bandit_captain"]["hp_current"]
    assert current["bandit_captain"]["conditions"] != before["bandit_captain"]["conditions"]
    assert any(condition["type"] == "mark_of_justice" for condition in current["bandit_captain"]["conditions"])
    assert current["companion_kael"]["is_fallen"] and not before["companion_kael"]["is_fallen"]


def assert_snapshots(
    fight: Fight, before: list, start: dict, last_inventory: dict, committed: dict, warrior: str, rogue: str, mover: str
) -> None:
    room = fight.session.room
    output = [
        (json.loads(call.args[0]), call.kwargs.get("destination_identities"))
        for call in room.local_participant.publish_data.call_args_list[len(before) :]
    ]
    hp = {dest[0]: (data["current"], data["temp_hp"]) for data, dest in output if data["type"] == E.HP_CHANGED}
    assert hp == {
        pid: (image["data"]["hp"]["current"], image["data"]["temp_hp"]) for pid, image in start["players"].items()
    }
    assert {data["caster_id"]: data["state"] for data, _ in output if data["type"] == E.RESONANCE_CHANGED} == {
        pid: get_resonance_state(
            row["data"]["resonance"]["current"],
            flickering_bonus=row["data"]["resonance"].get("flickering_bonus", 0),
        )
        for pid, row in committed["players"].items()
    }
    assert [data for data, _ in output if data["type"] == E.COMBAT_UI_UPDATE] == [
        {"type": E.COMBAT_UI_UPDATE, **build_combat_ui_update(fight.session.combat_state)}
    ]
    patron = {dest[0]: data for data, dest in output if data["type"] == E.PATRON_ABILITIES_UPDATED}
    assert patron.keys() == {warrior, rogue, mover}
    assert not next(row for row in patron[rogue]["abilities"] if row["id"] == "syrath_veilstep")["spent"]
    assert next(row for row in patron[warrior]["abilities"] if row["id"] == GIFT)["spent"]
    assert not next(row for row in patron[mover]["abilities"] if row["id"] == "valdris_mark_of_justice")["spent"]
    inventory = {data["player_id"]: data for data, _ in output if data["type"] == E.INVENTORY_UPDATED}
    assert inventory.keys() == {rogue}
    for owner, data in inventory.items():
        assert int(data["inventory_revision"]) > int(last_inventory[owner]["inventory_revision"])
        assert int(data["inventory_revision"]) == committed["players"][owner]["inventory_revision"]
        restored_slots = {item["id"]: item["slot_info"] for item in data["inventory"]}
        assert restored_slots["healing_potion_minor"]["quantity"] == 1
        assert restored_slots["leather_armor_basic"]["current_hits"] == 10


SCENARIOS = {GIFT: ("zhael_unravel_fate:activate", whole_round, [()])}
