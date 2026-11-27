"""Inapplicable contexts through the registered check."""

import json
from copy import deepcopy
from unittest.mock import patch

import pytest
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools
from acceptance.synergy_discovery import discover
from acceptance.test_synergy_context import payload, setup_actor
from acceptance.test_valdris_oath_breach import dev_db_pool as dev_db_pool
from acceptance.test_valdris_oath_breach import oath_book, registered, swear
from acceptance.test_valdris_party_yield import yield_action
from acceptance.test_valdris_sanctuary import TEMPLE
from livekit.agents.llm import ToolError
from test_encounter_facts_damage import GOBLIN, OTHER, dice, fight, goblin_strike
from test_encounter_facts_heal import save as death_save
from test_zhael_marshal_rally_saves import MANUAL
from voice_condition_fixtures import participant

import db_mutations
import patron_synergy
from check_tools import check
from combat_death_save import request_death_save
from combat_support import _resolve_attack_packet
from dice import DiceResult
from encounter_testimony import Testimony as EncounterTestimony
from mode_tools import enter_mode


async def test_combat_skill_has_zero_receipt(world) -> None:
    async with fight(world, "valdris", archetype="paladin") as f:
        registered(f)
        oath = await swear(f.session)
        with dice(10):
            result = await f.call("check", roll=payload("skill", "religion", "justice_at_stake"))
        assert result["context_synergy"]["oath_justice"] == {
            "oath_id": oath["oath_id"],
            "context": "skill",
            "skill": "religion",
            "tag": "justice_at_stake",
            "modifier": 0,
            "reason": "in_combat",
        }


@pytest.mark.parametrize(
    "evidence,reason,modifier",
    [
        ("retaliation", "no_wrongdoer", 0),
        ("initiator", "no_wrongdoer", 0),
        ("other_participant", "no_wrongdoer", 0),
        ("broken_promise", "grievance", 2),
        ("injustice", "grievance", 2),
        ("yielded_ally", "yielded_ally", 2),
        ("present_witness", "testimony", 2),
        ("absent_witness", "no_wrongdoer", 0),
        ("breaking_oath", "breaking_oath", 0),
    ],
)
async def test_only_exact_recorded_wrongdoing_counts(world, evidence, reason, modifier) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        oath = await swear(f.session)
        if evidence != "breaking_oath":
            await f.round(attack(f.ally, GOBLIN), faces=(1,))
        if evidence in {"retaliation", "yielded_ally", "other_participant"}:
            if evidence == "yielded_ally":
                await f.round(yield_action(f.ally), faces=())
            await f.round(goblin_strike(OTHER if evidence == "other_participant" else GOBLIN, f.ally), faces=(1,))
        if evidence in {"broken_promise", "injustice", "breaking_oath"}:
            val = "injustice" if evidence == "breaking_oath" else evidence
            await db_mutations.set_player_flag(f.ally, f"grievance:{GOBLIN}", val)
        state = f.session.combat_state
        if evidence == "initiator":
            state.initiated_by = "enemies"
        if evidence.endswith("witness"):
            state.location_id = "millhaven" if evidence == "present_witness" else "greyvale_ruins_entrance"
            state.testimony = EncounterTestimony("elder_yanna", [GOBLIN])
        participant(state, GOBLIN).ac = 6
        packets = await f.round(attack(f.hero, GOBLIN), faces=(6,))
        packet = next(p for p in packets if p["actor_id"] == f.hero)
        assert packet["oath_justice"] == {
            "oath_id": oath["oath_id"],
            "context": "attack",
            "target_id": GOBLIN,
            "modifier": modifier,
            "reason": reason,
        }
        assert packet["attack_total"] == 7 + modifier
        assert packet["hit"] is bool(modifier)
        if evidence == "breaking_oath":
            assert packet["oath_breach"]["oath_id"] == oath["oath_id"]
            assert (await oath_book(f.hero))["records"][0]["status"] == "broken"


