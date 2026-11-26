"""Sheltering Light at the registered attack and checkpoint boundaries."""

from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools
from acceptance._capstone_helpers import _damage_die, _player
from acceptance._enemy_opportunity_helpers import move
from test_aelora_gift import _live_party
from test_encounter_facts_damage import GOBLIN, OTHER, Fight, dice, fight, goblin_strike
from test_encounter_facts_heal import save
from test_fallen_ally_guard import roll_count
from voice_condition_fixtures import participant, place_actors, spatial_record

import db
import db_mutations
from activate_tools import activate
from combat_death_save import request_death_save
from combat_init_participants import class_reaction_ids
from combat_turn import declare_phase, resolve_phase
from query_tools import query_info

CLAUSE = "orenthel_guardian_ward"
FATE = "zhael_fates_thread"
BASE_AC = 14


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


def place(f: Fight, actor: str, x: float) -> None:
    spatial_record(f.session.combat_state)["positions"][actor]["x"] = x


async def persist(f: Fight) -> None:
    await db_mutations.save_combat_state(f.combat_id, f.session.combat_state.to_dict())
    await f.reload()


def ward_fields(packet: dict, bonus: int) -> None:
    assert (packet["orenthel_ac_bonus"], packet.get("orenthel_ac_clause_id")) == (bonus, CLAUSE if bonus else None)


def receipt(packet: dict, bonus: int, *, total: int = BASE_AC) -> None:
    hit = total >= BASE_AC + bonus
    assert (packet["attack_total"], packet["target_ac"], packet["hit"]) == (total, BASE_AC + bonus, hit)
    ward_fields(packet, bonus)
    assert (packet["mortaen_ac_bonus"], packet.get("mortaen_ac_clause_id")) == (0, None)
    assert (packet["synergy_ac_bonus"], packet.get("synergy_ac_clause_id")) == (0, None)
    assert packet["damage"] == (5 if hit else 0)


async def hostile_roll(f: Fight, bonus: int, *, fallen: bool = False) -> None:
    hero = participant(f.session.combat_state, f.hero)
    hp = hero.hp_current
    hostile = goblin_strike(GOBLIN, f.hero)
    if fallen:
        packets = await f.round(hostile, faces=(13, 13))
    else:
        packets = await f.round(attack(f.hero, OTHER), hostile, faces=(1, 13))
    packet = next(p for p in packets if p["actor_id"] == GOBLIN)
    receipt(packet, bonus)
    hero = participant(f.session.combat_state, f.hero)
    assert (hero.ac, hero.hp_current) == (BASE_AC, max(0, hp - packet["damage"]))


def add_companion(f: Fight) -> None:
    state = f.session.combat_state
    companion = _player("companion_kael", 20)
    companion.type, companion.hp_current = "companion", 9
    state.participants.append(companion)
    state.initiative_order.append(companion.id)
    place_actors(state)
    place(f, companion.id, -5)


async def guardian_ward(world: SimpleNamespace) -> None:
    async with fight(world, "orenthel", archetype="guardian", ally_hp=9) as f:
        add_companion(f)
        place(f, f.ally, 5)
        await hostile_roll(f, 1)
        synergy = (await f.call("query_info", kind="patron"))["synergy"]
        assert (synergy["name"], synergy["type"]) == ("Sheltering Light", "divine")
        assert synergy["clauses"] == [
            {
                "effect": "Gain +1 AC while guarding an ally below half HP.",
                "status": "active",
                "resolution": "engine",
                "implementation_id": CLAUSE,
            }
        ]


SCENARIOS = {CLAUSE: ("patron_synergy_combat:wounded_ally_defense", guardian_ward, [()])}


async def test_guardian_ward(world: SimpleNamespace) -> None:
    await guardian_ward(world)


@pytest.mark.parametrize(
    "control",
    ["half", "above_half", "fallen", "far", "patron", "class", "self", "enemy", "hollowed", "fallen_guardian"],
)
async def test_ward_eligibility(world: SimpleNamespace, control: str) -> None:
    patron = "thyra" if control == "patron" else "orenthel"
    archetype = "warrior" if control == "class" else "guardian"
    ally_hp = {"half": 10, "above_half": 11, "fallen": 0, "self": 20, "enemy": 20}.get(control, 9)
    async with fight(world, patron, archetype=archetype, ally_hp=ally_hp, hollowed=control == "hollowed") as f:
        state = f.session.combat_state
        hero, ally = participant(state, f.hero), participant(state, f.ally)
        ally.is_fallen = control == "fallen"
        if control == "hollowed":
            ally.type = "temporary_hollowed"
        place(f, f.ally, 6 if control == "far" else 5)
        if control == "self":
            hero.hp_current = 49
        if control == "enemy":
            participant(state, OTHER).hp_current = 9
            place(f, OTHER, 5)
        if control == "fallen_guardian":
            hero.hp_current, hero.is_fallen = 0, True
        await hostile_roll(f, 0, fallen=hero.is_fallen)


async def test_companion_can_supply_ward(world: SimpleNamespace) -> None:
    async with fight(world, "orenthel", archetype="guardian", ally_hp=20) as f:
        add_companion(f)
        await hostile_roll(f, 1)


async def test_opportunity_uses_interrupt_position(world: SimpleNamespace) -> None:
    async with fight(world, "orenthel", archetype="guardian", ally_hp=9) as f:
        place(f, f.ally, 10)
        place(f, OTHER, -30)
        packets = await f.round(move(f.hero, 20), faces=(13,))
        (strike,) = [p for p in packets if p.get("opportunity_attack")]
        assert strike["interrupt_position"] == {"x": 5, "y": 0, "z": 0}
        receipt(strike, 1)
        assert spatial_record(f.session.combat_state)["positions"][f.hero]["x"] == 20


