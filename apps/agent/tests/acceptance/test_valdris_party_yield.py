"""Party yield through registered tools, the combat checkpoint and the HUD wire."""

import json
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools
from acceptance import test_opportunity_strike, turn_undead_harness
from acceptance._capstone_helpers import _player
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_opportunity_strike import STRIKE, advance_to_departure
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.turn_undead_harness import TurnFight
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_encounter_facts_damage import GOBLIN, OTHER, Fight, catalog_clause, dice, fight, goblin_strike
from voice_condition_fixtures import participant, place_actors
from weapon_fixtures import DAGGER

import ability_persistence
import character_spells
import db
import db_mutations
from combat_agent import CombatAgent
from session_data import CompanionState

CLAUSE = "valdris_measured_reprisal"
FACT = "yielded_ally_attackers"
WIRE = Path(__file__).resolve().parents[4] / "packages/shared/fixtures/event_wire.json"
entered_fight = turn_undead_harness.fight
opportunity_fight = test_opportunity_strike.fight


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


def registered(f: Fight) -> None:
    f.call = game_tools(f.session, agent=CombatAgent())


def yield_action(actor: str) -> dict:
    return {"kind": "yield", "actor_id": actor}


def hud_actor(f: Fight, actor: str) -> dict:
    event = [e for e in published_payloads(f.session.room) if e["type"] == "combat_ui_update"][-1]
    return next(row for row in event["combatants"] if row["id"] == actor)


@pytest.mark.parametrize("companion", [False, True])
async def test_yield_spends_one_action_and_persists(world: SimpleNamespace, companion: bool) -> None:
    async with fight(world, "valdris", ally_hp=20) as f:
        registered(f)
        actor = f.ally if companion else f.hero
        if companion:
            ally = participant(f.session.combat_state, actor)
            ally.type = "companion"
            f.session.companion = CompanionState(actor, ally.name)

        await db_mutations.save_combat_state(f.combat_id, f.session.combat_state.to_dict())
        before = (await f.reload()).to_dict()
        with pytest.raises(ToolError, match="declared more than once"):
            await f.declare(yield_action(actor), attack(actor, GOBLIN))
        assert (await f.reload()).to_dict() == before
        assert not published_payloads(f.session.room)

        packets = await f.round(yield_action(actor), faces=())
        (receipt,) = [packet for packet in packets if packet["actor_id"] == actor]
        assert receipt["resolved"] and receipt["declaration_type"] == "yield" and receipt["yielded"]
        assert "action" in receipt["dm_cue"]
        assert participant(f.session.combat_state, GOBLIN).hp_current == 50
        assert not [e for e in published_payloads(f.session.room) if e.get("roll_type") == "attack"]
        (fixture,) = json.loads(WIRE.read_text())["events"]["party_yield_combat"]["combatants"]
        row = hud_actor(f, actor)
        assert row.keys() == fixture.keys() and row["yielded"] is fixture["yielded"] is True
        await f.round(faces=())
        assert participant(await f.reload(), actor).yielded

        packets = await f.round(attack(actor, GOBLIN), faces=(2,))
        strike = next(packet for packet in packets if packet["actor_id"] == actor)
        assert strike["hit"] is False and strike["damage"] == 0
        assert strike["yield_ended"] and strike["yielded"] is False
        assert hud_actor(f, actor)["yielded"] is False
        assert not participant(await f.reload(), actor).yielded
        later = await f.round(attack(actor, GOBLIN), faces=(2,))
        assert "yield_ended" not in next(packet for packet in later if packet["actor_id"] == actor)


async def measured_reprisal(world: SimpleNamespace) -> None:
    async with fight(world, "valdris", ally_hp=20) as f:
        registered(f)
        companion = participant(f.session.combat_state, f.ally)
        companion.type = "companion"
        f.session.companion = CompanionState(companion.id, companion.name)
        await f.round(yield_action(f.hero), yield_action(companion.id), faces=())
        packets = await f.round(goblin_strike(GOBLIN, f.hero), goblin_strike(OTHER, companion.id), faces=(15, 2))
        miss = next(packet for packet in packets if packet["actor_id"] == OTHER)
        assert miss["hit"] is False and miss["damage"] == 0
        assert (await f.reload()).encounter_facts[FACT] == [GOBLIN, OTHER]
        await f.round(goblin_strike(OTHER, f.ally), faces=(2,))
        assert (await f.reload()).encounter_facts[FACT] == [GOBLIN, OTHER]
        await f.hit(CLAUSE)
        assert not participant(await f.reload(), f.hero).yielded
        assert f.session.combat_state.encounter_facts[FACT] == [GOBLIN, OTHER]
        await catalog_clause(f, "valdris", CLAUSE)


