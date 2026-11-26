"""Orenthel's wounded-ally clauses through the registered combat tools."""

from types import SimpleNamespace

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack
from acceptance._capstone_helpers import _player
from test_encounter_facts_damage import GOBLIN, OTHER, Fight, catalog_clause, dice, fight, goblin_strike
from test_fallen_ally_guard import roll_count
from voice_condition_fixtures import participant, place_actors, spatial_record

import db_mutations
from _gods_content import load_gods
from combat_init_participants import class_reaction_ids

SHELTERING_LIGHT = "orenthel_sheltering_light"
DAWNWARD_STRIKE = "orenthel_dawnward_strike"
WOUNDED_ALLY = (
    "while another conscious party member in this encounter is above 0 HP and below half their effective maximum HP."
)


def test_orenthel_catalog_clauses() -> None:
    matrix = next(g for g in load_gods() if g["god_id"] == "orenthel")["layer_4_synergy_matrix"]
    for archetype, name, effect, clause_id in (
        ("guardian", "Sheltering Light", f"Gain +1 AC {WOUNDED_ALLY}", SHELTERING_LIGHT),
        ("warrior", "Dawnward Strike", f"Gain +1 damage against undead {WOUNDED_ALLY}", DAWNWARD_STRIKE),
    ):
        assert matrix[archetype] == {
            "type": "divine",
            "name": name,
            "clauses": [
                {
                    "effect": effect,
                    "status": "active",
                    "resolution": "engine",
                    "implementation_id": clause_id,
                }
            ],
        }


def add_wounded_companion(f: Fight) -> None:
    state = f.session.combat_state
    companion = _player("companion_kael", 9)
    companion.type = "companion"
    companion.hp_max = 20
    state.participants.append(companion)
    state.initiative_order.append(companion.id)
    place_actors(state)


def ac_receipt(packet: dict, bonus: int, *, hit: bool, clause: str | None = SHELTERING_LIGHT) -> None:
    assert (packet["target_ac"], packet["hit"]) == (16 + bonus, hit)
    assert (packet["synergy_ac_bonus"], packet["synergy_ac_clause_id"]) == (bonus, clause if bonus else None)


async def guardian_attack(f: Fight, bonus: int, *, earlier_strike: bool = False) -> None:
    state = f.session.combat_state
    hero = participant(state, f.hero)
    hero.ac = 16
    hp = hero.hp_current
    strikes = [attack(f.hero, OTHER), goblin_strike(GOBLIN, f.hero)]
    faces = (1, 15)
    if earlier_strike:
        strikes.insert(1, goblin_strike(OTHER, f.ally))
        faces = (1, 15, 15)
    else:
        spatial_record(state)["positions"][f.ally]["x"] = 120
    packets = await f.round(*strikes, faces=faces)
    packet = next(p for p in packets if p["actor_id"] == GOBLIN)
    assert packet["attack_total"] == 16
    ac_receipt(packet, bonus, hit=not bonus)
    assert packet["damage"] == (0 if bonus else 5)
    assert participant(f.session.combat_state, f.hero).hp_current == hp - packet["damage"]


async def sheltering_light(world: SimpleNamespace) -> None:
    async with fight(world, "orenthel", archetype="guardian", ally_hp=9) as f:
        await guardian_attack(f, 1)
        orenthel = next(g for g in load_gods() if g["god_id"] == "orenthel")
        assert (await f.call("query_info", kind="patron"))["synergy"] == orenthel["layer_4_synergy_matrix"]["guardian"]
        for hp, maximum, bonus in ((10, 20, 0), (9, 19, 1), (10, 19, 0), (0, 20, 0)):
            ally = participant(f.session.combat_state, f.ally)
            ally.hp_current, ally.hp_max, ally.is_fallen = hp, maximum, hp == 0
            await guardian_attack(f, bonus)

    for source, bonus in (("self", 0), ("hostile", 0), ("companion", 1), ("kaelen", 0), ("earlier_strike", 1)):
        patron = "kaelen" if source == "kaelen" else "orenthel"
        ally_hp = 9 if source == "kaelen" else 10 if source == "earlier_strike" else 20
        async with fight(world, patron, archetype="guardian", ally_hp=ally_hp) as f:
            state = f.session.combat_state
            if source == "self":
                participant(state, f.hero).hp_current = 40
            elif source == "hostile":
                hostile = participant(state, OTHER)
                hostile.hp_current, hostile.hp_max = 9, 20
            elif source == "companion":
                add_wounded_companion(f)
            await guardian_attack(f, bonus, earlier_strike=source == "earlier_strike")
            if source == "earlier_strike":
                assert participant(f.session.combat_state, f.ally).hp_current == 5


