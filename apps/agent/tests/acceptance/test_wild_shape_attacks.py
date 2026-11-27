"""Natural attacks and restored weapons through the registered combat tools."""

import json
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_opportunity_strike import MOVER, STRIKE, advance_to_departure, participant
from acceptance.test_opportunity_strike import fight as fight
from acceptance.test_wild_shape import ABILITY, declare, enter, prepare, updates
from acceptance.test_wild_shape import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_wild_shape import walk as walk
from acceptance.test_wild_shape_lifecycle import DISMISS, player_declaration
from sample_fixtures import FixedRng, published_payloads

import db_queries
import event_types
from combat_spatial import require_spatial
from creature_catalog import query_creature_by_id
from dice import DiceResult, roll

FOE = "bandit_1"


def attack(pid: str, selection: str) -> dict:
    return {
        "kind": "attack",
        "actor_id": pid,
        "target_id": FOE,
        "action": selection,
        "held_item_id": "",
        "rider": "",
        "quick_fingers_mode": "",
        "quick_fingers_item": "",
        "reshape": [],
    }


async def shift(walk: MawlingHarness, form: str, *, reach: int = 5, resistant: bool = False) -> tuple[str, list]:
    pid = await prepare(walk, "druid", 10 if form == "dire_bear" else 5)
    row = await db_queries.get_player(pid)
    assert row is not None and row["equipment"]["main_hand"]["name"] == "Longsword"
    row["attributes"]["strength"] = 20
    await walk.pool.execute("UPDATE players SET data=$2 WHERE player_id=$1", pid, json.dumps(row))
    await enter(walk)
    state = await walk.reload()
    original_pool = participant(state, pid).action_pool
    foe = participant(state, FOE)
    foe.hp_current = foe.hp_max = 50
    foe.ac = 12
    if resistant:
        foe.damage_affinities = {"resistant": ["piercing"]}
    spatial = require_spatial(state)
    spatial["positions"].update({pid: point(0), FOE: point(reach)})
    spatial["speeds"][pid] = 0
    await walk.persist()
    await declare(walk, ABILITY, form)
    await walk.drain()
    return pid, original_pool


def point(x: int) -> dict:
    return {"x": x, "y": 0, "z": 0}


def damage_roll(notation: str, **_kwargs: object) -> DiceResult:
    return roll(notation, rng=FixedRng(3))


async def swing(
    walk: MawlingHarness,
    pid: str,
    selection: str,
    *,
    face: int = 18,
    notation: str | None = None,
    d20s: int = 1,
) -> tuple[dict, dict]:
    roster = await player_declaration(walk, attack(pid, selection))
    assert isinstance(roster, dict)
    offered = next(p for p in roster["participants"] if p["id"] == pid)
    pending = (await walk.reload()).pending_declarations[pid]
    assert pending["action"] == (selection or offered["actions"][0])
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)) as rolls,
        patch("check_resolution_attack.dice_roll", side_effect=damage_roll) as damage,
    ):
        packets = await walk.drain()
    assert rolls.call_count == d20s
    assert [call.args[0] for call in damage.call_args_list] == ([notation] if notation else [])
    return next(p for p in packets if p["actor_id"] == pid), offered