SCENARIOS = {CLAUSE: ("patron_synergy_combat:encounter_damage_clause", measured_reprisal, [()])}


@pytest.mark.parametrize(
    "action",
    [
        "shove",
        "warrior_taunt",
        "warrior_war_cry",
        "warrior_whirlwind",
        "rogue_exploit_weakness",
        "arcane_bolt",
        "arcane_hold_person",
    ],
)
async def test_hostile_actions_end_yield(world: SimpleNamespace, action: str) -> None:
    caster = action.startswith("arcane_")
    archetype = {"arcane": "mage", "rogue": "rogue"}.get(action.split("_", 1)[0], "warrior")
    async with fight(world, "valdris", archetype=archetype) as f:
        registered(f)
        participant(f.session.combat_state, f.hero).level = 8
        await configure(
            world,
            "valdris",
            archetype,
            level=8,
            stamina={"current": 10},
            focus={"current": 10},
            equipment={"main_hand": DAGGER},
        )
        if caster:
            await character_spells.record_learned(f.hero, action, "training", is_prepared=True, conn=world.pool)
        elif action != "shove":
            await ability_persistence.set_elective_equipped(f.hero, action, True, conn=world.pool)
        await f.round(yield_action(f.hero), faces=())
        declaration = (
            {"kind": "maneuver", "actor_id": f.hero, "target_id": GOBLIN}
            if action == "shove"
            else ability_action(
                f.hero, action, *(() if action in ("warrior_war_cry", "warrior_whirlwind") else (GOBLIN,))
            )
        )
        packets = await f.round(declaration, faces=(15, 15))
        receipt = next(packet for packet in packets if packet["actor_id"] == f.hero)
        assert receipt["resolved"]
        if caster:
            assert receipt["action"] == action and receipt["cast"]["effect"]
            assert ("damage_result" in receipt["cast"]) is (action == "arcane_bolt")
            assert "yield_ended" not in receipt["cast"].get("damage_result", {})
        elif action == "shove":
            assert receipt["shove"] in ("resisted", "knocked_prone")
        else:
            assert receipt["action"] == action
        if action == "warrior_whirlwind":
            assert len(receipt["attacks"]) == 2
            assert [swing.get("yield_ended") for swing in receipt["attacks"]] == [True, None]
        assert receipt["yield_ended"] is True and receipt["yielded"] is False
        assert hud_actor(f, f.hero)["yielded"] is False
        assert not participant(await f.reload(), f.hero).yielded


def ability_action(actor: str, action: str, *targets: str) -> dict:
    return {"kind": "ability", "actor_id": actor, "action": action, "targets": list(targets), "argument_type": ""}


@pytest.mark.parametrize("version", [0, 5, 6, 7])
async def test_legacy_combat_records_new_attempts(world: SimpleNamespace, version: int) -> None:
    async with fight(world, "valdris", ally_hp=20) as f:
        registered(f)
        data = f.session.combat_state.to_dict()
        for actor in data["participants"]:
            del actor["yielded"]
        if version == 0:
            del data["encounter_facts"]
        else:
            facts = data["encounter_facts"]
            del facts[FACT]
            if version < 7:
                del facts["rally_pending"]
            if version < 6:
                del facts["party_aggressors"]
        await db_mutations.save_combat_state(f.combat_id, data)
        restored = await f.reload()
        assert not participant(restored, f.ally).yielded and restored.encounter_facts[FACT] == []
        await f.round(yield_action(f.ally), goblin_strike(GOBLIN, f.ally), faces=(2,))
        restored = await f.reload()
        assert restored.encounter_facts[FACT] == [GOBLIN]
        assert restored.encounter_facts["party_aggressors"] == (None if version < 6 else {GOBLIN: [f.ally]})


