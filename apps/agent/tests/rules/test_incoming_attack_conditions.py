import json
from pathlib import Path
from typing import Any, cast

import pytest

import check_resolution_attack
from combat_hold import _replay_resolver
from combat_support import roll_attack, serialize_roll
from session_data import CombatParticipant


class ScriptedRng:
    def __init__(self, values: list[int]):
        self.values = iter(values)
        self.calls: list[tuple[int, int]] = []

    def randint(self, low: int, high: int) -> int:
        self.calls.append((low, high))
        value = next(self.values)
        assert low <= value <= high
        return value


class RealResolver:
    def __init__(self, rng: ScriptedRng):
        self.rng = rng

    def resolve_attack(
        self,
        attacker_data,
        action,
        target_ac,
        target_hp,
        attack_mod=0,
        damage_mult=1.0,
        target_conditions=(),
    ):
        kwargs = {
            "rng": self.rng,
            "attack_mod": attack_mod,
            "damage_mult": damage_mult,
        }
        kwargs["target_conditions"] = target_conditions
        return check_resolution_attack.resolve_attack(attacker_data, action, target_ac, target_hp, **kwargs)


def _condition(name: str) -> dict:
    return {"type": name, "duration": 2, "source": "test", "stacks": 1}


def _participant(pid: str, *, conditions=(), ac=10) -> CombatParticipant:
    return CombatParticipant(
        id=pid,
        name=pid,
        type="player" if pid == "attacker" else "enemy",
        initiative=10,
        hp_current=40,
        hp_max=40,
        ac=ac,
        attributes={"strength": 10, "dexterity": 10},
        level=1,
        conditions=list(conditions),
    )


def _roll(values, *, target_condition, attacker_conditions=(), weapon=None):
    rng = ScriptedRng(values)
    result, effective_ac = roll_attack(
        _participant("attacker", conditions=attacker_conditions),
        weapon or {"name": "Sword", "damage": "1d6", "damage_type": "slashing", "properties": []},
        _participant("target", conditions=[_condition(target_condition)]),
        resolver=cast(Any, RealResolver(rng)),
    )
    return result, effective_ac, rng


@pytest.mark.parametrize("condition", ["paralyzed", "restrained"])
def test_incoming_advantage_rolls_two_d20_and_keeps_the_higher(condition):
    values = [4, 15, 3, 4] if condition == "paralyzed" else [4, 15, 3]
    result, _, rng = _roll(values, target_condition=condition)

    assert rng.calls.count((1, 20)) == 2
    assert result.roll == 15
    assert result.hit is True


def test_attacker_disadvantage_cancels_incoming_advantage():
    result, _, rng = _roll([12, 3, 4, 5], target_condition="paralyzed", attacker_conditions=[_condition("prone")])

    assert rng.calls.count((1, 20)) == 1
    assert result.roll == 12


def test_paralyzed_target_turns_a_non_20_melee_hit_into_a_critical():
    result, _, rng = _roll([7, 12, 3, 4], target_condition="paralyzed")

    assert result.hit is True
    assert result.roll == 12
    assert result.critical_success is True
    assert result.damage == 7
    assert rng.calls.count((1, 6)) == 2
    assert result.dramatic is False
    assert result.context == ""


def _shadow_bolt() -> dict:
    catalog = json.loads((Path(__file__).resolve().parents[4] / "content" / "encounter_templates.json").read_text())
    cult = next(encounter for encounter in catalog if encounter["id"] == "cult_cell")
    leader = next(enemy for enemy in cult["enemies"] if enemy["id"] == "cult_leader")
    return next(action for action in leader["action_pool"] if action["name"] == "Shadow Bolt")


@pytest.mark.parametrize(
    ("weapon", "base_damage_dice"),
    [
        ({"name": "Bow", "damage": "1d6", "damage_type": "piercing", "ranged": True}, 1),
        (_shadow_bolt(), 2),
    ],
)
def test_ranged_hit_gets_advantage_but_not_autocrit(weapon, base_damage_dice):
    result, _, rng = _roll([8, 13, *([2] * base_damage_dice * 2)], target_condition="paralyzed", weapon=weapon)

    assert rng.calls.count((1, 20)) == 2
    assert result.critical_success is False
    assert len([call for call in rng.calls if call != (1, 20)]) == base_damage_dice


def test_double_natural_one_still_misses_a_paralyzed_target():
    result, _, rng = _roll([1, 1], target_condition="paralyzed")

    assert rng.calls.count((1, 20)) == 2
    assert result.hit is False
    assert result.damage == 0
    assert result.critical_failure is True


def test_held_replay_keeps_the_serialized_autocrit_when_paralysis_is_gone():
    result, effective_ac, _ = _roll([7, 12, 3, 4], target_condition="paralyzed")
    head = {"actor_id": "attacker", "roll": serialize_roll(result, effective_ac)}

    replayed = _replay_resolver(head).resolve_attack({}, {}, effective_ac, 40, target_conditions=[])

    assert replayed == result
    assert replayed.critical_success is True
