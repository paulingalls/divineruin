"""Threshold Shield through registered combat phases and persisted attack receipts."""

from types import SimpleNamespace

from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _player
from sample_fixtures import published_payloads
from test_encounter_facts_damage import GOBLIN, OTHER, Fight, dice, fight, goblin_strike
from test_encounter_facts_heal import save
from voice_condition_fixtures import participant, place_actors, spatial_record

import db_mutations
from _gods_content import load_gods
from activate_tools import activate
from combat_death_save import request_death_save
from combat_init_participants import class_reaction_ids
from combat_state import CombatState
from combat_turn import declare_phase, resolve_phase
from query_tools import query_info

CLAUSE = "mortaen_threshold_shield"


async def drop_ally(f: Fight) -> None:
    await f.round(goblin_strike(GOBLIN, f.ally))
    ally = participant(f.session.combat_state, f.ally)
    assert (ally.hp_current, ally.is_fallen, ally.is_dead) == (0, True, False)


def receipt(packet: dict, ac: int, hit: bool, bonus: int) -> None:
    assert (packet["target_ac"], packet["hit"]) == (ac, hit)
    assert (packet["mortaen_ac_bonus"], packet["mortaen_ac_clause_id"]) == (bonus, CLAUSE if bonus else None)
    assert (packet["synergy_ac_bonus"], packet["synergy_ac_clause_id"]) == (0, None)