async def test_expanded_yield_break_survives_fate_checkpoint(world: SimpleNamespace) -> None:
    async with fight(world, "zhael", extra=True) as f:
        registered(f)
        await f.round(yield_action(f.hero), faces=())
        await configure(world, "zhael", "warrior", level=5, patron_gifts={})
        await f.declare(attack(f.hero, GOBLIN))
        with dice(15, 15):
            first = (await f.call("resolve_phase"))["fate_offer"]
            assert first["roller_id"] == f.hero and participant(await f.reload(), f.hero).yielded
            second = (await f.call("activate", id="zhael_fates_thread", offer_id=first["offer_id"], keep="original"))[
                "fate_offer"
            ]
            assert second["roller_id"] == f.hero and not participant(await f.reload(), f.hero).yielded
            resumed = await f.call("activate", id="zhael_fates_thread", offer_id=second["offer_id"], keep="original")
            receipts = [p for p in resumed["packets"] if p["actor_id"] == f.hero]
        (receipt,) = receipts
        assert receipt["yield_ended"] is True and receipt["yielded"] is False
        assert [p.get("yield_ended") for p in receipt["attacks"]] == [True, None]
        assert not participant(await f.reload(), f.hero).yielded


async def test_terminal_wrap_discards_yield_and_reprisal(entered_fight: TurnFight) -> None:
    walk = entered_fight
    foe = "witness_attacker"
    await walk.enter({foe: ("bandit", 5)}, archetype="warrior", patron="valdris", weapon=DAGGER)
    companion = _player("companion_kael", hp=20)
    companion.type = "companion"
    walk.sd.companion = CompanionState(companion.id, companion.name)
    state = await walk.reload()
    state.participants.append(companion)
    state.initiative_order.insert(1, companion.id)
    place_actors(state)
    await walk.persist()
    with dice(2):
        await walk.phase(yield_action(companion.id), {**walk.attack(foe), "target_id": companion.id})
    old = await walk.reload()
    assert walk.actor(companion.id).yielded and old.encounter_facts[FACT] == [foe]
    walk.actor(foe).hp_current = 1
    await walk.persist()
    with dice(15):
        await walk.phase(attack(walk.caster, foe))
    assert walk.last_result["outcome"] == "victory"
    assert walk.sd.combat_state is None and await db_mutations.load_combat_state(old.combat_id) is None
    assert any(event["type"] == "combat_ended" for event in walk.events())

    await walk.command("enter_mode", {"mode": "combat", "encounter_id": walk.encounter_id})
    fresh = await walk.reload()
    assert {p.id for p in fresh.participants} == {walk.caster, companion.id, foe}
    assert not any(p.yielded for p in fresh.participants)
    assert fresh.encounter_facts[FACT] == []
    before = walk.actor(foe).hp_current
    with dice(15):
        packets = await walk.phase(attack(walk.caster, foe))
    hit = next(packet for packet in packets if packet["actor_id"] == walk.caster)
    assert hit["damage"] == 6 and not hit.get("synergy_clause_id")
    assert walk.actor(foe).hp_current == before - 6


async def test_chosen_opportunity_attack_ends_yield(opportunity_fight: MawlingHarness) -> None:
    walk = opportunity_fight
    warrior = walk.players[0]
    await walk.command("declare_phase", {"declarations": [yield_action(warrior)]})
    await walk.drain()
    assert participant(await walk.reload(), warrior).yielded
    with dice(2, 15):
        window = (await advance_to_departure(walk))["next"]["waiting_on"]
        assert window["stage"] == "movement"
        await walk.command("activate", {"id": STRIKE})
        result = await walk.command("resolve_phase", {})
    (receipt,) = [p for p in result["packets"] if p.get("reaction") == STRIKE]
    assert receipt["hit"] is False and receipt["yield_ended"] is True
    assert not participant(await walk.reload(), warrior).yielded


async def test_only_a_foe_targeted_order_ends_yield(world: SimpleNamespace) -> None:
    async with fight(world, "valdris", archetype="marshal") as f:
        registered(f)
        await configure(world, "valdris", "marshal", level=5, focus={"current": 10})
        medic = "marshal_field_medic_order"
        await ability_persistence.set_elective_equipped(f.hero, medic, True, conn=world.pool)
        await f.round(yield_action(f.hero), faces=())
        packets = await f.round(ability_action(f.hero, medic, f.ally), faces=())
        receipt = next(packet for packet in packets if packet["actor_id"] == f.hero)
        assert receipt["order_rider_grant"] and "yield_ended" not in receipt
        assert participant(await f.reload(), f.hero).yielded
        packets = await f.round(ability_action(f.hero, "marshal_direct_strike", f.ally, GOBLIN), faces=())
        receipt = next(packet for packet in packets if packet["actor_id"] == f.hero)
        assert receipt["order_rider_grant"] and receipt["yield_ended"]
        assert not participant(await f.reload(), f.hero).yielded