async def test_hostile_save_ignores_ward(world: SimpleNamespace) -> None:
    async with fight(world, "orenthel", archetype="guardian", ally_hp=9) as f:
        place(f, f.ally, 5)
        hp = participant(f.session.combat_state, f.hero).hp_current
        participant(f.session.combat_state, GOBLIN).action_pool.append(
            {
                "name": "Dust",
                "resolution": "save",
                "save": "dex",
                "dc": 14,
                "damage": "1d6",
                "damage_type": "force",
                "type": "ranged",
                "reach": 60,
                "save_success_damage": "half",
                "conditions_on_failure": [],
                "conditions_on_success": [],
            }
        )
        with patch("combat_enemy_action.dice_roll", return_value=_damage_die(5)):
            packets = await f.round({**attack(GOBLIN, f.hero), "action": "Dust"}, faces=(13,))
        packet = next(p for p in packets if p["actor_id"] == GOBLIN)
        assert packet["save_total"] == 13
        assert (packet["save_dc"], packet["save_success"], packet["damage"]) == (14, False, 5)
        assert {"orenthel_ac_bonus", "orenthel_ac_clause_id"}.isdisjoint(packet)
        assert participant(f.session.combat_state, f.hero).hp_current == hp - 5


@pytest.mark.parametrize("change", ["move_away", "heal_to_half", "move_into_range"])
async def test_fate_hold_freezes_ward(world: SimpleNamespace, change: str) -> None:
    bonus = int(change != "move_into_range")
    async with fight(world, "orenthel", archetype="guardian", ally_hp=9) as f:
        place(f, f.ally, 5 if bonus else 10)
        hp = participant(f.session.combat_state, f.hero).hp_current
        lifecycle = _live_party(f.session, *world.ids)
        try:
            await f.declare(attack(f.hero, OTHER), goblin_strike(GOBLIN, f.hero))
            with dice(1):
                await f.call("resolve_phase")
            await configure(world, "zhael", "warrior", index=1, patron_gifts={"zhael_lucky": {"spent": True}})
            with dice(13):
                offer = (await f.call("resolve_phase"))["fate_offer"]
                assert (offer["roller_id"], offer["total"]) == (GOBLIN, BASE_AC)
                held = await f.reload()
                stored = held.held_actions[0]["fate_attack"]
                assert stored["prepared"]["d20"]["dc"] == BASE_AC + bonus
                ward_fields(stored["attacker_data"], bonus)
                assert participant(held, f.hero).hp_current == hp
                if change == "heal_to_half":
                    participant(held, f.ally).hp_current = 10
                    await configure(world, "zhael", "warrior", index=1, hp={"current": 10, "max": 20})
                else:
                    place(f, f.ally, 10 if bonus else 5)
                await persist(f)
                with f.session._bind_authenticated_actor(f.ally, 1, lifecycle.require_authorized):
                    settled = await f.call("activate", id=FATE, offer_id=offer["offer_id"], keep="original")
            packet = settled["packets"][0]
            receipt(packet, bonus)
            assert participant(await f.reload(), f.hero).hp_current == hp - packet["damage"]
            if settled["beat"] != "declaration":
                assert (await f.call("resolve_phase"))["beat"] == "declaration"
            await configure(
                world,
                "zhael",
                "warrior",
                index=1,
                patron_gifts={key: {"spent": True} for key in (FATE, "zhael_lucky")},
            )
            await hostile_roll(f, 1 - bonus)
        finally:
            await lifecycle.aclose()


@pytest.mark.parametrize("bonus", [0, 1], ids=["revival", "move_away"])
async def test_post_roll_hold_freezes_ward(world: SimpleNamespace, bonus: int) -> None:
    async with fight(world, "orenthel", archetype="guardian", ally_hp=9 if bonus else 0) as f:
        await configure(world, "orenthel", "guardian", level=6)
        guardian = participant(f.session.combat_state, f.hero)
        guardian.level = 6
        guardian.reaction_ids = class_reaction_ids("guardian", 6)
        guardian.has_reaction_ability = True
        hp = guardian.hp_current
        participant(f.session.combat_state, f.ally).is_fallen = not bonus
        place(f, f.ally, 5)
        f.call = game_tools(f.session, declare_phase, resolve_phase, request_death_save, activate, query_info)
        await f.declare(attack(f.hero, OTHER), goblin_strike(GOBLIN, f.hero))
        with dice(1, 15):
            for _ in range(3):
                window = (await f.call("resolve_phase"))["next"]["waiting_on"]
                if window and window["stage"] == "post_roll":
                    break
            else:
                raise AssertionError("no post-roll reaction window")
        assert (window["actor_id"], window["target_id"]) == (GOBLIN, f.hero)
        assert (f.hero, "guardian_retaliating_shield") in {(c["actor_id"], c["id"]) for c in window["reactions"]}
        state = await f.reload()
        assert participant(state, f.hero).hp_current == hp
        held = state.held_actions[0]["roll"]
        assert held["effective_ac"] == BASE_AC + bonus
        receipt(held["attack_result"], bonus, total=16)
        rolls = roll_count(f)
        if bonus:
            place(f, f.ally, 10)
            await persist(f)
        else:
            assert (await save(f.call, f.ally, 20))["revived"]
            ally = participant(await f.reload(), f.ally)
            assert (ally.hp_current, ally.is_fallen) == (1, False)
        with dice():
            result = await f.call("resolve_phase")
        packet = next(p for p in result["packets"] if p["actor_id"] == GOBLIN)
        assert packet["resolved"], packet
        receipt(packet, bonus, total=16)
        state = await f.reload()
        assert not state.held_actions
        assert participant(state, f.hero).hp_current == hp - 5
        assert roll_count(f) == rolls