async def threshold_shield(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", archetype="guardian") as f:
        await drop_ally(f)
        spatial_record(f.session.combat_state)["positions"][f.ally]["x"] = 120
        for declaration, faces, total, ac in (
            (attack(f.hero, OTHER), (1, 13), 14, 15),
            (defend(f.hero), (15,), 16, 17),
        ):
            hp = participant(f.session.combat_state, f.hero).hp_current
            packets = await f.round(declaration, goblin_strike(GOBLIN, f.hero), faces=faces)
            packet = next(p for p in packets if p["actor_id"] == GOBLIN)
            assert packet["attack_total"] == total
            receipt(packet, ac, False, 1)
            assert packet["damage"] == 0
            assert participant(f.session.combat_state, f.hero).hp_current == hp

        authored = next(g for g in load_gods() if g["god_id"] == "mortaen")["layer_4_synergy_matrix"]["guardian"]
        assert (authored["name"], authored["type"]) == ("Threshold Shield", "divine")
        assert [(c["status"], c["resolution"], c.get("implementation_id")) for c in authored["clauses"]] == [
            ("active", "engine", CLAUSE)
        ]
        assert (await f.call("query_info", kind="patron"))["synergy"] == authored

    for control in (
        "companion",
        "standing",
        "dead",
        "failed_saves",
        "revived",
        "enemy",
        "not_fallen",
        "positive_hp",
        "fallen_guardian",
        "thyra",
    ):
        await check_eligibility(world, control)


async def check_eligibility(world: SimpleNamespace, control: str) -> None:
    patron = "thyra" if control == "thyra" else "mortaen"
    async with fight(world, patron, archetype="guardian") as f:
        if control in {"failed_saves", "revived"}:
            await drop_ally(f)
            call = game_tools(f.session, request_death_save)
            if control == "failed_saves":
                assert not (await save(call, f.ally, 1))["dead"]
                assert (await save(call, f.ally, 5))["dead"]
                ally = participant(await f.reload(), f.ally)
                assert not ally.is_dead and ally.death_save_failures == 3
            else:
                assert (await save(call, f.ally, 20))["revived"]
                ally = participant(await f.reload(), f.ally)
                assert (ally.hp_current, ally.is_fallen) == (1, False)

        state = f.session.combat_state
        ally = participant(state, f.ally)
        if control in {"dead", "not_fallen", "fallen_guardian", "thyra"}:
            ally.hp_current = 0
            ally.is_fallen = control != "not_fallen"
            ally.is_dead = control == "dead"
        elif control == "positive_hp":
            ally.is_fallen = True
        elif control == "enemy":
            enemy = participant(state, OTHER)
            enemy.hp_current, enemy.is_fallen = 0, True
        if control in {"companion", "fallen_guardian"}:
            companion = _player("companion_kael", 0 if control == "companion" else 20)
            companion.type = "companion"
            companion.is_fallen = control == "companion"
            state.participants.append(companion)
            state.initiative_order.append(companion.id)
            place_actors(state)

        if control == "fallen_guardian":
            hero = participant(state, f.hero)
            hero.hp_current, hero.is_fallen = 0, True
            packets = await f.round(goblin_strike(GOBLIN, f.hero), faces=(13, 13))
        else:
            packets = await f.round(attack(f.hero, GOBLIN), goblin_strike(GOBLIN, f.hero), faces=(1, 13))
        packet = next(p for p in packets if p["actor_id"] == GOBLIN)
        assert packet["attack_total"] == 14, control
        bonus = int(control == "companion")
        receipt(packet, 14 + bonus, not bonus, bonus)


SCENARIOS = {CLAUSE: ("patron_synergy_combat:fallen_ally_defense", threshold_shield, [()])}


def roll_count(f: Fight) -> int:
    return sum(event.get("roll_type") == "attack" for event in published_payloads(f.session.room))


def held_receipt(state: CombatState, ac: int, bonus: int) -> None:
    stored = state.held_actions[0]["roll"]
    assert stored["effective_ac"] == ac
    receipt(stored["attack_result"], ac, True, bonus)


async def pause_guard_attack(world: SimpleNamespace, f: Fight, *, bonus: int) -> tuple[int, int]:
    await configure(world, "mortaen", "guardian", level=6)
    guardian = participant(f.session.combat_state, f.hero)
    guardian.level = 6
    guardian.reaction_ids = class_reaction_ids("guardian", 6)
    guardian.has_reaction_ability = True
    f.call = game_tools(f.session, declare_phase, resolve_phase, request_death_save, activate, query_info)
    if bonus:
        await drop_ally(f)

    before_rolls = roll_count(f)
    await f.declare(attack(f.hero, OTHER), goblin_strike(GOBLIN, f.hero))
    with dice(1, 15):
        for _ in range(3):
            window = (await f.call("resolve_phase"))["next"]["waiting_on"]
            if window and window["stage"] == "post_roll":
                break
        else:
            raise AssertionError("no post-roll reaction window")
    assert (window["actor_id"], window["target_id"]) == (GOBLIN, f.hero)
    assert (f.hero, "guardian_retaliating_shield") in {
        (choice["actor_id"], choice["id"]) for choice in window["reactions"]
    }
    state = await f.reload()
    held_receipt(state, 14 + bonus, bonus)
    assert roll_count(f) == before_rolls + 2  # Guardian's miss and the held goblin roll.
    return participant(state, f.hero).hp_current, roll_count(f)


async def resume_guard_attack(f: Fight, hp: int, rolls: int, *, bonus: int) -> None:
    result = await f.call("resolve_phase")
    packet = next(p for p in result["packets"] if p["actor_id"] == GOBLIN)
    assert packet["resolved"], packet
    assert (packet["roll"], packet["attack_total"], packet["damage"]) == (15, 16, 5)
    receipt(packet, 14 + bonus, True, bonus)
    state = await f.reload()
    assert not state.held_actions
    assert participant(state, f.hero).hp_current == hp - 5
    assert roll_count(f) == rolls


async def test_held_guard_survives_ally_revival(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", archetype="guardian") as f:
        hp, rolls = await pause_guard_attack(world, f, bonus=1)
        assert (await save(f.call, f.ally, 20))["revived"]
        adopted = f.session.combat_state
        state = await f.reload()
        for snapshot in (adopted, state):
            ally = participant(snapshot, f.ally)
            assert (ally.hp_current, ally.is_fallen) == (1, False)
        assert (await row(world))["hp"]["current"] == 1
        held_receipt(state, 15, 1)
        await resume_guard_attack(f, hp, rolls, bonus=1)


async def test_held_zero_guard_stays_zero(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", archetype="guardian", ally_hp=20) as f:
        hp, rolls = await pause_guard_attack(world, f, bonus=0)
        state = await f.reload()
        ally = participant(state, f.ally)
        ally.hp_current, ally.is_fallen = 0, True
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        held_receipt(await f.reload(), 14, 0)
        await resume_guard_attack(f, hp, rolls, bonus=0)
