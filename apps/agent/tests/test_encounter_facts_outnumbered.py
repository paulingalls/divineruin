"""Oath of Valor through registered combat phases and persisted damage."""

from random import Random
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _d20, _enemy
from combat.test_synergy_crit_edges import dice_events
from combat.test_synergy_spell_edges import authored_clause, configure_caster
from creature_combat_helpers import participant as creature_participant
from test_encounter_facts_damage import EMPTY, GOBLIN, fight
from voice_condition_fixtures import participant, place_actors

from creature_combat_loader import load_creature_enemy
from dice import DiceResult, roll

OATH = "kaelen_oath_of_valor"


async def strike(world: SimpleNamespace, case: str, damage: int, radiant: int, notations: tuple[str, ...]) -> None:
    patron = "valdris" if case == "valdris" else "kaelen"
    async with fight(world, patron, archetype="paladin", goblin_hp=100, ally_hp=20) as f:
        state = f.session.combat_state
        hero, ally, target = (participant(state, pid) for pid in (f.hero, f.ally, GOBLIN))
        declarations = [attack(f.hero, GOBLIN)]
        if case not in ("even", "fallen_ally"):
            third = _enemy("goblin_three", 1 if case == "fallen_enemy" else 100)
            state.participants.append(third)
            state.initiative_order.append(third.id)
        if case == "fallen_ally":
            ally.hp_current, ally.is_fallen = 0, True
        if case == "fallen_enemy":
            ally.initiative = hero.initiative + 1
            state.initiative_order[:2] = [f.ally, f.hero]
            declarations.insert(0, attack(f.ally, third.id))
        if case == "spell":
            await configure_caster(world, "kaelen", "paladin", "arcane_bolt")
            hero.level, hero.attributes["intelligence"] = 1, 10
            declarations = [{**defend(f.hero), "kind": "ability", "action": "arcane_bolt", "targets": [GOBLIN]}]
        if case == "echo":
            hero.type = "temporary_hollowed"
            target = ally
            declarations = [attack(f.hero, f.ally)]
        if case in ("veilrender", "immune"):
            boss = creature_participant(
                await load_creature_enemy(
                    "hollow_veilrender", encounter_id=f.combat_id, enemy_id=GOBLIN, role="standard"
                )
            )
            state.participants[state.participants.index(target)] = boss
            target = boss
            boss.hp_current = 100
            for actor in state.participants:
                actor.veilrender_turn_round = state.round_number
            if case == "immune":
                target.damage_affinities = {"immune": ["radiant"]}
        place_actors(state)
        before = target.hp_current
        await f.declare(*declarations)
        rng, calls = Random(7), []

        def seeded(notation: str, **_: object) -> DiceResult:
            calls.append(notation)
            return roll(notation, rng=rng)

        with (
            patch("check_resolution.dice_roll", return_value=_d20(20 if case == "critical" else 15)),
            patch("check_resolution_attack.dice_roll", side_effect=seeded),
            patch("patron_synergy_combat.dice_roll", side_effect=seeded),
        ):
            result = await f.call("resolve_phase")
            if case == "echo":
                result = await f.call("resolve_phase")
        packet = next(p for p in result["packets"] if p["actor_id"] == f.hero)
        if case == "spell":
            packet = packet["cast"]["damage_result"]
            assert packet["damage_type"] == "force"
        assert packet["damage"] == damage and tuple(calls) == notations
        saved = await f.reload()
        assert participant(saved, target.id).hp_current == before - damage
        receipt = dice_events(world)[-1]
        keys = ("synergy_damage", "synergy_damage_type", "synergy_clause_id")
        typed = ("radiant", OATH) if radiant or case == "immune" else (None, None)
        assert tuple(packet.get(k) for k in keys) == (radiant, *typed)
        assert tuple(receipt.get(k) for k in keys) == (radiant if typed[0] else None, *typed)
        if case == "positive":
            await authored_clause(world, "kaelen", "paladin", "divine", OATH)
            assert saved.encounter_facts == {**EMPTY, "attacked": [GOBLIN]}
        if case == "fallen_enemy":
            assert participant(saved, third.id).is_fallen
        if case in ("veilrender", "immune"):
            assert participant(saved, GOBLIN).radiant_suppression_pending == bool(radiant)
            await f.call("resolve_phase")
            next_round = f.session.combat_state
            for actor in next_round.participants:
                if actor.id != GOBLIN:
                    actor.veilrender_turn_round = next_round.round_number
            packets = await f.round(faces=())
            effect = next(
                e for row in packets for e in row.get("turn_start_effects", []) if e["effect"] == "regeneration"
            )
            assert (effect["suppressed"], effect["causes"], effect["healed"]) == (
                (True, ["radiant"], 0) if radiant else (False, [], 10)
            )
            boss = participant(f.session.combat_state, GOBLIN)
            assert (boss.radiant_suppression_pending, boss.hp_current) == (False, before - damage + effect["healed"])


async def kaelen_valor(world: SimpleNamespace) -> None:
    await strike(world, "positive", 8, 2, ("1d8", "1d6"))


SCENARIOS = {OATH: ("patron_synergy_combat:outnumbered_rider", kaelen_valor, [()])}


@pytest.mark.parametrize(
    "case,damage,radiant,notations",
    [
        pytest.param("even", 6, 0, ("1d8",), id="even"),
        pytest.param("spell", 3, 0, ("1d6",), id="spell"),
        pytest.param("valdris", 6, 0, ("1d8",), id="valdris"),
        pytest.param("critical", 19, 10, ("1d8", "1d8", "2d6"), id="critical"),
        pytest.param("fallen_ally", 8, 2, ("1d8", "1d6"), id="fallen-ally"),
        pytest.param("fallen_enemy", 3, 0, ("1d8", "1d8"), id="fallen-enemy"),
        pytest.param("echo", 6, 0, ("1d8",), id="echo"),
        pytest.param("veilrender", 10, 4, ("1d8", "1d6"), id="veilrender"),
        pytest.param("immune", 6, 0, ("1d8", "1d6"), id="immune"),
    ],
)
async def test_oath_scope(
    world: SimpleNamespace, case: str, damage: int, radiant: int, notations: tuple[str, ...]
) -> None:
    await strike(world, case, damage, radiant, notations)