@pytest.mark.parametrize(
    ("form", "selection", "name", "modifier", "notation", "damage_type", "damage"),
    [
        ("grey_wolf", "", "Bite", 4, "1d6+2", "piercing", 5),
        ("wild_boar", "", "Tusk", 4, "1d6+2", "slashing", 5),
        ("steppe_bison", "", "Gore", 6, "2d6+4", "piercing", 10),
        ("dire_bear", "", "Claw", 8, "1d8+5", "slashing", 8),
        ("dire_bear", "Bite", "Bite", 8, "2d6+5", "piercing", 11),
        ("dire_bear", "Maul", "Maul", 0, "2d8+5", "piercing", 11),
    ],
)
async def test_authored_attack(
    walk: MawlingHarness,
    form: str,
    selection: str,
    name: str,
    modifier: int,
    notation: str,
    damage_type: str,
    damage: int,
) -> None:
    pid, original_pool = await shift(walk, form, reach=10 if name == "Claw" else 5)
    receipt, roster = await swing(walk, pid, selection, notation=notation)
    assert (receipt["action"], receipt["attack_total"], receipt["damage_type"], receipt["damage"]) == (
        name,
        18 + modifier,
        damage_type,
        damage,
    )
    assert receipt["hit"] and receipt.get("attack_disadvantage_source") is None
    assert participant(await walk.reload(), FOE).hp_current == 50 - damage

    catalog = await query_creature_by_id(form)
    specials = {a["name"]: a["special"] for a in catalog["attacks"]}
    assert roster["actions"] == list(specials)
    assert [a["id"] for a in roster["executable_actions"]] == list(specials)
    deferred = roster["deferred_effects"]
    assert [(a["group"], a["name"]) for a in deferred] == [("attacks", name) for name in specials]
    assert [a["source"]["special"] for a in deferred] == list(specials.values())
    if name == "Claw":
        assert receipt["moved_ft"] == 0
        short, _ = await swing(walk, pid, "Bite", d20s=0)
        assert not short["attack_resolved"] and "beyond reach 5" in short["reason"]
        assert participant(await walk.reload(), FOE).hp_current == 50 - damage
    if name == "Maul":
        miss, _ = await swing(walk, pid, "Maul", face=5)
        assert miss["action"] == "Maul" and miss["attack_total"] == 5 and not miss["hit"]
        assert participant(await walk.reload(), FOE).hp_current == 50 - damage
    if form == "grey_wolf":
        assert not (await walk.reload()).round_checkpoints[-1]["players"][pid]["session_flags"]["weapon_used"]
        await player_declaration(walk, {"kind": "interact", "actor_id": pid, "action": DISMISS})
        await walk.drain()
        own_shape = participant(await walk.reload(), pid)
        assert own_shape.action_pool == original_pool and own_shape.deferred_effects == []
        error = await player_declaration(walk, attack(pid, ""), error=True)
        assert "attack declaration requires an 'action'" in error
        weapon, weapon_roster = await swing(walk, pid, "Longsword", notation="1d8", d20s=2)
        assert (weapon["action"], weapon["damage_type"], weapon["damage"]) == ("Longsword", "slashing", 8)
        assert weapon["attack_disadvantage_source"] == "weapon_proficiency"
        assert weapon_roster["actions"] == ["Longsword"]
        restored = await walk.reload()
        assert participant(restored, FOE).hp_current == 50 - damage - 8
        assert restored.round_checkpoints[-1]["players"][pid]["session_flags"]["weapon_used"]


async def test_form_refuses_weapon_and_unknown_attack(walk: MawlingHarness) -> None:
    pid, _ = await shift(walk, "grey_wolf")
    before, events = await walk.snapshot(), updates(walk)
    for selection in ("Longsword", "Gore"):
        error = await player_declaration(walk, attack(pid, selection), error=True)
        assert isinstance(error, str) and selection in error and "available actions: ['Bite']" in error
        assert await walk.snapshot() == before and updates(walk) == events

    interact = {"kind": "interact", "actor_id": pid, "action": ""}
    attack_consume = {
        "kind": "attack_consume",
        "actor_id": pid,
        "target_id": FOE,
        "action": "",
        "item_id": "healing_potion_basic",
        "heal_target_id": "",
    }
    for declaration, kind in ((interact, "interact"), (attack_consume, "attack")):
        error = await player_declaration(walk, declaration, error=True)
        assert f"{kind} declaration requires an 'action'" in error
        assert await walk.snapshot() == before and updates(walk) == events


async def test_bite_uses_piercing_resistance(walk: MawlingHarness) -> None:
    pid, _ = await shift(walk, "grey_wolf", resistant=True)
    receipt, _ = await swing(walk, pid, "Bite", notation="1d6+2")
    assert (receipt["damage_type"], receipt["damage"]) == ("piercing", 2)
    assert participant(await walk.reload(), FOE).hp_current == 48


async def test_opportunity_strike_uses_bite(fight: MawlingHarness) -> None:
    pid = await prepare(fight, "druid", level=10, stamina=6)
    row = await db_queries.get_player(pid)
    assert row is not None and row["equipment"]["main_hand"]["name"] == "Longsword"
    await declare(fight, ABILITY, "grey_wolf")
    await fight.drain()
    departure = await advance_to_departure(fight)
    waiting = departure["next"]["waiting_on"]
    assert [(entry["actor_id"], entry["id"]) for entry in waiting["reactions"]] == [(pid, STRIKE)]
    # Grant the warrior reaction for this walk while still exercising its real activation and spend.
    with patch("abilities.owns_ability", return_value=True):
        await fight.command("activate", {"id": STRIKE})
    before = participant(await fight.reload(), MOVER).hp_current
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", side_effect=damage_roll) as damage,
    ):
        result = await fight.command("resolve_phase", {})
    (receipt,) = [p for p in result["packets"] if p.get("reaction") == STRIKE]
    assert (receipt["action"], receipt["attack_total"], receipt["damage_type"], receipt["damage"]) == (
        "Bite",
        22,
        "piercing",
        5,
    )
    assert (receipt["to_hit"], receipt["damage_dice"]) == (4, "1d6+2")
    assert damage.call_args_list[0].args[0] == "1d6+2"
    assert receipt.get("attack_disadvantage_source") is None
    assert participant(await fight.reload(), MOVER).hp_current == before - 5
    assert fight.sd.room is not None
    assert any(
        event["type"] == event_types.DICE_ROLL and event["modifier"] == 4 and event["total"] == 22
        for event in published_payloads(fight.sd.room)
    )