async def dawnward_strike(world: SimpleNamespace) -> None:
    async with fight(world, "orenthel", ally_hp=9) as f:
        participant(f.session.combat_state, GOBLIN).category = "undead"
        await f.hit(DAWNWARD_STRIKE)
        await catalog_clause(f, "orenthel", DAWNWARD_STRIKE)
        participant(f.session.combat_state, GOBLIN).category = "beast"
        await f.hit(None)

    for source, clause in (("companion", DAWNWARD_STRIKE), ("self", None), ("kaelen", None)):
        patron = "kaelen" if source == "kaelen" else "orenthel"
        async with fight(world, patron, ally_hp=9 if source == "kaelen" else 20) as f:
            state = f.session.combat_state
            participant(state, GOBLIN).category = "undead"
            if source == "companion":
                add_wounded_companion(f)
            elif source == "self":
                participant(state, f.hero).hp_current = 40
            await f.hit(clause)


SCENARIOS = {
    SHELTERING_LIGHT: ("patron_synergy_combat:wounded_ally_defense", sheltering_light, [()]),
    DAWNWARD_STRIKE: ("patron_synergy_combat:encounter_damage_clause", dawnward_strike, [()]),
}


@pytest.mark.parametrize(
    ("patron", "ally_hp", "clause", "next_bonus"),
    [
        ("orenthel", 9, SHELTERING_LIGHT, 0),
        ("orenthel", 10, None, 1),
        ("zhael", 9, "zhael_second_before", 0),
    ],
)
async def test_held_guardian_attack_keeps_rolled_ac(
    world: SimpleNamespace, patron: str, ally_hp: int, clause: str | None, next_bonus: int
) -> None:
    bonus = int(clause is not None)
    async with fight(world, patron, archetype="guardian", ally_hp=ally_hp) as f:
        await configure(world, patron, "guardian", level=6)
        guardian = participant(f.session.combat_state, f.hero)
        guardian.ac, guardian.level = 16, 6
        guardian.reaction_ids = class_reaction_ids("guardian", 6)
        guardian.has_reaction_ability = True
        hp, before_rolls = guardian.hp_current, roll_count(f)

        await f.declare(attack(f.hero, OTHER), goblin_strike(GOBLIN, f.hero))
        with dice(1, 16):
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
        participant(state, f.ally).hp_current = 19 - ally_hp
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        stored = (await f.reload()).held_actions[0]["roll"]
        assert stored["effective_ac"] == 16 + bonus
        ac_receipt(stored["attack_result"], bonus, hit=True, clause=clause)
        assert roll_count(f) == before_rolls + 2  # The guardian's miss and the hostile's held hit.

        result = await f.call("resolve_phase")
        packet = next(p for p in result["packets"] if p["actor_id"] == GOBLIN)
        assert packet["resolved"], packet
        assert (packet["roll"], packet["attack_total"], packet["damage"]) == (16, 17, 5)
        ac_receipt(packet, bonus, hit=True, clause=clause)
        state = await f.reload()
        assert not state.held_actions
        assert participant(state, f.hero).hp_current == hp - 5
        assert roll_count(f) == before_rolls + 2
        if result["beat"] != "declaration":
            assert (await f.call("resolve_phase"))["beat"] == "declaration"
        await guardian_attack(f, next_bonus)
