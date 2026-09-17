from typing import Any, cast

import check_resolution_attack
from combat_hold import _roll as roll_held_attack
from combat_marks import FOCUS_ATTACK_BONUS
from combat_support import roll_attack
from session_data import CombatParticipant, CombatState


class ScriptedRng:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = []

    def randint(self, low, high):
        self.calls.append((low, high))
        return next(self.values)


class RealResolver:
    def __init__(self, rng):
        self.rng = rng

    def resolve_attack(self, attacker_data, action, target_ac, target_hp, **kwargs):
        return check_resolution_attack.resolve_attack(
            attacker_data, action, target_ac, target_hp, rng=cast(Any, self.rng), **kwargs
        )


def _participant(pid, participant_type, *, conditions=()):
    return CombatParticipant(
        id=pid,
        name=pid,
        type=participant_type,
        initiative=10,
        hp_current=30,
        hp_max=30,
        ac=10,
        attributes={"strength": 10, "dexterity": 10},
        conditions=list(conditions),
    )


def _prone():
    return {"type": "prone", "duration": 2, "source": "test", "stacks": 1}


def _attack(values, *, ranged=False, attacker_prone=False):
    rng = ScriptedRng(values)
    weapon = {
        "name": "Bow" if ranged else "Sword",
        "damage": "1d6",
        "damage_type": "piercing" if ranged else "slashing",
        "properties": ["ranged"] if ranged else [],
    }
    result, _ = roll_attack(
        _participant("attacker", "player", conditions=[_prone()] if attacker_prone else []),
        weapon,
        _participant("target", "enemy", conditions=[_prone()]),
        resolver=cast(Any, RealResolver(rng)),
    )
    return result, rng


def test_melee_attack_against_prone_keeps_the_higher_d20():
    result, rng = _attack([4, 15, 3])

    assert rng.calls.count((1, 20)) == 2
    assert result.roll == 15


def test_ranged_attack_against_prone_keeps_the_lower_d20():
    result, rng = _attack([15, 4, 3], ranged=True)

    assert rng.calls.count((1, 20)) == 2
    assert result.roll == 4


def test_prone_attacker_and_prone_melee_target_cancel_to_one_d20():
    result, rng = _attack([12, 3, 4], attacker_prone=True)

    assert rng.calls.count((1, 20)) == 1
    assert result.roll == 12


def test_marked_held_melee_attack_keeps_focus_bonus_and_prone_advantage():
    attacker = _participant("attacker", "enemy")
    marker = _participant("marker", "enemy")
    target = _participant("target", "player", conditions=[_prone()])
    action = {"name": "Sword", "damage": "1d6", "damage_type": "slashing", "properties": []}
    attacker.action_pool = [action]
    state = CombatState(
        combat_id="combat",
        participants=[attacker, marker, target],
        initiative_order=[attacker.id, marker.id, target.id],
        location_id="test",
        focus_marks={target.id: {"source_id": marker.id, "kind": "command"}},
    )
    head = {
        "actor_id": attacker.id,
        "declaration": {"type": "attack", "action": action["name"], "target_id": target.id},
    }
    rng = ScriptedRng([4, 15, 3])

    result, _ = roll_held_attack(state, head, action, cast(Any, RealResolver(rng)))

    assert result.roll == 15
    assert result.attack_modifier == 1 + FOCUS_ATTACK_BONUS