@pytest.mark.parametrize(
    "change,reason",
    [
        ("no_oath", "no_oath"),
        ("broken", "inactive_oath"),
        ("suppressed", "suppressed"),
        ("wrong_patron", "unheld"),
        ("wrong_class", "unheld"),
        ("wrong_owner", None),
        ("inactive_clause", "inactive_clause"),
    ],
)
async def test_tag_requires_current_unbroken_owned_oath(world, change, reason) -> None:
    await setup_actor(world, "valdris", "paladin")
    session = world.ctx.userdata
    tag = "justice_at_stake"
    if change != "no_oath":
        await swear(session)
        [record] = (await oath_book(world.ids[0]))["records"]
        book: dict = {"records": [record]}
        updates = {}
        match change:
            case "wrong_patron":
                updates["divine_favor"] = {"patron": "thyra", "level": 40, "max": 100}
            case "wrong_class":
                updates["class"] = "guardian"
            case "broken":
                record["status"] = "broken"
            case "wrong_owner":
                record["owner_id"] = world.ids[1]
            case "suppressed":
                updates["oath_session_id"] = session.session_id
                book["valdris_breach"] = dict(
                    session_id=session.session_id, breach_event_id="breach", combat_id="combat", round_number=1
                )
        await world.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
            world.ids[0],
            json.dumps({**updates, "oaths": book}),
        )
    call = game_tools(session, check)
    roll = payload("skill", "athletics", tag)
    if reason is None:
        with pytest.raises(ValueError, match="Invalid oath record ownership"):
            await call("check", roll=roll)
        return
    catalog = deepcopy(patron_synergy.load_gods())
    if change == "inactive_clause":
        god = next(g for g in catalog if g["god_id"] == "valdris")
        god["layer_4_synergy_matrix"]["paladin"]["clauses"][1]["status"] = "pending"
    with patch.object(patron_synergy, "load_gods", return_value=catalog), dice(10):
        result = await call("check", roll=roll)
    assert result["total"] == result["roll"] == 10
    assert result["context_synergy"]["oath_justice"]["reason"] == reason


@pytest.mark.parametrize("kind", ["skill", "social", "discover"])
async def test_registered_tool_refuses_unknown_justice_tag(world, kind) -> None:
    roll = discover() if kind == "discover" else payload(kind, "persuasion")
    call = game_tools(world.ctx.userdata, check)
    with pytest.raises(ToolError, match="Unknown synergy_context"), dice():
        await call("check", roll={**roll, "synergy_context": "justice_at_steak"})


async def test_narrative_dice_and_manual_saves_have_no_justice_bonus(world) -> None:
    async with fight(world, "valdris", archetype="paladin") as f:
        registered(f)
        await swear(f.session)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        with dice(10):
            combat = await f.call("check", roll=MANUAL)
        assert combat["total"] == 10
        assert combat["oath_justice"]["reason"] == "missing_source"
        f.session.combat_state = None
        with dice(10):
            outside = await f.call("check", roll=MANUAL)
        assert outside["total"] == 10
        assert outside["oath_justice"]["reason"] == "outside_combat"
        with patch("check_tools.dice.roll", return_value=DiceResult(total=10, rolls=[10], dropped=[], notation="1d20")):
            arbitrary = await f.call("check", roll={"kind": "dice", "notation": "1d20"})
        assert arbitrary["total"] == 10


async def test_oath_does_not_modify_initiative(world) -> None:
    session = world.ctx.userdata
    session.location_id = TEMPLE
    await setup_actor(world, "valdris", "paladin")
    await setup_actor(world, "thyra", "warrior", index=1)
    for player_id in world.ids:
        await world.pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{speed}', '30') WHERE player_id=$1", player_id
        )
    await swear(session)
    call = game_tools(session, enter_mode)
    try:
        with (
            patch("combat_agent.create_combat_agent"),
            patch("combat_resolution.dice_roll", return_value=DiceResult("1d20", [10], [], 10)),
        ):
            _, entered = await call(
                "enter_mode", mode="combat", encounter_id="ruins_mawling_pair", initiated_by="enemies"
            )
        actor = next(p for p in entered["initiative_order"] if p["id"] == world.ids[0])
        assert actor["total"] == actor["roll"] == 10
        assert participant(session.combat_state, world.ids[0]).initiative == 10
    finally:
        if session.combat_state is not None:
            await db_mutations.delete_combat_state(session.combat_state.combat_id, conn=world.pool)


async def test_oath_does_not_modify_death_save(world) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        await swear(f.session)
        hero = participant(f.session.combat_state, f.hero)
        hero.hp_current = 4
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(19,))
        assert participant(f.session.combat_state, f.hero).is_fallen
        receipt = await death_save(game_tools(f.session, request_death_save), f.hero, 9)
        assert receipt["roll"] == 9 and receipt["success"] is False
        assert participant(await f.reload(), f.hero).death_save_failures == 1


async def test_attack_outside_combat_has_no_justice_bonus(world) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        oath = await swear(f.session)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        state = f.session.combat_state
        attacker, target = participant(state, f.hero), participant(state, GOBLIN)
        f.session.combat_state = None
        with dice(8):
            packet = await _resolve_attack_packet(f.session, attacker, attacker.action_pool[0], target)
        assert packet["attack_total"] == 9
        assert packet["hit"] is False
        assert packet["oath_justice"] == {
            "oath_id": oath["oath_id"],
            "context": "attack",
            "target_id": target.id,
            "modifier": 0,
            "reason": "outside_combat",
        }
